"""Alternative Phases 2–5: find figure boxes with the Egret Medium layout model (ONNX) instead of heuristics.

docling-layout-egret-medium (Apache-2.0, D-FINE, 19.5M params) is exported to ONNX by
dev/egret/export_onnx.py. The graph takes the page image already resized to 640x640 and scaled to 0..1, and
returns raw `logits [1, 300, 17]` and `pred_boxes [1, 300, 4]` (cx, cy, w, h normalized). Pre- and
post-processing below reproduce `RTDetrImageProcessor` from transformers without torch.

PyMuPDF still renders the page, extracts text for caption linking (Phase 1 + `link_captions`), counts
drawings/images for `source`, and crops the final PNGs (Phase 6) — only the box search is replaced.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from path_guards import assert_local_no_unc_path, get_tools_dir, is_reparse_point

from .captions import link_captions
from .model import DEFAULT_CONFIG, CandidateBox, DetectorConfig, PageContext, _ensure_pymupdf, pymupdf
from .pipeline import _annotate_candidate_origins
from .text import analyze_page

INPUT_SIZE = 640
RENDER_OVERSAMPLE = 2.0
NUM_CLASSES = 17
LABELS = (
    "Caption", "Footnote", "Formula", "List-item", "Page-footer", "Page-header", "Picture", "Section-header",
    "Table", "Text", "Title", "Document Index", "Code", "Checkbox-Selected", "Checkbox-Unselected", "Form",
    "Key-Value Region",
)
PICTURE_LABEL = LABELS.index("Picture")
TABLE_LABEL = LABELS.index("Table")
DOCUMENT_INDEX_LABEL = LABELS.index("Document Index")

# ---- Post-processing constants taken from Docling (MIT, (c) The Docling Contributors) ----
# docling/utils/layout_postprocessor.py and docling/models/inference_engines/object_detection/base.py,
# docling-slim 2.151.1. Keep these in step with upstream rather than tuning them locally.
MODEL_SCORE_THRESHOLD = 0.3  # engine pre-filter (BaseObjectDetectionEngineOptions.score_threshold)
CONFIDENCE_THRESHOLDS = {  # LayoutPostprocessor.CONFIDENCE_THRESHOLDS (kept when score >= threshold)
    "Caption": 0.5, "Footnote": 0.5, "Formula": 0.5, "List-item": 0.5, "Page-footer": 0.5, "Page-header": 0.5,
    "Picture": 0.5, "Section-header": 0.45, "Table": 0.5, "Text": 0.5, "Title": 0.45, "Code": 0.45,
    "Checkbox-Selected": 0.45, "Checkbox-Unselected": 0.45, "Form": 0.45, "Key-Value Region": 0.45,
    "Document Index": 0.45,
}
PICTURE_OVERLAP_PARAMS = {"area_threshold": 2.0, "conf_threshold": 0.3}  # OVERLAP_PARAMS["picture"]
WRAPPER_OVERLAP_PARAMS = {"area_threshold": 2.0, "conf_threshold": 0.2}  # OVERLAP_PARAMS["wrapper"]
OVERLAP_IOU = 0.8            # _remove_overlapping_clusters(overlap_threshold=0.8)
OVERLAP_CONTAINMENT = 0.8    # _remove_overlapping_clusters(containment_threshold=0.8)
COINCIDENT_IOU = 0.8         # _resolve_coincident_pairs(iou_threshold=0.8)
COINCIDENT_CONF_TOLERANCE = 0.1  # _resolve_coincident_pairs(conf_tolerance=0.1)
FULL_PAGE_PICTURE_RATIO = 0.9    # _process_special_clusters: pictures covering > 90% of the page are dropped
MODEL_FILENAME = "egret_medium.onnx"
MAX_MODEL_BYTES = 200 * 1024 * 1024

_session = None


@dataclass(frozen=True)
class Detection:
    label: int
    score: float
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in pixels of the target size

    @property
    def name(self) -> str:
        return LABELS[self.label]


def default_model_path() -> Path:
    """`<exe dir>/_internal/models/` when frozen (PyInstaller --add-data), else `tools/models/`."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base / "models" / MODEL_FILENAME
    return get_tools_dir() / "models" / MODEL_FILENAME


