"""Phase 4 — caption linking: conflict arbitration, sibling propagation, orphan-caption recovery."""

from __future__ import annotations

from .caption_match import (
    _has_obstacle_between,
    _is_table_row_pair,
    _match_caption,
    _match_caption_scored,
)
from .geometry import (
    _horiz_overlap,
    _rect_center_inside,
    _rect_gap,
    _vert_overlap,
)
from .model import (
    _SUBPANEL_LABEL_RE,
    DEFAULT_CONFIG,
    CandidateBox,
    DetectorConfig,
    PageContext,
    pymupdf,
)
from .text import (
    _clean_text,
)
from .vector import (
    _evaluate_vector_cluster,
)


def _resolve_caption_conflicts(
    candidates: list[CandidateBox], ctx: PageContext, cfg: DetectorConfig = DEFAULT_CONFIG
) -> None:
    """Arbitrate when one caption is claimed by incompatible sides (vertical vs side, or above vs below)."""
    by_cap: dict[int, list[int]] = {}
    for ci, cand in enumerate(candidates):
        if cand.caption_idx is not None:
            by_cap.setdefault(cand.caption_idx, []).append(ci)

    losing_side: dict[int, set[int]] = {}
    for cap_idx, idxs in by_cap.items():
        if len(idxs) < 2:
            continue

        # Rule A: Direct vertical caption ownership (below/above) always beats weak side-caption matches.
        vert_claimants = [i for i in idxs if candidates[i].caption_side in ("below", "above")]
        side_claimants = [i for i in idxs if candidates[i].caption_side == "side"]
        if vert_claimants and side_claimants:
            for i in side_claimants:
                losing_side.setdefault(i, set()).add(cap_idx)
            idxs = vert_claimants
            if len(idxs) < 2:
                continue

        # Rule B: Prevent a caption sandwiched between two stacked figures from claiming both above and below.
        cap_cy = 0.5 * (ctx.fig_captions[cap_idx].rect.y0 + ctx.fig_captions[cap_idx].rect.y1)
        above = [i for i in idxs if 0.5 * (candidates[i].rect.y0 + candidates[i].rect.y1) < cap_cy]
        below = [i for i in idxs if 0.5 * (candidates[i].rect.y0 + candidates[i].rect.y1) >= cap_cy]
        if not (above and below):
            continue
        best_above_i = min(above, key=lambda i: candidates[i].caption_score)
        best_below_i = min(below, key=lambda i: candidates[i].caption_score)
        best_above = candidates[best_above_i].caption_score
        best_below = candidates[best_below_i].caption_score
        losers = below if best_above <= best_below else above

        if best_above <= best_below:
            alt_above, _, _ = _match_caption_scored(
                candidates[best_above_i].rect,
                ctx.fig_captions,
                ctx.text_blocks,
                excluded=set(by_cap.keys()),
                cfg=cfg,
            )
            if alt_above is not None and (best_below - 18.0) <= (best_above + 6.0):
                losers = above

        for i in losers:
            losing_side.setdefault(i, set()).add(cap_idx)

    for ci, excluded in losing_side.items():
        new_cap, new_side, new_score = _match_caption_scored(
            candidates[ci].rect, ctx.fig_captions, ctx.text_blocks, excluded=excluded, cfg=cfg
        )
        candidates[ci].caption_idx = new_cap
        candidates[ci].caption_side = new_side
        candidates[ci].caption_score = new_score


def _same_side_of_caption(a: pymupdf.Rect, b: pymupdf.Rect, cap: pymupdf.Rect) -> bool:
    cap_cy = 0.5 * (cap.y0 + cap.y1)
    a_above = 0.5 * (a.y0 + a.y1) < cap_cy
    b_above = 0.5 * (b.y0 + b.y1) < cap_cy
    return a_above == b_above


