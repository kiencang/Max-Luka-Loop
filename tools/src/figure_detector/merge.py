"""Phase 5 — multi-panel candidate merging under anti-swallow geometric invariants; reading order."""

from __future__ import annotations

from .caption_match import (
    _has_obstacle_between,
    _is_table_row_pair,
)
from .geometry import (
    _horiz_overlap,
    _is_page_background,
    _rect_gap,
    _vert_overlap,
)
from .model import (
    DEFAULT_CONFIG,
    CandidateBox,
    DetectorConfig,
    PageContext,
)


def _violates_merge_invariants(
    a: CandidateBox,
    b: CandidateBox,
    all_candidates: list[CandidateBox],
    ctx: PageContext,
    cfg: DetectorConfig = DEFAULT_CONFIG,
) -> bool:
    """Block merges that balloon to full-page background, swallow another captioned figure, or swallow prose."""
    union = a.rect | b.rect
    if (
        _is_page_background(union, ctx.pw, ctx.ph, cfg)
        and not _is_page_background(a.rect, ctx.pw, ctx.ph, cfg)
        and not _is_page_background(b.rect, ctx.pw, ctx.ph, cfg)
    ):
        return True

    # Never swallow an unrelated candidate that belongs to a different caption.
    for other in all_candidates:
        if other is a or other is b:
            continue
        if other.caption_idx is not None and other.caption_idx not in (a.caption_idx, b.caption_idx):
            other_area = max(1.0, other.rect.get_area())
            if (union & other.rect).get_area() >= 0.50 * other_area:
                return True

    # Never swallow >=2 newly enclosed long prose blocks that weren't already inside a or b.
    newly_swallowed_prose = 0
    for tb in ctx.text_blocks:
        if tb.kind != "text" or tb.word_count < 12:
            continue
        tb_area = max(1.0, tb.rect.get_area())
        if (union & tb.rect).get_area() >= 0.65 * tb_area:
            in_a = (a.rect & tb.rect).get_area() >= 0.50 * tb_area
            in_b = (b.rect & tb.rect).get_area() >= 0.50 * tb_area
            if not in_a and not in_b:
                newly_swallowed_prose += 1
                if newly_swallowed_prose >= 2:
                    return True

    return False


def _should_merge_candidates(
    a: CandidateBox,
    b: CandidateBox,
    all_candidates: list[CandidateBox],
    ctx: PageContext,
    cfg: DetectorConfig = DEFAULT_CONFIG,
) -> bool:
    """Decide whether two figure candidates belong to the same logical figure."""
    if a.caption_idx is not None and b.caption_idx is not None and a.caption_idx != b.caption_idx:
        return False
    same_cap = a.caption_idx is not None and a.caption_idx == b.caption_idx
    if _has_obstacle_between(a.rect, b.rect, ctx.text_blocks, ctx.separator_rules, allow_axis_labels=same_cap):
        return False
    if _is_table_row_pair(a.rect, b.rect, ctx.text_blocks):
        return False

    gap = _rect_gap(a.rect, b.rect)
    if same_cap:
        shares_row = _vert_overlap(a.rect, b.rect) >= 0.40 * min(a.rect.height, b.rect.height)
        exact_col_align = (
            abs(a.rect.x0 - b.rect.x0) <= 12.0
            and abs(a.rect.x1 - b.rect.x1) <= 12.0
            and _horiz_overlap(a.rect, b.rect) >= 0.85 * max(a.rect.width, b.rect.width)
        )
        limit = (
            cfg.same_caption_row_merge_gap
            if shares_row
            else (cfg.same_caption_merge_gap * 1.65 if exact_col_align else cfg.same_caption_merge_gap)
        )
        if gap > limit:
            return False
    elif gap > cfg.touching_merge_gap:
        return False

    if _violates_merge_invariants(a, b, all_candidates, ctx, cfg=cfg):
        return False
    return True


def _sort_reading_order(candidates: list[CandidateBox]) -> list[CandidateBox]:
    """Sort candidates top-to-bottom, ordering items within the same ~14pt band left-to-right."""
    ordered = sorted(candidates, key=lambda c: (c.rect.y0, c.rect.x0))
    rows: list[list[CandidateBox]] = []
    for c in ordered:
        if rows and abs(c.rect.y0 - rows[-1][0].rect.y0) <= 14.0:
            rows[-1].append(c)
        else:
            rows.append([c])
    result: list[CandidateBox] = []
    for row in rows:
        row.sort(key=lambda c: c.rect.x0)
        result.extend(row)
    return result


def merge_candidates(
    ctx: PageContext,
    candidates: list[CandidateBox],
    cfg: DetectorConfig = DEFAULT_CONFIG,
) -> list[CandidateBox]:
    """Phase 5: Iteratively merge multi-panel candidates respecting anti-swallow invariants."""
    changed = True
    while changed:
        changed = False
        merged: list[CandidateBox] = []
        for c in candidates:
            did_merge = False
            for m in merged:
                if _should_merge_candidates(m, c, candidates, ctx, cfg=cfg):
                    m.rect = m.rect | c.rect
                    if m.caption_idx is None:
                        m.caption_idx = c.caption_idx
                        m.caption_side = c.caption_side
                        m.caption_score = c.caption_score
                    did_merge = True
                    changed = True
                    break
            if not did_merge:
                merged.append(c)
        candidates = merged
    return _sort_reading_order(candidates)
