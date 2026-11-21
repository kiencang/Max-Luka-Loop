"""Phase 3 — drawing filtering, vector clustering and feature-based cluster classification."""

from __future__ import annotations

import sys
from functools import cached_property

from .caption_match import (
    _match_caption,
    _match_caption_scored,
)
from .geometry import (
    _count_non_grid_detail,
    _count_words_inside,
    _horiz_overlap,
    _is_edge_ornament,
    _is_frame_for,
    _is_full_bleed_edge_strip,
    _is_light_gray_watermark_glyph,
    _is_page_background,
    _is_simple_box_drawing,
    _is_tiny_bullet_dot,
    _rect_center_inside,
    _vert_overlap,
)
from .model import (
    _NUMERIC_TOKEN_RE,
    _TICK_TOKEN_RE,
    DEFAULT_CONFIG,
    DetectorConfig,
    FilterDecision,
    PageContext,
    PageTableInfo,
    pymupdf,
)
from .text import (
    _is_short_axis_label,
)


def _filter_drawings(
    ctx: PageContext, raster_rects: list[pymupdf.Rect], cfg: DetectorConfig = DEFAULT_CONFIG
) -> list[dict]:
    """Remove page frames, divider rules, highlights, watermarks, and tall sidebar containers."""
    top_y, bot_y = ctx.page_rect.y0, ctx.page_rect.y1
    wm_indices = {i for i, dr in enumerate(ctx.drawings) if _is_light_gray_watermark_glyph(dr)}
    drop_wm = len(wm_indices) >= 4 and any(
        ctx.drawings[i]["rect"].intersects(wr) for i in wm_indices for wr in ctx.word_rects
    )

    filtered: list[dict] = []
    for idx, dr in enumerate(ctx.drawings):
        if drop_wm and idx in wm_indices:
            continue
        r = dr["rect"]
        # Keep axis-aligned straight lines (width == 0 or height == 0) for flowchart connectors & plot axes.
        if r.is_infinite or r.x1 < r.x0 or r.y1 < r.y0 or (r.width <= 0.0 and r.height <= 0.0):
            continue
        if (
            r.x1 < ctx.page_rect.x0
            or r.x0 > ctx.page_rect.x1
            or r.y1 < ctx.page_rect.y0
            or r.y0 > ctx.page_rect.y1
        ):
            continue
        if _is_page_background(r, ctx.pw, ctx.ph, cfg) or _is_full_bleed_edge_strip(r, ctx.page_rect, cfg):
            continue
        if r.height <= 4.0 and r.width >= 0.62 * ctx.pw:
            continue
        if r.width <= 4.0 and r.height >= 0.45 * ctx.ph:
            continue
        if (r.y1 < (top_y + 48.0) or r.y0 > (bot_y - 40.0)) and r.height < 28.0:
            continue

        if dr.get("color") is None and dr.get("fill") is not None:
            is_highlight = 4.0 <= r.height <= 24.0 and any(
                r.intersects(wr) and _vert_overlap(r, wr) >= 0.5 * min(r.height, wr.height)
                for wr in ctx.word_rects
            )
            is_tall_backdrop = (
                r.height >= 0.45 * ctx.ph
                and r.width >= 0.12 * ctx.pw
                and _count_words_inside(r, ctx.word_rects) >= 10
            )
            if is_highlight or r.width >= 0.30 * ctx.pw or is_tall_backdrop:
                continue
        elif r.height >= 0.45 * ctx.ph and r.width >= 0.12 * ctx.pw and _is_simple_box_drawing(dr):
            # Drop tall framed sidebar card backdrops (stroked + filled) enclosing dense sidebar prose/tables.
            if (
                _count_words_inside(r, ctx.word_rects) >= 25
                and _match_caption(r, ctx.fig_captions, ctx.text_blocks, cfg, allow_side=False) is None
            ):
                ctx.log(f"drawing:skip tall_sidebar_box {r}")
                continue
        if dr.get("fill") is None and r.height >= 0.40 * ctx.ph and r.width >= 0.12 * ctx.pw and raster_rects:
            inside_rasters = sorted(
                (rr for rr in raster_rects if _rect_center_inside(rr, r)),
                key=lambda x: x.y0,
            )
            if len(inside_rasters) >= 2:
                max_gap = max(
                    inside_rasters[k + 1].y0 - inside_rasters[k].y1
                    for k in range(len(inside_rasters) - 1)
                )
                if max_gap >= 40.0 and _count_words_inside(r, ctx.word_rects) >= 10:
                    continue

        filtered.append(dr)

    return filtered