def _propagate_captions(
    candidates: list[CandidateBox], ctx: PageContext, cfg: DetectorConfig = DEFAULT_CONFIG
) -> None:
    """Propagate caption ownership across tightly aligned multi-panel sibling subplots."""
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(candidates):
            if a.caption_idx is not None:
                continue
            for j, b in enumerate(candidates):
                if i == j or b.caption_idx is None or b.caption_side == "side":
                    continue
                cap = ctx.fig_captions[b.caption_idx].rect
                if not _same_side_of_caption(a.rect, b.rect, cap):
                    continue

                gap = _rect_gap(a.rect, b.rect)
                shares_col = _horiz_overlap(a.rect, b.rect) >= 0.35 * min(a.rect.width, b.rect.width)
                shares_row = _vert_overlap(a.rect, b.rect) >= 0.45 * min(a.rect.height, b.rect.height)
                exact_col_align = (
                    abs(a.rect.x0 - b.rect.x0) <= 12.0
                    and abs(a.rect.x1 - b.rect.x1) <= 12.0
                    and _horiz_overlap(a.rect, b.rect) >= 0.85 * max(a.rect.width, b.rect.width)
                )

                if shares_col:
                    col_limit = cfg.sibling_col_max_gap * 1.65 if exact_col_align else cfg.sibling_col_max_gap
                    if gap > col_limit:
                        continue
                elif shares_row:
                    if gap > cfg.sibling_row_max_gap:
                        continue
                    # Do not propagate horizontally into an unrelated tall sidebar.
                    if max(a.rect.height, b.rect.height) > 2.2 * max(1.0, min(a.rect.height, b.rect.height)):
                        continue
                else:
                    continue

                # Avoid crossing from a narrow single-column caption into an unrelated other column.
                if cap.width < 0.45 * ctx.pw and _horiz_overlap(a.rect, cap) == 0.0 and not shares_col and gap > 16.0:
                    continue
                if _has_obstacle_between(a.rect, b.rect, ctx.text_blocks, ctx.separator_rules, allow_axis_labels=True):
                    continue
                if _is_table_row_pair(a.rect, b.rect, ctx.text_blocks):
                    continue

                a.caption_idx = b.caption_idx
                a.caption_side = b.caption_side
                a.caption_score = b.caption_score + gap
                changed = True
                break


def _fallback_search_band(
    cr: pymupdf.Rect,
    ctx: PageContext,
    direction: int,
    existing_rects: list[pymupdf.Rect],
) -> pymupdf.Rect:
    """Compute the obstacle-free rectangular search band below (+1) or above (-1) an orphaned caption."""
    pad_x = 120.0 if cr.width < 0.50 * ctx.pw else 50.0
    bx0 = max(ctx.page_rect.x0, cr.x0 - pad_x)
    bx1 = min(ctx.page_rect.x1, cr.x1 + pad_x)
    max_reach = min(0.55 * ctx.ph, 380.0)

    if direction > 0:
        band_y0 = cr.y1 - 4.0
        band_y1 = min(ctx.page_rect.y1 - 24.0, cr.y1 + max_reach)
        band_span = pymupdf.Rect(bx0, band_y0, bx1, band_y1)
        for tb in ctx.text_blocks:
            if tb.rect != cr and _horiz_overlap(tb.rect, band_span) >= 25.0 and tb.rect.y0 >= cr.y1 + 2.0:
                if tb.kind in ("fig_caption", "tab_caption") or (tb.kind == "text" and tb.word_count >= 10):
                    band_y1 = min(band_y1, tb.rect.y0 + 2.0)
        for rr in ctx.separator_rules:
            if rr.height <= 4.0 and rr.width >= 0.60 * ctx.pw and rr.y0 >= cr.y1 + 6.0:
                band_y1 = min(band_y1, rr.y0 + 2.0)
        for er in existing_rects:
            if _horiz_overlap(er, cr) >= 20.0 and er.y0 >= cr.y1 - 4.0:
                band_y1 = min(band_y1, er.y0 - 2.0)
    else:
        band_y1 = cr.y0 + 4.0
        band_y0 = max(ctx.page_rect.y0 + 24.0, cr.y0 - max_reach)
        band_span = pymupdf.Rect(bx0, band_y0, bx1, band_y1)
        for tb in ctx.text_blocks:
            if tb.rect != cr and _horiz_overlap(tb.rect, band_span) >= 25.0 and tb.rect.y1 <= cr.y0 - 2.0:
                if tb.kind in ("fig_caption", "tab_caption") or (tb.kind == "text" and tb.word_count >= 10):
                    band_y0 = max(band_y0, tb.rect.y1 - 2.0)
        for rr in ctx.separator_rules:
            if rr.height <= 4.0 and rr.width >= 0.60 * ctx.pw and rr.y1 <= cr.y0 - 6.0:
                band_y0 = max(band_y0, rr.y1 - 2.0)
        for er in existing_rects:
            if _horiz_overlap(er, cr) >= 20.0 and er.y1 <= cr.y0 + 4.0:
                band_y0 = max(band_y0, er.y1 + 2.0)

    return pymupdf.Rect(bx0, band_y0, bx1, band_y1)