def _resolve_model_path(model_path: Path | None) -> Path:
    path = Path(model_path) if model_path is not None else default_model_path()
    assert_local_no_unc_path(path, "EgretModelPath")
    for p in (path.parent, path):
        if os.path.lexists(p) and is_reparse_point(p):
            raise ValueError(f"Refusing to load Egret model through symlink/junction: {p}")
    if not path.is_file():
        raise FileNotFoundError(
            f"Egret ONNX model not found: {path}. Build it with dev\\egret\\export_onnx.py (dev) "
            "or use the release package that bundles it."
        )
    size = path.stat().st_size
    if size > MAX_MODEL_BYTES:
        raise ValueError(f"Refusing oversized Egret model ({size:,} bytes): {path}")
    return path


def load_session(model_path: Path | None = None, threads: int = 0):
    """Create (once per process) a CPU onnxruntime session for the Egret model.

    `threads` sets onnxruntime's intra-op thread count (0 = onnxruntime default, one per physical core);
    dev tools running several worker processes pass 1 so the workers do not oversubscribe the CPU.
    """
    global _session
    if _session is not None and model_path is None:
        return _session
    resolved = _resolve_model_path(model_path)
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(f"Egret detector cannot start: onnxruntime is missing or broken ({exc}).") from exc

    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.log_severity_level = 3
    if threads > 0:
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
    try:
        sess = ort.InferenceSession(str(resolved), sess_options=opts, providers=["CPUExecutionProvider"])
    except Exception as exc:  # noqa: BLE001 - onnxruntime raises its own pybind exception types
        raise RuntimeError(
            f"Egret model could not be loaded ({type(exc).__name__}): {' '.join(str(exc).split())[:300]} | "
            f"Model: {resolved}. If the folder is synced to the cloud, keep it available offline; "
            "otherwise re-extract the release package."
        ) from exc
    if model_path is None:
        _session = sess
    return sess


def preprocess_pixmap(pix: pymupdf.Pixmap):
    """RGB Pixmap of exactly 640x640 -> float32 [1, 3, 640, 640] scaled to 0..1 (no mean/std, as the processor)."""
    import numpy as np

    if pix.width != INPUT_SIZE or pix.height != INPUT_SIZE or pix.n != 3 or pix.alpha:
        raise ValueError(f"Egret input must be a 640x640 RGB pixmap (got {pix.width}x{pix.height}, n={pix.n})")
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(INPUT_SIZE, INPUT_SIZE, 3)
    return (arr.transpose(2, 0, 1)[None].astype(np.float32) / np.float32(255.0)).copy()


def render_page_input(page: pymupdf.Page) -> pymupdf.Pixmap:
    """Render the page at ~2x the model size (long side 1280 px), then let MuPDF downsample to 640x640.

    Mirrors the reference path (page image -> processor resize to a non-square 640x640). Rendering
    straight at 640x640 changed Picture boxes on 4/20 sample pages; this path matched the reference on 20/20.
    """
    rect = page.rect
    zoom = RENDER_OVERSAMPLE * INPUT_SIZE / max(1e-6, rect.width, rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csRGB)
    return pymupdf.Pixmap(pix, INPUT_SIZE, INPUT_SIZE, None)


def postprocess(logits, pred_boxes, width: float, height: float, threshold: float) -> list[Detection]:
    """Reproduce RTDetrImageProcessor.post_process_object_detection (focal loss: sigmoid + top-k over queries x classes)."""
    import numpy as np

    lg = np.asarray(logits, dtype=np.float32)[0]
    bx = np.asarray(pred_boxes, dtype=np.float32)[0]
    num_queries, num_classes = lg.shape
    scores = 1.0 / (1.0 + np.exp(-lg.reshape(-1)))
    top = np.argsort(-scores, kind="stable")[:num_queries]
    out: list[Detection] = []
    for flat in top:
        s = float(scores[flat])
        if s <= threshold:
            break
        q, lbl = divmod(int(flat), num_classes)
        cx, cy, w, h = (float(v) for v in bx[q])
        out.append(
            Detection(
                lbl,
                s,
                ((cx - w / 2) * width, (cy - h / 2) * height, (cx + w / 2) * width, (cy + h / 2) * height),
            )
        )
    return out