def _is_dense_heatmap_not_table(tab: PageTableInfo, word_count: int) -> bool:
    """Return True when PyMuPDF misclassifies a dense multi-cell vector heatmap/grid plot as a table."""
    cells = tab.row_count * tab.col_count
    return cells >= 20 and word_count < int(0.25 * cells)


def _is_ui_text_card(
    rect: pymupdf.Rect,
    inside_drawings: list[dict],
    word_count: int,
    ctx: PageContext,
) -> bool:
    """Return True for uncaptioned UI pricing/KPI/callout cards containing only chrome + stacked text."""
    if word_count < 15 or len(inside_drawings) > 12:
        return False
    has_outer_box = False
    bullet_x0s: list[float] = []
    for dr in inside_drawings:
        r = dr["rect"]
        if _is_frame_for(r, rect) and _is_simple_box_drawing(dr):
            has_outer_box = True
            continue
        # Accent bar or divider rule
        if min(r.width, r.height) <= 4.0 and (r.width >= 0.35 * rect.width or r.height >= 0.35 * rect.height):
            continue
        # Tiny list bullet dot (validated for vertical column alignment below)
        if _is_tiny_bullet_dot(dr):
            bullet_x0s.append(r.x0)
            continue
        # Text-bearing pill badge or sub-card (never empty bar-chart bars)
        if _is_simple_box_drawing(dr) and _count_words_inside(r, ctx.word_rects) >= 1:
            continue
        return False

    if not has_outer_box:
        return False
    if len(bullet_x0s) > 8:
        return False
    if len(bullet_x0s) >= 2 and (max(bullet_x0s) - min(bullet_x0s)) > 12.0:
        return False

    # Count distinct vertical text lines inside the card
    y_centers = sorted(
        0.5 * (wr.y0 + wr.y1)
        for wr in ctx.word_rects
        if rect.contains(wr) or (rect & wr).get_area() >= 0.5 * max(1e-6, wr.get_area())
    )
    lines = 0
    last_y = -999.0
    for cy in y_centers:
        if cy - last_y >= 7.0:
            lines += 1
            last_y = cy
    return lines >= 4


def _is_financial_numeric_table(
    rect: pymupdf.Rect,
    inside_drawings: list[dict],
    txt: str,
    word_count: int,
    ctx: PageContext,
) -> bool:
    """Return True for uncaptioned shaded/ruled financial tables dominated by tabular numbers."""
    if word_count < 12 or not inside_drawings:
        return False
    # Every drawing must be either a thin rule or a wide row/column shading band (never varying-height bars).
    for dr in inside_drawings:
        r = dr["rect"]
        is_thin = min(r.width, r.height) <= 3.0
        is_wide_band = r.width >= 0.35 * rect.width and r.height <= 32.0 and dr.get("color") is None
        is_outer_frame = _is_frame_for(r, rect) and _is_simple_box_drawing(dr)
        if not (is_thin or is_wide_band or is_outer_frame):
            return False
    tokens = txt.split()
    num_tokens = sum(1 for tok in tokens if _NUMERIC_TOKEN_RE.match(tok))
    if num_tokens < max(5, int(0.45 * len(tokens))):
        return False
    y_centers = sorted(
        0.5 * (wr.y0 + wr.y1)
        for wr in ctx.word_rects
        if rect.contains(wr) or (rect & wr).get_area() >= 0.5 * max(1e-6, wr.get_area())
    )
    lines = 0
    last_y = -999.0
    for cy in y_centers:
        if cy - last_y >= 7.0:
            lines += 1
            last_y = cy
    return lines >= 3