def _recover_orphan_caption_vectors(
    ctx: PageContext,
    filtered_drawings: list[dict],
    raster_rects: list[pymupdf.Rect],
    candidates: list[CandidateBox],
    raw_cluster_count: int,
    cfg: DetectorConfig = DEFAULT_CONFIG,
) -> list[pymupdf.Rect]:
    """Recover disconnected vector charts (e.g., axis-less bar groups or sparse schematics) near orphaned captions."""
    if not filtered_drawings or not ctx.fig_captions:
        return []
    assigned = {c.caption_idx for c in candidates if c.caption_idx is not None}
    existing_rects = [c.rect for c in candidates if c.caption_idx is not None]
    extra_vecs: list[pymupdf.Rect] = []

    for cap_idx, cap in enumerate(ctx.fig_captions):
        if cap_idx in assigned:
            continue
        for direction in (1, -1):
            band = _fallback_search_band(cap.rect, ctx, direction, existing_rects)
            if band.height < cfg.min_vector_dim or band.width < cfg.min_vector_dim:
                continue
            band_drawings = [
                dr
                for dr in filtered_drawings
                if _rect_center_inside(dr["rect"], band)
                and not any(er.contains(dr["rect"]) for er in existing_rects)
            ]
            if len(band_drawings) < 4:
                continue

            found_here = False
            tol_passes = ((48, 24), (112, 68)) if direction < 0 else ((48, 24),)
            for x_tol, y_tol in tol_passes:
                for c in ctx.page.cluster_drawings(drawings=band_drawings, x_tolerance=x_tol, y_tolerance=y_tol):
                    if any(c.intersects(er) for er in existing_rects):
                        continue
                    if sum(1 for dr in filtered_drawings if c.contains(dr["rect"])) < 4:
                        continue
                    if _match_caption(c, ctx.fig_captions, ctx.text_blocks, cfg) != cap_idx:
                        continue
                    dec = _evaluate_vector_cluster(ctx, c, filtered_drawings, raster_rects, raw_cluster_count, cfg=cfg)
                    if dec.keep:
                        extra_vecs.append(c)
                        found_here = True
                if found_here:
                    break
            if found_here:
                break

    return extra_vecs


def _is_unlabeled_two_col_plot_grid(base_rects: list[pymupdf.Rect], ctx: PageContext) -> bool:
    """Return True for a multi-row 2-column grid of large standalone plots lacking `(a)/(b)` subpanel labels."""
    large_plots = [r for r in base_rects if r.width >= 155.0 and r.height >= 75.0]
    if len(large_plots) < 4:
        return False
    mid_x = 0.50 * ctx.pw
    left_col = [r for r in large_plots if r.x1 <= mid_x]
    right_col = [r for r in large_plots if r.x0 >= mid_x]
    if len(left_col) < 2 or len(right_col) < 2:
        return False
    col_gap = min(r.x0 for r in right_col) - max(r.x1 for r in left_col)
    if col_gap < 45.0:
        return False
    grid_box = pymupdf.Rect(large_plots[0])
    for r in large_plots[1:]:
        grid_box = grid_box | r
    grid_box = pymupdf.Rect(grid_box.x0 - 30.0, grid_box.y0 - 24.0, grid_box.x1 + 30.0, grid_box.y1 + 24.0)
    has_subpanel_labels = any(
        tb.kind == "text"
        and grid_box.intersects(tb.rect)
        and _SUBPANEL_LABEL_RE.match(_clean_text(tb.text))
        for tb in ctx.text_blocks
    )
    return not has_subpanel_labels


def link_captions(
    ctx: PageContext,
    base_rects: list[pymupdf.Rect],
    cfg: DetectorConfig = DEFAULT_CONFIG,
) -> list[CandidateBox]:
    """Phase 4: Assign, arbitrate, and propagate figure captions across candidate regions."""
    if _is_unlabeled_two_col_plot_grid(base_rects, ctx):
        return [CandidateBox(r, None, "", float("inf")) for r in base_rects]
    candidates: list[CandidateBox] = []
    for r in base_rects:
        cap_idx, cap_side, dist = _match_caption_scored(r, ctx.fig_captions, ctx.text_blocks, cfg=cfg)
        candidates.append(CandidateBox(r, cap_idx, cap_side, dist))

    _resolve_caption_conflicts(candidates, ctx, cfg=cfg)
    _propagate_captions(candidates, ctx, cfg=cfg)
    return candidates
