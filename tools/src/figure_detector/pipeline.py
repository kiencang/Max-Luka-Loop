"""Phases 1–5 orchestration per page, plus origin annotation and axis-label expansion."""

from __future__ import annotations

import re

from .captions import (
    _recover_orphan_caption_vectors,
    link_captions,
)
from .geometry import (
    _is_frame_for,
    _merge_touching,
    _rect_center_inside,
    _rect_gap,
)
from .merge import (
    merge_candidates,
)
from .model import (
    _SECTION_HEADING_RE,
    _SUBPANEL_LABEL_RE,
    DEFAULT_CONFIG,
    CandidateBox,
    DetectorConfig,
    PageContext,
    _ensure_pymupdf,
    pymupdf,
)
from .raster import (
    detect_raster_regions,
)
from .text import (
    _clean_text,
    _is_short_axis_label,
    analyze_page,
)
from .vector import (
    detect_vector_regions,
)


def _annotate_candidate_origins(
    candidates: list[CandidateBox],
    raster_rects: list[pymupdf.Rect],
    filtered_rects: list[pymupdf.Rect],
) -> None:
    """Populate `source` ('raster'|'vector'|'hybrid') and `drawings` count on each candidate."""
    for cand in candidates:
        bb = cand.rect
        overlapping_rasters = [rr for rr in raster_rects if bb.intersects(rr)]
        intersecting_vecs = [r for r in filtered_rects if bb.intersects(r) and _rect_center_inside(r, bb)]
        if not overlapping_rasters:
            cand.source = "vector"
            cand.drawings = len(intersecting_vecs)
            continue

        non_frame_vecs = [r for r in intersecting_vecs if not _is_frame_for(r, bb)]
        if len(non_frame_vecs) >= 2 or (len(overlapping_rasters) >= 2 and len(non_frame_vecs) >= 1):
            cand.source = "hybrid"
            cand.drawings = len(intersecting_vecs)
        else:
            cand.source = "raster"
            cand.drawings = 0


def _expand_plot_axis_labels(candidates: list[CandidateBox], ctx: PageContext) -> None:
    """Expand vector/hybrid (or captioned) plot boxes to include tightly attached axis ticks & titles.

    Prevents vector chart crops from slicing off Y-axis numbers, rotated Y-axis titles,
    X-axis labels, and subpanel markers that live just outside the vector axis frame.
    """
    all_captions = ctx.fig_captions + ctx.tab_captions
    prose_blocks = [
        tb
        for tb in ctx.text_blocks
        if tb.kind != "text" or (tb.word_count >= 6 and not _is_short_axis_label(tb, vertical_ok=True))
    ]
    axis_blocks = [
        tb
        for tb in ctx.text_blocks
        if tb.kind == "text"
        and _is_short_axis_label(tb, vertical_ok=True)
        and tb.rect.y1 >= ctx.page_rect.y0 + 36.0
        and tb.rect.y0 <= ctx.page_rect.y1 - 36.0
    ]
    if not axis_blocks:
        return

    for idx, cand in enumerate(candidates):
        if cand.source == "raster" and cand.caption_idx is None:
            continue
        orig = pymupdf.Rect(cand.rect)
        cur = pymupdf.Rect(cand.rect)
        other_rects = [c.rect for j, c in enumerate(candidates) if j != idx]

        changed = True
        while changed:
            changed = False
            for tb in axis_blocks:
                tr = tb.rect
                if cur.contains(tr):
                    continue
                # Hard expansion caps relative to the original graphic box so absorption cannot run away.
                if (
                    orig.x0 - tr.x0 > 52.0
                    or tr.x1 - orig.x1 > 40.0
                    or tr.y1 - orig.y1 > 36.0
                    or orig.y0 - tr.y0 > 24.0
                ):
                    continue

                is_rotated = tr.width <= 28.0 and tr.height >= 1.8 * tr.width
                cleaned = _clean_text(tb.text)
                is_subpanel = bool(_SUBPANEL_LABEL_RE.match(cleaned))
                attachable = False

                # Left side (Y-axis ticks, rotated Y-axis title, or subpanel marker)
                if (
                    tr.x1 <= cur.x0 + 6.0
                    and (cur.x0 - tr.x1) <= 16.0
                    and tr.y0 >= cur.y0 - 10.0
                    and tr.y1 <= cur.y1 + 10.0
                ):
                    if cand.source != "raster" or is_rotated or is_subpanel or tr.width <= 32.0:
                        attachable = True
                # Right side (only rotated secondary Y-axis title or narrow right-axis tick/unit)
                elif (
                    tr.x0 >= cur.x1 - 6.0
                    and (tr.x0 - cur.x1) <= 16.0
                    and tr.y0 >= cur.y0 - 10.0
                    and tr.y1 <= cur.y1 + 10.0
                    and (is_rotated or tr.width <= 42.0)
                ):
                    if cand.source != "raster" or is_rotated or tr.width <= 28.0:
                        attachable = True
                # Bottom side (X-axis ticks or X-axis title)
                elif (
                    tr.y0 >= cur.y1 - 6.0
                    and (tr.y0 - cur.y1) <= 16.0
                    and tr.x0 >= cur.x0 - 16.0
                    and tr.x1 <= cur.x1 + 16.0
                ):
                    if cand.source != "raster" or is_subpanel or tr.height <= 16.0:
                        attachable = True
                # Top side (compact panel title, top ticks, or subpanel marker)
                elif (
                    tr.y1 <= cur.y0 + 6.0
                    and (cur.y0 - tr.y1) <= 14.0
                    and tr.x0 >= cur.x0 - 16.0
                    and tr.x1 <= cur.x1 + 16.0
                    and (is_subpanel or (tb.word_count <= 4 and tr.height <= 18.0))
                ):
                    if cand.source != "raster" or is_subpanel:
                        attachable = True

                if not attachable:
                    continue

                expanded = cur | tr
                if any(_rect_gap(expanded, cap.rect) < 3.0 for cap in all_captions):
                    continue
                if any(expanded.intersects(orect) for orect in other_rects):
                    continue
                if any(
                    not orig.intersects(pb.rect) and (expanded & pb.rect).get_area() >= 0.25 * max(1.0, pb.rect.get_area())
                    for pb in prose_blocks
                ):
                    continue

                cur = expanded
                changed = True

        cand.rect = cur & ctx.page_rect