def _is_in_caption_above_zone(rect: pymupdf.Rect, ctx: PageContext) -> bool:
    """Return True if `rect` sits in an unobstructed figure zone above a `fig_caption`."""
    for cap in ctx.fig_captions:
        cr = cap.rect
        if rect.y1 > cr.y0 + 4.0 or (cr.y0 - rect.y0) > min(0.75 * ctx.ph, 540.0):
            continue
        pad_x = 120.0 if cr.width < 0.50 * ctx.pw else 60.0
        if rect.x0 < cr.x0 - pad_x or rect.x1 > cr.x1 + pad_x:
            continue
        span = pymupdf.Rect(min(rect.x0, cr.x0), rect.y1, max(rect.x1, cr.x1), cr.y0)
        blocked = any(
            tb.rect != cr
            and _horiz_overlap(tb.rect, span) >= 25.0
            and rect.y1 - 2.0 <= tb.rect.y0
            and tb.rect.y1 <= cr.y0 - 2.0
            and (tb.kind in ("fig_caption", "tab_caption") or (tb.kind == "text" and tb.word_count >= 10))
            for tb in ctx.text_blocks
        )
        if not blocked:
            return True
    return False


class _ClusterFeatures:
    """Features of one vector cluster, shared by every rule in `_VECTOR_CLUSTER_RULES`.

    Every feature is a `cached_property`: computed at most once, and only when a rule actually asks
    for it. Expensive work (`page.get_text`, `find_tables`) therefore still runs only for clusters
    that get past the cheaper rules, exactly as in the original chain of `if` statements.
    """

    def __init__(
        self,
        ctx: PageContext,
        rect: pymupdf.Rect,
        filtered_drawings: list[dict],
        raster_rects: list[pymupdf.Rect],
        page_raw_clusters: int,
        cfg: DetectorConfig,
    ) -> None:
        self.ctx = ctx
        self.rect = rect
        self.filtered_drawings = filtered_drawings
        self.raster_rects = raster_rects
        self.page_raw_clusters = page_raw_clusters
        self.cfg = cfg

    @cached_property
    def has_fig_cap(self) -> bool:
        """A figure caption sits below/above the cluster (side captions do not count)."""
        cap_idx, cap_side, _ = _match_caption_scored(
            self.rect, self.ctx.fig_captions, self.ctx.text_blocks, cfg=self.cfg
        )
        return cap_idx is not None and cap_side != "side"

    @cached_property
    def has_tab_cap(self) -> bool:
        return _match_caption(self.rect, self.ctx.tab_captions, self.ctx.text_blocks, self.cfg) is not None

    @cached_property
    def min_dim(self) -> float:
        """Minimum width/height; uncaptioned clusters on large pages must be proportionally bigger."""
        dim_scale = 1.0 if self.has_fig_cap else max(1.0, min(self.ctx.pw, self.ctx.ph) / 792.0)
        return self.cfg.min_vector_dim * dim_scale

    @cached_property
    def has_raster(self) -> bool:
        return any(self.rect.intersects(rr) for rr in self.raster_rects)

    @cached_property
    def inside_drawings(self) -> list[dict]:
        return [dr for dr in self.filtered_drawings if self.rect.contains(dr["rect"])]

    @cached_property
    def inside_rects(self) -> list[pymupdf.Rect]:
        return [dr["rect"] for dr in self.inside_drawings]

    @cached_property
    def curve_count(self) -> int:
        """Curves/diagonals inside the cluster, capped at 12 (one pass serves all thresholds below)."""
        return _count_non_grid_detail(self.filtered_drawings, self.rect, limit=12)

    @property
    def has_curves_12(self) -> bool:
        return self.curve_count >= 12

    @property
    def has_curves_2(self) -> bool:
        return self.curve_count >= 2

    @property
    def has_curves_1(self) -> bool:
        return self.curve_count >= 1

    @cached_property
    def txt(self) -> str:
        return self.ctx.page.get_text("text", clip=self.rect).strip()

    @cached_property
    def word_count(self) -> int:
        return len(self.txt.split())

    @cached_property
    def non_tick_word_count(self) -> int:
        """Word count, ignoring axis tick values (numbers, units) inside curve-rich plots."""
        tokens = self.txt.split()
        if self.has_curves_12:
            return sum(1 for tok in tokens if not _TICK_TOKEN_RE.match(tok))
        return len(tokens)

    @cached_property
    def is_captioned_strip(self) -> bool:
        rect = self.rect
        return (
            self.has_fig_cap
            and min(rect.width, rect.height) >= 18.0
            and max(rect.width, rect.height) >= 95.0
            and rect.get_area() >= 1800.0
        )

    @cached_property
    def is_caption_zone_subdiagram(self) -> bool:
        rect = self.rect
        return (
            min(rect.width, rect.height) >= 24.0
            and max(rect.width, rect.height) >= 38.0
            and rect.get_area() >= 1100.0
            and self.has_curves_2
            and len(self.inside_rects) >= 4
            and _is_in_caption_above_zone(rect, self.ctx)
        )


