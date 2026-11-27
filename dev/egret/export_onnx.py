"""Export docling-layout-egret-medium (D-FINE) to ONNX and check it against PyTorch (dev only).

Needs a dev venv with torch (CPU), transformers, onnx, onnxscript, onnxruntime, PyMuPDF, numpy, Pillow.
With the versions in dev/egret/requirements-export.txt the export is reproducible: it rebuilds the released
tools/models/egret_medium.onnx byte for byte (SHA-256 06da7202...fbcc). PyMuPDF and Pillow are only used by --check.
The exported graph takes the already-preprocessed page tensor and returns raw outputs, so preprocessing
and post-processing live in tools/src/figure_detector/egret.py, the same code the exe runs:

    pixel_values float32 [1, 3, 640, 640] (RGB, bilinear resize, /255, no mean/std)
      -> logits [1, 300, 17], pred_boxes [1, 300, 4] (cx, cy, w, h normalized to 0..1)

Usage:
    python -X utf8 dev\\egret\\export_onnx.py --out tools\\models\\egret_medium.onnx
    python -X utf8 dev\\egret\\export_onnx.py --out tools\\models\\egret_medium.onnx --check tests\\layout_samples
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "src"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Pinned source of the released tools/models/egret_medium.onnx (see fetch_model.ps1). model.safetensors is identical
# in every revision of the repo that has weights; 77ede7cc (2026-07-31) only renamed the labels in config.json, which
# the ONNX graph does not carry. verify_onnx_weights.py checks the ONNX file against these exact weights.
from verify_onnx_weights import MODEL_ID, MODEL_REVISION, MODEL_SAFETENSORS_SHA256  # noqa: E402

INPUT_SIZE = 640


def pinned_model_dir() -> Path:
    """Download (or reuse from the HF cache) the pinned revision and refuse it unless the weights hash matches."""
    from huggingface_hub import snapshot_download

    local = Path(
        snapshot_download(
            MODEL_ID,
            revision=MODEL_REVISION,
            allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors"],
        )
    )
    weights = local / "model.safetensors"
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    if digest != MODEL_SAFETENSORS_SHA256:
        raise RuntimeError(
            f"model.safetensors of {MODEL_ID}@{MODEL_REVISION[:12]} has sha256 {digest}, "
            f"expected {MODEL_SAFETENSORS_SHA256}: refusing to export"
        )
    print(f"Weights {MODEL_ID}@{MODEL_REVISION[:12]} verified (sha256 {digest[:16]}...)")
    return local


class _RawOutputs(torch.nn.Module):
    def __init__(self, model: torch.nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(self, pixel_values: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        out = self.model(pixel_values=pixel_values)
        return out.logits, out.pred_boxes


def _double_nodes(model) -> list:
    from onnx import TensorProto, shape_inference

    inferred = shape_inference.infer_shapes(model)
    types = {
        vi.name: vi.type.tensor_type.elem_type
        for vi in [*inferred.graph.value_info, *inferred.graph.input, *inferred.graph.output]
    }
    return [n for n in inferred.graph.node if any(types.get(o) == TensorProto.DOUBLE for o in n.output)]


class _FrozenPositionEmbedding(torch.nn.Module):
    """Records the sin/cos position embedding on one eager run, then returns it as a float32 constant.

    transformers builds this embedding in float64 (Range/Sin/Cos on doubles). Double-precision Sin/Cos
    kernels are missing from some onnxruntime builds (1.26 fails with "Could not find an implementation for
    Cos(7)"). The input is fixed at 640x640, so the embedding is a constant: exporting it as an initializer
    leaves a plain float32 graph that older runtimes load too.
    """

    def __init__(self, inner: torch.nn.Module) -> None:
        super().__init__()
        self.inner = inner
        self.frozen: torch.Tensor | None = None

    def forward(self, *args, **kwargs) -> torch.Tensor:
        if self.frozen is not None:
            return self.frozen
        out = self.inner(*args, **kwargs)
        self.frozen = out.detach().clone()
        return out


def _freeze_position_embeddings(model: torch.nn.Module, dummy: torch.Tensor) -> int:
    targets = [
        (parent, name, child)
        for parent in model.modules()
        for name, child in parent.named_children()
        if type(child).__name__.endswith("SinePositionEmbedding")
    ]
    for parent, name, child in targets:
        setattr(parent, name, _FrozenPositionEmbedding(child))
    with torch.no_grad():
        model(pixel_values=dummy)
    return len(targets)


def _assert_float32_only(path: Path) -> None:
    import onnx

    left = _double_nodes(onnx.load(str(path)))
    if left:
        raise RuntimeError(f"float64 nodes in exported graph: {sorted({n.op_type for n in left})}")


def export(out_path: Path, opset: int) -> None:
    from transformers import DFineForObjectDetection

    model = DFineForObjectDetection.from_pretrained(pinned_model_dir()).eval()
    dummy = torch.rand(1, 3, INPUT_SIZE, INPUT_SIZE)
    print(f"Frozen position embeddings: {_freeze_position_embeddings(model, dummy)}")
    wrapper = _RawOutputs(model).eval()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (dummy,),
            str(out_path),
            input_names=["pixel_values"],
            output_names=["logits", "pred_boxes"],
            opset_version=opset,
            dynamo=False,
        )
    import onnx

    _assert_float32_only(out_path)
    onnx.checker.check_model(str(out_path))
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"Exported {out_path} ({out_path.stat().st_size:,} bytes, sha256 {digest})")


def _iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _same_detections(a: list, b: list, min_iou: float) -> bool:
    if len(a) != len(b):
        return False
    rest = list(b)
    for d in a:
        match = next((o for o in rest if o.label == d.label and _iou(d.box, o.box) >= min_iou), None)
        if match is None:
            return False
        rest.remove(match)
    return True


def check(onnx_path: Path, pdf_dir: Path, max_pages: int) -> None:
    """On rendered sample pages, check three things:

    1. parity   — ONNX raw outputs vs PyTorch on the same tensor, and our numpy post-processing vs
                  RTDetrImageProcessor.post_process_object_detection (must match exactly);
    2. input    — our direct 640x640 MuPDF render vs the reference path (2x render + HF processor resize):
                  not bit-identical by design, so report how many pages give the same detections (IoU >= 0.9);
    3. speed    — ONNX CPU time per page.
    """
    import pymupdf
    from PIL import Image
    from transformers import DFineForObjectDetection, RTDetrImageProcessor

    from figure_detector import egret

    model_dir = pinned_model_dir()
    model = DFineForObjectDetection.from_pretrained(model_dir).eval()
    processor = RTDetrImageProcessor.from_pretrained(model_dir)
    session = egret.load_session(onnx_path)

    worst_logit = worst_box = 0.0
    pages = post_ok = input_same = 0
    t_onnx = 0.0
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        with pymupdf.open(pdf) as doc:
            for page in doc:
                if pages >= max_pages:
                    break
                pw, ph = page.rect.width, page.rect.height
                tensor = egret.preprocess_pixmap(egret.render_page_input(page))

                with torch.no_grad():
                    ref = model(pixel_values=torch.from_numpy(tensor))
                t0 = time.perf_counter()
                logits, boxes = session.run(None, {"pixel_values": tensor})
                t_onnx += time.perf_counter() - t0
                dl = float(np.abs(ref.logits.numpy() - logits).max())
                db = float(np.abs(ref.pred_boxes.numpy() - boxes).max())
                worst_logit, worst_box = max(worst_logit, dl), max(worst_box, db)

                ref_det = processor.post_process_object_detection(
                    ref, target_sizes=[(ph, pw)], threshold=egret.MODEL_SCORE_THRESHOLD
                )[0]
                ref_list = [
                    egret.Detection(int(lbl), float(s), tuple(float(v) for v in bb))
                    for s, lbl, bb in zip(ref_det["scores"], ref_det["labels"], ref_det["boxes"], strict=True)
                ]
                ours = egret.postprocess(logits, boxes, pw, ph, egret.MODEL_SCORE_THRESHOLD)
                post_same = _same_detections(ours, ref_list, 0.999)
                post_ok += post_same

                # Reference input path: 2x render, HF processor resize to 640x640.
                pix2 = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                img = Image.frombytes("RGB", (pix2.width, pix2.height), pix2.samples)
                hf_in = processor(images=img, return_tensors="pt")["pixel_values"]
                with torch.no_grad():
                    hf_out = model(pixel_values=hf_in)
                hf_det = processor.post_process_object_detection(
                    hf_out, target_sizes=[(ph, pw)], threshold=egret.MODEL_SCORE_THRESHOLD
                )[0]
                hf_list = [
                    egret.Detection(int(lbl), float(s), tuple(float(v) for v in bb))
                    for s, lbl, bb in zip(hf_det["scores"], hf_det["labels"], hf_det["boxes"], strict=True)
                ]
                same_input = _same_detections(ours, hf_list, 0.9)
                input_same += same_input
                pics = sum(d.label == egret.PICTURE_LABEL for d in ours)
                hf_pics = sum(d.label == egret.PICTURE_LABEL for d in hf_list)
                print(
                    f"{pdf.name} p{page.number + 1}: logits {dl:.1e} boxes {db:.1e} "
                    f"post {'OK' if post_same else 'MISMATCH'} | dets {len(ours)} vs HF-input {len(hf_list)} "
                    f"(pictures {pics} vs {hf_pics}) {'same' if same_input else 'differs'}"
                )
                pages += 1
    print(
        f"Pages {pages} | worst logits diff {worst_logit:.2e} | worst box diff {worst_box:.2e} | "
        f"post-process identical {post_ok}/{pages} | same detections as HF input path {input_same}/{pages} | "
        f"ONNX mean {1000 * t_onnx / max(1, pages):.0f} ms/page"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--opset", type=int, default=17)
    ap.add_argument("--skip-export", action="store_true")
    ap.add_argument("--check", type=Path, default=None, help="Folder of PDFs to compare ONNX vs PyTorch on")
    ap.add_argument("--max-pages", type=int, default=12)
    args = ap.parse_args()
    if not args.skip_export:
        export(args.out, args.opset)
    if args.check is not None:
        check(args.out, args.check, args.max_pages)


if __name__ == "__main__":
    main()
