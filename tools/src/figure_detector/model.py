"""Shared lazy PyMuPDF handle, detector thresholds (`DetectorConfig`), caption regexes and data models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from image_ops import ensure_pymupdf


class _LazyPyMuPDF:
    """Stand-in for the `pymupdf` module shared by every detector submodule.

    Importing PyMuPDF loads the MuPDF DLLs, so it is deferred until the first attribute access
    (e.g. `pymupdf.Rect`). Each attribute is then cached on the instance, so later lookups cost
    the same as a plain module attribute.
    """

    def __getattr__(self, name: str):
        value = getattr(ensure_pymupdf(), name)
        setattr(self, name, value)
        return value


pymupdf = _LazyPyMuPDF()


def _ensure_pymupdf():
    """Return the real PyMuPDF module (importing it on first use) via the shared loader in `image_ops`."""
    return ensure_pymupdf()


@dataclass(frozen=True)
class DetectorConfig:
    """Centralized geometric and heuristic thresholds (units: PDF points or page fractions)."""

    # Phase 1: Text & caption segmentation
    col_split_gap_x: float = 12.0
    caption_cont_max_gap_y: float = 5.5
    # Phase 2 & 3: Page background, bleed, and ornament thresholds
    bg_area_ratio: float = 0.78
    bg_width_ratio: float = 0.90
    bg_height_ratio: float = 0.85
    vert_bleed_h_ratio: float = 0.92
    vert_bleed_w_ratio: float = 0.18
    horiz_bleed_w_ratio: float = 0.92
    horiz_bleed_h_ratio: float = 0.16
    hero_banner_h_ratio: float = 0.22
    hero_banner_min_words: int = 4
    # Phase 2: Raster dimensions
    min_raster_dim: float = 36.0
    min_raster_area: float = 1600.0
    min_strip_short_dim: float = 16.0
    min_strip_long_dim: float = 100.0
    min_strip_area: float = 1800.0
    # Phase 2: White-margin trimming of embedded images
    raster_trim_max_images: int = 40           # skip trimming on pages tiled with many images
    raster_trim_max_pixels: int = 60_000_000   # skip decoding absurdly large images
    raster_trim_min_gain: float = 0.03         # apply only when the box shrinks by >= 3% of its area
    # Phase 6: Line-level label attachment (max gap per side, pt; max growth per side from the original box)
    label_gap_left: float = 28.0
    label_gap_right: float = 20.0
    label_gap_top: float = 18.0
    label_gap_bottom: float = 26.0
    label_max_growth: float = 60.0
    # Phase 3: Vector clustering & text density
    cluster_tol_x: float = 5.0
    cluster_tol_y: float = 5.0
    min_vector_dim: float = 42.0
    max_vector_words: int = 200
    max_uncaptioned_vector_words: int = 80
    max_page_drawings: int = 200000
    dense_drawing_downsample_threshold: int = 2500
    dense_drawing_grid_pt: float = 6.0
    max_clustered_drawings: int = 12000
    # Phase 4: Caption linking & sibling propagation
    caption_below_max_gap: float = 64.0
    caption_below_bridge_gap: float = 96.0
    caption_above_max_gap: float = 68.0
    caption_side_max_gap_x: float = 35.0
    caption_side_align_y: float = 35.0
    sibling_col_max_gap: float = 68.0
    sibling_row_max_gap: float = 42.0
    # Phase 5: Candidate merging
    touch_pad: float = 2.0
    same_caption_merge_gap: float = 68.0
    same_caption_row_merge_gap: float = 74.0
    touching_merge_gap: float = 4.0


DEFAULT_CONFIG = DetectorConfig()
_LEAD_TRIM_RE = re.compile(r"^[\s•·▪▫▶►▸●○■□.\-–—*:]+")
_OPT_SUPP_PREFIX = r"(?:(?i:supplementary|extended\s+data|appendix)\s+)?"
_CAPTION_ID_BODY = (
    r"(?:(?:\s+|(?<=\.)\s*)(?:\d+(?:[.\-]\d+)*(?:[a-zA-Z])?|[IVXLCDM]+|[SA-Z]\.?\d+(?:[.\-]\d+)*(?:[a-zA-Z])?)"
    r"|\d+(?:[.\-]\d+)*(?:[a-zA-Z])?)"
)
_CAPTION_BOUNDARY = r"(?=$|[\s.:;\-–—|)\],])"
_FIG_CAPTION_RE = re.compile(
    rf"^{_OPT_SUPP_PREFIX}"
    r"(?i:figures?\.?|figs?\.?|hình(?:\s+(?:ảnh|minh\s+họa))?|sơ\s*đồ|biểu\s*đồ|scheme|chart|plate|diagram)"
    rf"{_CAPTION_ID_BODY}{_CAPTION_BOUNDARY}"
)
_TAB_CAPTION_RE = re.compile(
    rf"^{_OPT_SUPP_PREFIX}"
    r"(?i:tables?\.?|tabs?\.?|bảng)"
    rf"{_CAPTION_ID_BODY}{_CAPTION_BOUNDARY}"
)
_PROSE_AFTER_NUM_RE = re.compile(
    r"^\s+(?:shows|illustrates|presents|depicts|demonstrates|summarizes|compares|contrasts|displays|"
    r"indicates|lists|provides|gives|reports|reveals|confirms|suggests|highlights|describes|details|"
    r"evaluates|examines|explains|explores|contains|includes|measures|outlines|plots|records|reflects|"
    r"tracks|traces|is|was|are|were|has|have|can|may|will|"
    r"that|where|when|which|while|whereas|because|since|if|unless|although|though|after|before|until|"
    r"during|between|among|within|without|under|over|above|below|through|across|along|around|near|"
    r"against|despite|could|would|should|must|might|had|does|did|do|we|it|they|this|these|those|our|"
    r"their|its|here|there|also|only|still|already|clearly|further|again|"
    r"cho\s+thấy|minh\s+họa|mô\s+tả|trình\s+bày|tóm\s+tắt|so\s+sánh|chỉ\s+ra|thể\s+hiện)\b",
)
_PLURAL_CAPTION_NOUN_RE = re.compile(
    rf"^{_OPT_SUPP_PREFIX}(?i:figures\.?|figs\.?|tables\.?|tabs\.?)\b"
)
_PLURAL_PROSE_AFTER_NUM_RE = re.compile(
    r"^\s+(?:show|illustrate|present|depict|demonstrate|summarize|compare|contrast|display|indicate|"
    r"list|provide|give|report|reveal|confirm|suggest|highlight|describe|detail|evaluate|examine|"
    r"explain|explore|contain|include|measure|outline|plot|record|reflect|track|trace)\b",
)
_COMMA_PROSE_AFTER_NUM_RE = re.compile(r"^\s*,\s+[a-z]")
_INLINE_REF_AFTER_NUM_RE = re.compile(
    r"^(?:\s*[\)\]]|\s+(?:and|or)\s+(?i:fig(?:ure)?s?\.?|tables?\.?|tabs?\.?)\b|"
    r"\s+(?:for|as|to|in|on|at|with|by|from)\s+(?:a|an|the|this|more|further|details?|comparison|illustration|explanation)\b)"
)
_SUBPANEL_LABEL_RE = re.compile(r"^(?:\([a-zA-Z0-9]{1,2}\)|[a-zA-Z]\)\s)")
_NUMERIC_TOKEN_RE = re.compile(r"^[($€£¥+\-−±≈~<>≤≥]?\d[\d,./:%×x^eE+\-–—]*[)%°]?$|^(?:n/a|na|-|—|–)$", re.IGNORECASE)
_TICK_TOKEN_RE = re.compile(
    r"^[($€£¥+\-−±]?\d[\d,./:%^eE+\-]*[)%°]?$|^\([a-zA-Z0-9]{1,2}\)$|^[xyztrfkpqvnmXYZT]$"
)
_SECTION_HEADING_RE = re.compile(
    r"^(?:(?:\d+(?:\.\d+)*\.?|[IVXLCDM]+\.)\s+[A-Z][a-zA-Z]{2,}|(?:Abstract|Introduction|Conclusion|References|Appendix|Methods|Results|Discussion)\b)"
)


@dataclass
class TextBlock:
    rect: pymupdf.Rect
    text: str
    kind: str  # "fig_caption", "tab_caption", "text"
    word_count: int = 0

    def __post_init__(self) -> None:
        if self.word_count == 0 and self.text:
            self.word_count = len(self.text.split())


@dataclass
class CandidateBox:
    rect: pymupdf.Rect
    caption_idx: int | None = None
    caption_side: str = ""  # "below", "above", "side", ""
    caption_score: float = float("inf")
    source: str = "vector"  # "raster", "vector", "hybrid"
    drawings: int = 0
    origin_kind: str = "vector"  # "raster" | "vector"
    # Manifest metadata. Egret fills these from Docling's layout and reading order (`docling_layout.py`);
    # the legacy heuristic detector gets them from `extract.fill_heuristic_metadata`.
    caption_text: str | None = None
    placement: str = "figure"  # "figure" | "table_cell"
    context: str | None = None


@dataclass(frozen=True)
class FilterDecision:
    keep: bool
    reason: str
    soft_reject: bool = False


@dataclass
class PageTableInfo:
    rect: pymupdf.Rect
    row_count: int
    col_count: int


@dataclass
class PageContext:
    """Single-pass extracted structure of one PDF page shared across all pipeline phases."""

    page: pymupdf.Page
    page_rect: pymupdf.Rect
    pw: float
    ph: float
    text_blocks: list[TextBlock]
    fig_captions: list[TextBlock]
    tab_captions: list[TextBlock]
    words: list[tuple]
    word_rects: list[pymupdf.Rect]
    drawings: list[dict]
    separator_rules: list[pymupdf.Rect]
    trace: list[str] = field(default_factory=list)
    _page_tables: list[PageTableInfo] | None = None

    def get_page_tables(self) -> list[PageTableInfo]:
        """Lazily run whole-page `find_tables()` at most once per page."""
        if self._page_tables is None:
            self._page_tables = [
                PageTableInfo(pymupdf.Rect(t.bbox), t.row_count, t.col_count)
                for t in self.page.find_tables().tables
            ]
        return self._page_tables

    def log(self, msg: str) -> None:
        self.trace.append(msg)