# ------------------------------------------------------------------------------
# Phase 3 rules. Each returns a FilterDecision to stop evaluation, or None to defer to the next rule.
# A rule states every condition it needs on its own (including the "no raster" / "no figure caption"
# guards), so rules can be read, tested and reordered individually.
# ------------------------------------------------------------------------------


def _reject_page_background(f: _ClusterFeatures) -> FilterDecision | None:
    """Cluster covers (almost) the whole page canvas."""
    if _is_page_background(f.rect, f.ctx.pw, f.ctx.ph, f.cfg):
        return FilterDecision(False, "reject:page_background")
    return None


def _reject_too_small(f: _ClusterFeatures) -> FilterDecision | None:
    """Narrower/shorter than `min_dim`, unless it is a captioned strip or a sub-diagram above a caption."""
    rect = f.rect
    if (rect.width < f.min_dim or rect.height < f.min_dim) and not (
        f.is_captioned_strip or f.is_caption_zone_subdiagram
    ):
        return FilterDecision(False, "reject:too_small")
    return None


def _reject_edge_ornament(f: _ClusterFeatures) -> FilterDecision | None:
    """Small running header/footer logo, page badge or margin bar."""
    if _is_edge_ornament(f.rect, f.ctx.page_rect, f.ctx.fig_captions):
        return FilterDecision(False, "reject:edge_ornament")
    return None


def _reject_inner_table_caption(f: _ClusterFeatures) -> FilterDecision | None:
    """Framed table card whose `Table X` title sits inside the box itself (e.g. rounded card tables)."""
    if not f.has_fig_cap and any(
        (f.rect & tc.rect).get_area() >= 0.65 * max(1.0, tc.rect.get_area())
        for tc in f.ctx.tab_captions
    ):
        return FilterDecision(False, "reject:inner_table_caption")
    return None


def _reject_excessive_words(f: _ClusterFeatures) -> FilterDecision | None:
    """Too much (non-tick) text for any figure."""
    if f.non_tick_word_count > f.cfg.max_vector_words:
        return FilterDecision(False, "reject:excessive_words")
    return None


def _reject_uncaptioned_high_words(f: _ClusterFeatures) -> FilterDecision | None:
    """Too much (non-tick) text for a figure without a caption."""
    if f.non_tick_word_count > f.cfg.max_uncaptioned_vector_words and not f.has_fig_cap:
        return FilterDecision(False, "reject:uncaptioned_high_words")
    return None


def _reject_table_caption(f: _ClusterFeatures) -> FilterDecision | None:
    """Text-bearing cluster owned by a table caption and by no figure caption."""
    if f.word_count >= 6 and f.has_tab_cap and not f.has_fig_cap:
        return FilterDecision(False, "reject:table_caption")
    return None