def detect_layout(page: pymupdf.Page, session=None, threshold: float = MODEL_SCORE_THRESHOLD) -> list[Detection]:
    """Run Egret on `page`; boxes are returned in PDF page coordinates (points, page.rect origin)."""
    sess = session if session is not None else load_session()
    tensor = preprocess_pixmap(render_page_input(page))
    try:
        logits, boxes = sess.run(None, {"pixel_values": tensor})
    except Exception as exc:  # noqa: BLE001 - onnxruntime raises its own pybind exception types
        raise RuntimeError(
            f"Egret detector failed on page {page.number + 1} ({type(exc).__name__}): "
            f"{' '.join(str(exc).split())[:300]}"
        ) from exc
    rect = page.rect
    dets = postprocess(logits, boxes, rect.width, rect.height, threshold)
    return [
        Detection(d.label, d.score, (d.box[0] + rect.x0, d.box[1] + rect.y0, d.box[2] + rect.x0, d.box[3] + rect.y0))
        for d in dets
    ]


# ---- Docling picture post-processing (port of LayoutPostprocessor's special-cluster path) ----
# Detections play the role of Docling clusters; their index in `dets` (score order) is the cluster id.


def _area(r: pymupdf.Rect) -> float:
    return max(0.0, r.width) * max(0.0, r.height)


