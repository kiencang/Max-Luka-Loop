"""Phases 2–5 for the product: find figures with the Egret Medium layout model (ONNX) and describe them as Docling would.

docling-layout-egret-medium (Apache-2.0, D-FINE, 19.5M params) is exported to ONNX by
dev/egret/export_onnx.py. The graph takes the page image already resized to 640x640 and scaled to 0..1, and
returns raw `logits [1, 300, 17]` and `pred_boxes [1, 300, 4]` (cx, cy, w, h normalized). Pre- and
post-processing below reproduce `RTDetrImageProcessor` from transformers without torch.

What happens to the detections afterwards — picture boxes, captions, footnotes, pictures inside tables —
follows Docling's layout post-processing and rule-based reading order, ported in `docling_layout.py` (MIT,
licenses/docling-MIT.txt and licenses/docling-core-MIT.txt). PyMuPDF renders the page, supplies the text
lines Docling would read from the PDF, counts drawings/images for `source`, and crops the PNGs (Phase 6).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from path_guards import assert_local_no_unc_path, get_tools_dir, is_reparse_point

from . import docling_layout
from .docling_layout import CONFIDENCE_THRESHOLDS  # noqa: F401 - re-exported for tests
from .model import DEFAULT_CONFIG, CandidateBox, DetectorConfig, PageContext, _ensure_pymupdf, pymupdf
from .pipeline import _annotate_candidate_origins

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


# ---- Docling post-processing, reading order and relations: see docling_layout.py ----

_TEXT_LABELS = {"Text", "List-item", "Section-header"}
CONTEXT_MAX_CHARS = 220


def _picture_rects(dets: list[Detection], page_rect: pymupdf.Rect) -> list[pymupdf.Rect]:
    """Picture boxes as Docling's `LayoutPostprocessor` keeps them, top-to-bottom then left-to-right."""
    layout = docling_layout.postprocess_layout(dets, [], page_rect)
    rects = [c.rect & page_rect for c in layout.of("Picture")]
    return sorted((r for r in rects if not r.is_empty), key=lambda r: (r.y0, r.x0))


def _table_row_text(rect: pymupdf.Rect, table: docling_layout.Cluster) -> str | None:
    """Text of the table row a table-cell picture sits in (cells sharing its vertical span), left to right."""
    row = [
        c for c in table.cells
        if docling_layout.ios(c.rect, rect) < 0.5
        and min(c.rect.y1, rect.y1) - max(c.rect.y0, rect.y0) >= 0.5 * min(c.rect.height, rect.height)
    ]
    text = " | ".join(docling_layout.sanitize_text([c.text.strip()]) for c in sorted(row, key=lambda c: c.rect.x0))
    return text[:CONTEXT_MAX_CHARS] or None


def _neighbour_text(cid: int, ordered: list, layout: docling_layout.PageLayout) -> str | None:
    """Nearest text element before or after the picture in reading order (for pictures without a caption)."""
    pos = next((k for k, n in enumerate(ordered) if n.cid == cid), None)
    if pos is None:
        return None
    best = None
    for rng in (range(pos - 1, -1, -1), range(pos + 1, len(ordered))):
        for k in rng:
            n = ordered[k]
            if n.label in _TEXT_LABELS and layout.clusters[n.cid].text.strip():
                gap = docling_layout._shortest_gap(ordered[pos], n)
                if best is None or gap < best[0]:
                    best = (gap, n.cid)
                break
    return layout.clusters[best[1]].text[:CONTEXT_MAX_CHARS] if best else None


def _page_context(page: pymupdf.Page) -> PageContext:
    """Only what Egret's path needs from PyMuPDF: the page box and its drawings (for `source`)."""
    rect = page.rect
    return PageContext(
        page=page, page_rect=rect, pw=rect.width, ph=rect.height, text_blocks=[], fig_captions=[],
        tab_captions=[], words=[], word_rects=[], drawings=page.get_drawings(), separator_rules=[],
    )


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

    Everything follows Docling: picture boxes (`LayoutPostprocessor`), captions (Caption regions matched in
    reading order), and `placement` ("table_cell" = no caption/footnote and >= 80% inside a Table region).
    PyMuPDF supplies the text lines Docling would read from the PDF, renders, and counts images/drawings.
    """
    _ensure_pymupdf()
    ctx = _page_context(page)
    dets = detect_layout(page, session=session)
    layout = docling_layout.postprocess_layout(dets, docling_layout.page_cells(page), ctx.page_rect)
    ordered = docling_layout.reading_order(layout, ctx.page_rect)
    captions = docling_layout.match_captions(ordered)
    footnotes = docling_layout.match_footnotes(ordered)
    pictures = sorted(
        ((cid, c) for cid, c in enumerate(layout.clusters) if c.label == "Picture"),
        key=lambda item: (item[1].rect.y0, item[1].rect.x0),
    )
    candidates: list[CandidateBox] = []
    for cid, pic in pictures:
        rect = pic.rect & ctx.page_rect
        if rect.is_empty:
            continue
        cap = captions.get(cid)
        caption = (layout.clusters[cap].text or None) if cap is not None else None
        table = None if cap is not None or cid in footnotes else docling_layout.inside_table(pic, layout)
        if table is not None:
            cand = CandidateBox(rect, placement="table_cell", context=_table_row_text(rect, table))
        else:
            context = None if caption else _neighbour_text(cid, ordered, layout)
            cand = CandidateBox(rect, caption_text=caption, placement="figure", context=context)
        candidates.append(cand)
    ctx.log(f"egret: {len(dets)} regions, {len(candidates)} pictures, {len(captions)} caption links")
    image_rects, full_page = _page_image_rects(ctx, cfg)
    drawing_rects = [pymupdf.Rect(d["rect"]) for d in ctx.drawings if d.get("rect") is not None]
    _annotate_candidate_origins(candidates, image_rects, drawing_rects)
    is_scanned = full_page and not candidates
    return ctx, candidates, is_scanned