def _reject_pymupdf_table(f: _ClusterFeatures) -> FilterDecision | None:
    """Curve-poor text-bearing cluster that PyMuPDF recognizes as a real table (not a dense heatmap)."""
    if f.word_count < 6 or (f.has_fig_cap and not f.has_tab_cap) or f.has_curves_12:
        return None
    rect, ctx, word_count = f.rect, f.ctx, f.word_count
    # Check cached page-level tables first; fallback to clip find_tables only if cluster has grid lines.
    rect_area = max(1.0, rect.get_area())
    matched_tab = any(
        (t.rect & rect).get_area() > 0.45 * rect_area
        and t.row_count >= 2
        and t.col_count >= 2
        and not _is_dense_heatmap_not_table(t, word_count)
        for t in ctx.get_page_tables()
    )
    if not matched_tab and len(f.inside_rects) >= 4:
        clip_tabs = [
            PageTableInfo(pymupdf.Rect(t.bbox), t.row_count, t.col_count)
            for t in ctx.page.find_tables(clip=rect).tables
        ]
        matched_tab = any(
            t.rect.get_area() > 0.45 * rect_area
            and t.row_count >= 2
            and t.col_count >= 2
            and not _is_dense_heatmap_not_table(t, word_count)
            for t in clip_tabs
        )
    if matched_tab:
        return FilterDecision(False, "reject:pymupdf_table", soft_reject=True)
    return None


def _reject_prose_box(f: _ClusterFeatures) -> FilterDecision | None:
    """Callout box holding running prose, unless it is a captioned curve-rich figure."""
    if f.word_count < 20:
        return None
    prose_inside = [
        tb
        for tb in f.ctx.text_blocks
        if tb.kind == "text"
        and (tb.rect & f.rect).get_area() > 0.5 * tb.rect.get_area()
        and not _is_short_axis_label(tb, vertical_ok=True)
    ]
    long_blocks = [
        tb
        for tb in prose_inside
        if sum(1 for tok in tb.text.split() if not _TICK_TOKEN_RE.match(tok)) >= 12
    ]
    is_prose_callout = len(long_blocks) >= 2 or any(
        sum(1 for tok in tb.text.split() if not _TICK_TOKEN_RE.match(tok)) >= 40 for tb in long_blocks
    )
    if is_prose_callout and not (f.has_fig_cap and not f.has_tab_cap and f.has_curves_12):
        return FilterDecision(False, "reject:prose_box")
    return None


def _reject_trivial_shape(f: _ClusterFeatures) -> FilterDecision | None:
    """Uncaptioned, raster-free cluster of at most two shapes."""
    if not f.has_raster and not f.has_fig_cap and len(f.inside_rects) <= 2:
        return FilterDecision(False, "reject:trivial_shape")
    return None


def _reject_tall_narrow_column(f: _ClusterFeatures) -> FilterDecision | None:
    """Uncaptioned, raster-free tall narrow column (sidebar rail, timeline bar)."""
    rect, ctx = f.rect, f.ctx
    if not f.has_raster and not f.has_fig_cap and rect.height >= 0.50 * ctx.ph and rect.width <= 0.18 * ctx.pw:
        return FilterDecision(False, "reject:tall_narrow_column")
    return None


def _reject_ui_text_card(f: _ClusterFeatures) -> FilterDecision | None:
    """Uncaptioned, raster-free pricing/KPI/callout card: chrome plus stacked text."""
    if not f.has_raster and not f.has_fig_cap and _is_ui_text_card(f.rect, f.inside_drawings, f.word_count, f.ctx):
        return FilterDecision(False, "reject:ui_text_card")
    return None


def _reject_financial_numeric_table(f: _ClusterFeatures) -> FilterDecision | None:
    """Uncaptioned, raster-free, curve-free shaded/ruled table dominated by numbers."""
    if (
        not f.has_raster
        and not f.has_fig_cap
        and not f.has_curves_1
        and _is_financial_numeric_table(f.rect, f.inside_drawings, f.txt, f.word_count, f.ctx)
    ):
        return FilterDecision(False, "reject:financial_numeric_table")
    return None