def _iou(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    inter = _area(a & b)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _inside(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    """Docling's `a.intersection_over_self(b)`: share of `a` lying inside `b`."""
    return _area(a & b) / _area(a) if _area(a) > 0 else 0.0


def _check_overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    """SpatialClusterIndex.check_overlap with the default 0.8 / 0.8 thresholds."""
    if _area(a) <= 0 or _area(b) <= 0:
        return False
    return _iou(a, b) > OVERLAP_IOU or _inside(a, b) > OVERLAP_CONTAINMENT or _inside(b, a) > OVERLAP_CONTAINMENT


def _should_prefer(cand: Detection, other: Detection, params: dict) -> bool:
    """LayoutPostprocessor._should_prefer_cluster, area/confidence rule (the label rules never apply to pictures)."""
    area_ratio = _area(pymupdf.Rect(cand.box)) / max(1e-9, _area(pymupdf.Rect(other.box)))
    conf_diff = other.score - cand.score
    return not (area_ratio <= params["area_threshold"] and conf_diff > params["conf_threshold"])


def _select_best(group: list[Detection], params: dict) -> Detection:
    """LayoutPostprocessor._select_best_cluster_from_group: prefer the larger box unless clearly less confident."""
    best = None
    for cand in group:
        if all(other is cand or _should_prefer(cand, other, params) for other in group):
            if best is None or (
                _area(pymupdf.Rect(cand.box)) > _area(pymupdf.Rect(best.box))
                and best.score - cand.score <= params["conf_threshold"]
            ):
                best = cand
    return best if best is not None else group[0]


def _remove_overlapping(dets: list[Detection], params: dict) -> list[Detection]:
    """LayoutPostprocessor._remove_overlapping_clusters: union-find groups of overlapping boxes, keep one each."""
    parent = list(range(len(dets)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    rects = [pymupdf.Rect(d.box) for d in dets]
    for i in range(len(dets)):
        for j in range(i + 1, len(dets)):
            if _check_overlap(rects[i], rects[j]):
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in range(len(dets)):
        groups.setdefault(find(i), []).append(i)
    kept = [dets[g[0]] if len(g) == 1 else _select_best([dets[i] for i in g], params) for g in groups.values()]
    return sorted(kept, key=dets.index)


def _coincident_losers(losers: list[Detection], winners: list[Detection]) -> set[int]:
    """LayoutPostprocessor._resolve_coincident_pairs: near-identical boxes, the loser label is dropped
    unless it is clearly (>= 0.1) more confident."""
    drop: set[int] = set()
    for loser in losers:
        for winner in winners:
            if _iou(pymupdf.Rect(loser.box), pymupdf.Rect(winner.box)) <= COINCIDENT_IOU:
                continue
            if loser.score - winner.score < COINCIDENT_CONF_TOLERANCE:
                drop.add(id(loser))
                break
    return drop


def _picture_rects(dets: list[Detection], page_rect: pymupdf.Rect) -> list[pymupdf.Rect]:
    """Picture boxes as Docling's `_process_special_clusters` keeps them.

    1. per-label confidence thresholds (`score >= CONFIDENCE_THRESHOLDS[label]`);
    2. pictures covering > 90% of the page are dropped (page backgrounds, whole scans);
    3. overlapping pictures (IoU > 0.8 or one > 80% inside the other) collapse to the best one of each group —
       the larger box wins unless its score is > 0.3 lower; tables and document indexes likewise among themselves;
    4. a picture on (almost) the same box as a table or document index is dropped unless its score is
       at least 0.1 higher, because tables are translated as text.
    """
    kept = [d for d in dets if d.score >= CONFIDENCE_THRESHOLDS[d.name]]
    page_area = _area(page_rect)
    pictures = [
        d for d in kept
        if d.label == PICTURE_LABEL and not (page_area > 0 and _area(pymupdf.Rect(d.box)) / page_area > FULL_PAGE_PICTURE_RATIO)
    ]
    pictures = _remove_overlapping(pictures, PICTURE_OVERLAP_PARAMS)
    tables_and_indexes = _remove_overlapping(
        [d for d in kept if d.label in (TABLE_LABEL, DOCUMENT_INDEX_LABEL)], WRAPPER_OVERLAP_PARAMS
    )
    tables = [d for d in tables_and_indexes if d.label == TABLE_LABEL]
    indexes = [d for d in tables_and_indexes if d.label == DOCUMENT_INDEX_LABEL]
    dropped_tables = _coincident_losers(tables, indexes)
    winners = [d for d in tables if id(d) not in dropped_tables] + indexes
    dropped = _coincident_losers(pictures, winners)
    rects = []
    for d in pictures:
        if id(d) in dropped:
            continue
        r = pymupdf.Rect(d.box) & page_rect
        if not r.is_empty:
            rects.append(r)
    # Docling `_sort_clusters(mode="tblr")`: top-to-bottom, then left-to-right (file numbering follows it).
    return sorted(rects, key=lambda r: (r.y0, r.x0))


def _page_image_rects(ctx: PageContext, cfg: DetectorConfig) -> tuple[list[pymupdf.Rect], bool]:
    """Embedded image boxes (for `source`) and whether one covers the page like a scan."""
    rects: list[pymupdf.Rect] = []
    full_page = False
    page_area = max(1.0, ctx.pw * ctx.ph)
    for info in ctx.page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & ctx.page_rect
        if r.is_empty:
            continue
        if r.get_area() >= cfg.bg_area_ratio * page_area:
            full_page = True
        rects.append(r)  # a scan's full-page image too: figures cut from it are raster (Group B)
    return rects, full_page


def run_page_egret(
    page: pymupdf.Page, session=None, cfg: DetectorConfig = DEFAULT_CONFIG
) -> tuple[PageContext, list[CandidateBox], bool]:
    """Same contract as `pipeline._run_page_pipeline`: `(PageContext, candidates, is_scanned)`.

    Boxes are exactly what Docling would keep (`_picture_rects`); they are not grown, trimmed or merged.
    PyMuPDF text (Phase 1) only attaches caption metadata (`link_captions`, which never moves a box) and
    the image/drawing counts give `source`.
    """
    _ensure_pymupdf()
    ctx = analyze_page(page, cfg=cfg)
    dets = detect_layout(page, session=session)
    pic_rects = _picture_rects(dets, ctx.page_rect)
    ctx.log(f"egret: {len(dets)} regions, {len(pic_rects)} pictures")
    candidates = link_captions(ctx, pic_rects, cfg=cfg)
    image_rects, full_page = _page_image_rects(ctx, cfg)
    drawing_rects = [pymupdf.Rect(d["rect"]) for d in ctx.drawings if d.get("rect") is not None]
    _annotate_candidate_origins(candidates, image_rects, drawing_rects)
    is_scanned = full_page and not candidates
    return ctx, candidates, is_scanned