_EQUATION_NUMBER_RE = re.compile(r"^\(\d+(?:\.\d+)*[a-z]?\)$")


def _label_lines(ctx: PageContext) -> list[tuple[pymupdf.Rect, bool]]:
    """Label-like text lines outside captions, prose and page margins, as (rect, set larger than body text)."""
    lines: dict[tuple[int, int], pymupdf.Rect] = {}
    words: dict[tuple[int, int], list[str]] = {}
    for w in ctx.words:
        key = (w[5], w[6])
        r = pymupdf.Rect(w[:4])
        lines[key] = lines[key] | r if key in lines else r
        words.setdefault(key, []).append(w[4])
    top_band = ctx.page_rect.y0 + 0.10 * ctx.ph  # running headers sit in the top ~10%
    bottom_band = ctx.page_rect.y1 - 0.06 * ctx.ph
    # Body font size proxy: median height of horizontal words. Headings and titles are set larger than body text,
    # while axis labels, ticks and legends are the same size or smaller.
    heights = sorted(wr.height for wr in ctx.word_rects if wr.width >= wr.height)
    body = heights[len(heights) // 2] if heights else 0.0

    def looks_like_label(r: pymupdf.Rect, ws: list[str]) -> bool:
        if len(ws) > 8 or r.is_empty or r.width > 0.55 * ctx.pw:
            return False
        if len(ws) >= 2 and ws[-1].endswith((".", ";", ":", ",")):
            return False  # the tail of a sentence
        if ws[-1].endswith("-") and len(ws[-1]) > 1:
            return False  # a hyphenated line break inside running text
        return not _EQUATION_NUMBER_RE.match(ws[-1])  # a display equation: "... (12)"

    owners: dict[tuple[int, int], int] = {}
    block_ok: dict[int, bool] = {}
    for key, r in lines.items():
        centre = pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        owner = next((i for i, tb in enumerate(ctx.text_blocks) if (tb.rect + (-0.5, -0.5, 0.5, 0.5)).contains(centre)), -1)
        owners[key] = owner
        # A label stands on its own: every line of its text block must look like a label too. This keeps out
        # single short lines of paragraphs, equations and tables whose other lines give them away.
        block_ok[owner] = block_ok.get(owner, True) and looks_like_label(r, words[key])

    # Lines continuing a caption or prose line on the same baseline (split off by sub/superscripts or inline math)
    anchors = [tb.rect for i, tb in enumerate(ctx.text_blocks) if tb.kind != "text" or not block_ok.get(i, True)]
    out = []
    for key, r in lines.items():
        owner = owners[key]
        if owner < 0 or not block_ok[owner] or r.y1 <= top_band or r.y0 >= bottom_band:
            continue
        tb = ctx.text_blocks[owner]
        if tb.kind != "text" or _SECTION_HEADING_RE.match(_clean_text(tb.text)):
            continue  # captions and section headings
        if any(
            min(a.y1, r.y1) - max(a.y0, r.y0) >= 0.5 * r.height and max(a.x0 - r.x1, r.x0 - a.x1) <= 40.0
            for a in anchors
        ):
            continue
        thickness = r.width if r.height > 1.5 * r.width else r.height  # vertical lines: rotated axis titles
        out.append((r, bool(body) and thickness > 1.15 * body))
    return out


def _attach_adjacent_label_lines(candidates: list[CandidateBox], ctx: PageContext, cfg: DetectorConfig) -> None:
    """Grow figure boxes line by line to take in adjacent axis titles, tick values and legends.

    Complements `_expand_plot_axis_labels`, which works on whole text blocks: a block can join the tick values of
    two neighbouring panels (too wide to attach) or straddle the box edge (matching no side). Working on lines,
    with side-specific gaps, recovers those labels. Never crosses captions, prose, another figure or page margins.
    """
    lines = _label_lines(ctx)
    if not lines:
        return
    captions = [tb.rect for tb in ctx.fig_captions + ctx.tab_captions]
    prose = [
        tb.rect
        for tb in ctx.text_blocks
        if tb.kind == "text" and tb.word_count >= 12 and not _is_short_axis_label(tb, vertical_ok=True)
    ]
    gaps = (cfg.label_gap_left, cfg.label_gap_right, cfg.label_gap_top, cfg.label_gap_bottom)
    table_cache: list[list[pymupdf.Rect]] = []

    def tables() -> list[pymupdf.Rect]:
        if not table_cache:
            table_cache.append([t.rect for t in ctx.get_page_tables()])
        return table_cache[0]

    for idx, cand in enumerate(candidates):
        if cand.source == "raster" and cand.caption_idx is None:
            continue
        orig = pymupdf.Rect(cand.rect)
        cur = pymupdf.Rect(cand.rect)
        others = [c.rect for j, c in enumerate(candidates) if j != idx]
        for _ in range(8):
            changed = False
            for lr, large in lines:
                if cur.contains(lr):
                    continue
                ho = max(0.0, min(cur.x1, lr.x1) - max(cur.x0, lr.x0))
                vo = max(0.0, min(cur.y1, lr.y1) - max(cur.y0, lr.y0))
                inter = (cur & lr).get_area()
                if inter >= 0.3 * max(1e-6, lr.get_area()):
                    ok = True  # straddles the box edge
                elif lr.x1 <= cur.x0 + 3 and vo >= 0.5 * lr.height:
                    ok = cur.x0 - lr.x1 <= gaps[0]
                elif lr.x0 >= cur.x1 - 3 and vo >= 0.5 * lr.height:
                    ok = lr.x0 - cur.x1 <= gaps[1]
                elif lr.y1 <= cur.y0 + 3 and ho >= 0.5 * lr.width:
                    # above the figure, a line set larger than the body text is a heading, not a panel title
                    ok = not large and cur.y0 - lr.y1 <= gaps[2]
                elif lr.y0 >= cur.y1 - 3 and ho >= 0.5 * lr.width:
                    ok = lr.y0 - cur.y1 <= gaps[3]
                else:
                    ok = False
                if not ok:
                    continue
                expanded = cur | lr
                g = cfg.label_max_growth
                if (orig.x0 - expanded.x0 > g or expanded.x1 - orig.x1 > g
                        or orig.y0 - expanded.y0 > g or expanded.y1 - orig.y1 > g):
                    continue
                if any(expanded.intersects(c + (-2, -2, 2, 2)) for c in captions):
                    continue
                shrunk = [o + (1, 1, -1, -1) for o in others]
                if any(expanded.intersects(o) for o in shrunk if not o.is_empty):
                    continue
                if any(not orig.intersects(p) and (expanded & p).get_area() >= 0.25 * max(1.0, p.get_area()) for p in prose):
                    continue
                if any((t + (-1, -1, 1, 1)).contains(lr) for t in tables()):
                    continue  # a table row (tables are only searched once something is about to be attached)
                cur = expanded
                changed = True
            if not changed:
                break
        if cur != orig:
            ctx.log(f"labels:attach_lines {orig} -> {cur}")
        cand.rect = cur & ctx.page_rect


def _run_page_pipeline(
    page: pymupdf.Page, cfg: DetectorConfig = DEFAULT_CONFIG
) -> tuple[PageContext, list[CandidateBox], bool]:
    """Execute Phases 1–5 on `page` and return `(PageContext, candidates, is_scanned)`."""
    _ensure_pymupdf()
    # Phase 1
    ctx = analyze_page(page, cfg=cfg)
    # Phase 2
    raster_rects, has_full_page_img = detect_raster_regions(ctx, cfg=cfg)
    # Phase 3
    vector_rects, filtered_drawings, raw_cluster_count = detect_vector_regions(ctx, raster_rects, cfg=cfg)
    filtered_rects = [dr["rect"] for dr in filtered_drawings]

    # Phase 4 & 5
    base_rects = _merge_touching(
        raster_rects + vector_rects,
        pad=cfg.touch_pad,
        prevent_page_bg=(ctx.pw, ctx.ph, cfg),
    )
    candidates = merge_candidates(ctx, link_captions(ctx, base_rects, cfg=cfg), cfg=cfg)

    # Orphan-caption vector recovery (e.g., axis-less bar groups beneath an unclaimed caption)
    extra_vecs = _recover_orphan_caption_vectors(
        ctx, filtered_drawings, raster_rects, candidates, raw_cluster_count, cfg=cfg
    )
    if extra_vecs:
        base_rects = _merge_touching(
            raster_rects + vector_rects + extra_vecs,
            pad=cfg.touch_pad,
            prevent_page_bg=(ctx.pw, ctx.ph, cfg),
        )
        candidates = merge_candidates(ctx, link_captions(ctx, base_rects, cfg=cfg), cfg=cfg)

    _annotate_candidate_origins(candidates, raster_rects, filtered_rects)
    _expand_plot_axis_labels(candidates, ctx)
    if len(candidates) >= 2:
        candidates = merge_candidates(ctx, candidates, cfg=cfg)
        _annotate_candidate_origins(candidates, raster_rects, filtered_rects)
        _expand_plot_axis_labels(candidates, ctx)
    _attach_adjacent_label_lines(candidates, ctx, cfg)
    min_uncap_vec_dim = cfg.min_vector_dim * max(1.0, min(ctx.pw, ctx.ph) / 792.0)
    candidates = [
        c
        for c in candidates
        if c.caption_idx is not None
        or c.source != "vector"
        or (c.rect.width >= min_uncap_vec_dim and c.rect.height >= min_uncap_vec_dim)
    ]
    is_scanned = has_full_page_img and not candidates
    return ctx, candidates, is_scanned


def detect_page_figures_debug(
    page: pymupdf.Page, cfg: DetectorConfig = DEFAULT_CONFIG
) -> tuple[list[CandidateBox], bool, list[str]]:
    """Run full pipeline and also return human-readable per-region decision trace for diagnostics."""
    ctx, candidates, is_scanned = _run_page_pipeline(page, cfg=cfg)
    return candidates, is_scanned, ctx.trace


def collect_page_figures(page: pymupdf.Page) -> tuple[list[pymupdf.Rect], bool]:
    """Collect logical figure bounding boxes on `page` and flag scanned pages."""
    _, candidates, is_scanned = _run_page_pipeline(page)
    return [c.rect for c in candidates], is_scanned