def _reject_hairline_table_grid(f: _ClusterFeatures) -> FilterDecision | None:
    """Uncaptioned, raster-free cluster made only of hairline rules forming a table grid."""
    if f.has_raster or f.has_fig_cap:
        return None
    rect, inside_rects, word_count = f.rect, f.inside_rects, f.word_count
    if not (inside_rects and all(min(x.width, x.height) <= 3.0 for x in inside_rects)):
        return None
    h_rules = sum(1 for x in inside_rects if x.height <= 3.0 and x.width >= 0.4 * rect.width)
    v_rules = sum(1 for x in inside_rects if x.width <= 3.0 and x.height >= 0.4 * rect.height)
    if (
        (word_count >= 6 and h_rules >= 2 and v_rules >= 1)
        or (h_rules >= 3 and v_rules >= 2)
        or (
            h_rules >= 2
            and v_rules >= 2
            and not f.has_curves_1
            and all(dr.get("fill") is None for dr in f.inside_drawings)
        )
        or (word_count >= 10 and h_rules >= 2 and not f.has_curves_1)
    ):
        return FilterDecision(False, "reject:hairline_table_grid")
    return None


def _reject_outlined_glyph_confetti(f: _ClusterFeatures) -> FilterDecision | None:
    """Uncaptioned, raster-free swarm of tiny filled glyph outlines (text or formulas drawn as paths)."""
    if f.has_raster or f.has_fig_cap or not f.inside_drawings:
        return None
    rect, ctx, inside_drawings = f.rect, f.ctx, f.inside_drawings
    # Only strokeless filled tiny paths represent outlined text/formula glyphs; stroked diagrams survive.
    glyph_cap = 12.0 * max(1.0, min(ctx.pw, ctx.ph) / 792.0)
    tiny_filled_glyphs = sum(
        1
        for dr in inside_drawings
        if dr.get("color") is None
        and dr.get("fill") is not None
        and dr["rect"].width <= glyph_cap
        and dr["rect"].height <= glyph_cap
    )
    tiny_ratio = tiny_filled_glyphs / len(inside_drawings)
    long_parts = sum(
        1
        for x in f.inside_rects
        if max(x.width, x.height) >= 0.45 * min(rect.width, rect.height)
    )
    if long_parts < 2 and (
        (len(inside_drawings) >= 120 and tiny_ratio >= 0.72)
        or (len(inside_drawings) >= 35 and f.word_count == 0 and tiny_ratio >= 0.85)
    ):
        return FilterDecision(False, "reject:outlined_glyph_confetti")
    return None


def _reject_dense_poster_fragment(f: _ClusterFeatures) -> FilterDecision | None:
    """Uncaptioned, raster-free, text-free small fragment on a page shattered into >= 80 clusters."""
    ctx = f.ctx
    if (
        not f.has_raster
        and not f.has_fig_cap
        and f.page_raw_clusters >= 80
        and f.word_count == 0
        and len(f.inside_rects) <= 16
        and f.rect.get_area() < 0.03 * ctx.pw * ctx.ph
    ):
        return FilterDecision(False, "reject:dense_poster_fragment")
    return None


# Evaluation order matters: the first rule that returns a decision wins.
_VECTOR_CLUSTER_RULES = (
    _reject_page_background,
    _reject_too_small,
    _reject_edge_ornament,
    _reject_inner_table_caption,
    _reject_excessive_words,
    _reject_uncaptioned_high_words,
    _reject_table_caption,
    _reject_pymupdf_table,
    _reject_prose_box,
    _reject_trivial_shape,
    _reject_tall_narrow_column,
    _reject_ui_text_card,
    _reject_financial_numeric_table,
    _reject_hairline_table_grid,
    _reject_outlined_glyph_confetti,
    _reject_dense_poster_fragment,
)


def _evaluate_vector_cluster(
    ctx: PageContext,
    rect: pymupdf.Rect,
    filtered_drawings: list[dict],
    raster_rects: list[pymupdf.Rect],
    page_raw_clusters: int,
    cfg: DetectorConfig = DEFAULT_CONFIG,
) -> FilterDecision:
    """Phase 3 classifier: apply `_VECTOR_CLUSTER_RULES` in order; keep the cluster if no rule rejects it."""
    features = _ClusterFeatures(ctx, rect, filtered_drawings, raster_rects, page_raw_clusters, cfg)
    for rule in _VECTOR_CLUSTER_RULES:
        decision = rule(features)
        if decision is not None:
            return decision
    return FilterDecision(True, "keep:vector_figure")


def _downsample_dense_drawings(drawings: list[dict], grid_pt: float = 6.0) -> list[dict]:
    """Coalesce ultra-dense micro-segments onto an O(n) spatial grid before O(n^2) clustering."""
    inv = 1.0 / max(1.0, grid_pt)
    small_cap = grid_pt
    buckets: dict[tuple[int, ...], dict] = {}
    for dr in drawings:
        r = dr["rect"]
        is_stroked = 1 if dr.get("color") is not None else 0
        if max(r.width, r.height) <= small_cap:
            key: tuple[int, ...] = (
                0,
                is_stroked,
                int((r.x0 + r.x1) * 0.5 * inv),
                int((r.y0 + r.y1) * 0.5 * inv),
            )
        else:
            key = (
                1,
                is_stroked,
                int(r.x0 * inv),
                int(r.y0 * inv),
                int(r.x1 * inv),
                int(r.y1 * inv),
            )
        existing = buckets.get(key)
        if existing is None:
            buckets[key] = dict(dr)
        else:
            existing["rect"] = existing["rect"] | r
    return list(buckets.values())


def detect_vector_regions(
    ctx: PageContext,
    raster_rects: list[pymupdf.Rect],
    cfg: DetectorConfig = DEFAULT_CONFIG,
) -> tuple[list[pymupdf.Rect], list[dict], int]:
    """Phase 3: Filter page drawings, cluster vector graphics, and classify valid figure clusters."""
    if not ctx.drawings:
        return [], [], 0
    if len(ctx.drawings) > cfg.max_page_drawings:
        ctx.log(f"vector:skip excessive_drawings count={len(ctx.drawings)} limit={cfg.max_page_drawings}")
        pno = getattr(ctx.page, "number", 0) + 1
        print(
            f"WARNING: Page {pno} has {len(ctx.drawings):,} vector drawings (> {cfg.max_page_drawings:,} limit); "
            f"skipped vector clustering on this page to prevent DoS (use RenderPages fallback if needed).",
            file=sys.stderr,
        )
        return [], [], 0

    filtered = _filter_drawings(ctx, raster_rects, cfg=cfg)
    if not filtered:
        return [], [], 0
    if len(filtered) > cfg.dense_drawing_downsample_threshold:
        orig_len = len(filtered)
        filtered = _downsample_dense_drawings(filtered, grid_pt=cfg.dense_drawing_grid_pt)
        ctx.log(f"vector:downsample_dense {orig_len}->{len(filtered)}")

    if len(filtered) > cfg.max_clustered_drawings:
        ctx.log(
            f"vector:skip excessive_clustered_drawings count={len(filtered)} limit={cfg.max_clustered_drawings}"
        )
        pno = getattr(ctx.page, "number", 0) + 1
        print(
            f"WARNING: Page {pno} still has {len(filtered):,} vector drawings after downsampling "
            f"(> {cfg.max_clustered_drawings:,} limit); skipped vector clustering on this page to prevent DoS "
            f"(use RenderPages fallback if needed).",
            file=sys.stderr,
        )
        return [], [], 0

    raw_clusters = ctx.page.cluster_drawings(
        drawings=filtered, x_tolerance=cfg.cluster_tol_x, y_tolerance=cfg.cluster_tol_y
    )
    raw_count = len(raw_clusters)
    kept: list[pymupdf.Rect] = []
    for c in raw_clusters:
        dec = _evaluate_vector_cluster(ctx, c, filtered, raster_rects, raw_count, cfg=cfg)
        ctx.log(f"vector:{dec.reason} {[round(v, 1) for v in c]}")
        if dec.keep:
            kept.append(c)
    return kept, filtered, raw_count
