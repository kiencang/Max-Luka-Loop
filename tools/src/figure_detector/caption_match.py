"""Caption matching primitives shared by Phases 2–6 (scored match, obstacles, row alignment)."""

from __future__ import annotations

from .geometry import (
    _horiz_overlap,
    _vert_overlap,
)
from .model import (
    _SUBPANEL_LABEL_RE,
    _TICK_TOKEN_RE,
    DEFAULT_CONFIG,
    DetectorConfig,
    TextBlock,
    pymupdf,
)
from .text import (
    _clean_text,
    _is_short_axis_label,
)


def _match_caption_scored(
    rect: pymupdf.Rect,
    fig_captions: list[TextBlock],
    text_blocks: list[TextBlock],
    excluded: set[int] | None = None,
    cfg: DetectorConfig = DEFAULT_CONFIG,
    allow_side: bool = True,
) -> tuple[int | None, str, float]:
    """Return `(best_caption_idx, placement_side, distance_score)` for `rect`."""
    best_idx: int | None = None
    best_side = ""
    best_dist = float("inf")

    for idx, cap in enumerate(fig_captions):
        if excluded and idx in excluded:
            continue
        cr = cap.rect
        h_ov = _horiz_overlap(rect, cr)
        min_ov = min(28.0, 0.30 * min(rect.width, cr.width))
        needs_axis_bridge = False
        side = ""

        # Allow modest bottom overlap (up to 26pt on tall figures) when EPS plot frame extends behind caption.
        max_bot_overlap = -26.0 if rect.height >= 120.0 else -14.0
        if h_ov >= min_ov:
            gap_below = cr.y0 - rect.y1
            gap_above = rect.y0 - cr.y1
            if max_bot_overlap <= gap_below <= cfg.caption_below_bridge_gap:
                dist = abs(gap_below)
                side = "below"
                needs_axis_bridge = gap_below > cfg.caption_below_max_gap
            elif -14.0 <= gap_above <= cfg.caption_above_max_gap:
                dist = abs(gap_above) + 18.0
                side = "above"
            else:
                dist = float("inf")
        elif (
            allow_side
            and _vert_overlap(rect, cr) >= 10.0
            and (
                abs(cr.y0 - rect.y0) <= cfg.caption_side_align_y
                or abs(cr.y1 - rect.y1) <= cfg.caption_side_align_y
            )
        ):
            gap_x = max(0.0, max(rect.x0, cr.x0) - min(rect.x1, cr.x1))
            if gap_x <= cfg.caption_side_max_gap_x:
                dist = gap_x + 24.0
                side = "side"
            else:
                dist = float("inf")
        else:
            continue

        if dist < best_dist:
            span = rect | cr
            blocked = False
            max_axis_y1 = -1.0
            for tb in text_blocks:
                if tb.rect == cr or tb.kind == "fig_caption":
                    continue
                if (
                    needs_axis_bridge
                    and _horiz_overlap(tb.rect, span) >= 10.0
                    and rect.y1 - 2.0 <= tb.rect.y0
                    and tb.rect.y1 <= cr.y0 + 2.0
                    and _is_short_axis_label(tb)
                ):
                    max_axis_y1 = max(max_axis_y1, tb.rect.y1)
                if tb.word_count < 4 or _is_short_axis_label(tb):
                    continue
                if (
                    cr.y1 <= rect.y0
                    and 0.0 <= tb.rect.y0 - cr.y1 <= 10.0
                    and tb.word_count <= 14
                    and tb.rect.height <= 26.0
                    and _horiz_overlap(tb.rect, cr) >= 20.0
                ):
                    continue
                if _horiz_overlap(tb.rect, span) >= 20.0 and (
                    (rect.y1 <= tb.rect.y0 + 2 and tb.rect.y1 <= cr.y0 + 2)
                    or (cr.y1 <= tb.rect.y0 + 2 and tb.rect.y1 <= rect.y0 + 2)
                ):
                    blocked = True
                    break
            if needs_axis_bridge and (max_axis_y1 < 0.0 or (cr.y0 - max_axis_y1) > 45.0):
                blocked = True
            if not blocked:
                best_dist = dist
                best_idx = idx
                best_side = side

    return best_idx, best_side, best_dist


def _match_caption(
    rect: pymupdf.Rect,
    fig_captions: list[TextBlock],
    text_blocks: list[TextBlock],
    cfg: DetectorConfig = DEFAULT_CONFIG,
    allow_side: bool = True,
) -> int | None:
    """Find the most likely figure caption belonging to `rect`, if any."""
    idx, _, _ = _match_caption_scored(rect, fig_captions, text_blocks, cfg=cfg, allow_side=allow_side)
    return idx


def _has_obstacle_between(
    a: pymupdf.Rect,
    b: pymupdf.Rect,
    text_blocks: list[TextBlock],
    rules: list[pymupdf.Rect],
    allow_axis_labels: bool = False,
) -> bool:
    """Return True if a prose/caption block or divider rule lies strictly between `a` and `b`."""
    if a.y1 <= b.y0 or b.y1 <= a.y0:
        top, bot = (a, b) if a.y1 <= b.y0 else (b, a)
        x_lo, x_hi = min(a.x0, b.x0), max(a.x1, b.x1)
        for tb in text_blocks:
            if allow_axis_labels and _is_short_axis_label(tb):
                continue
            tr = tb.rect
            tr_area = max(1.0, tr.get_area())
            if (tr & a).get_area() >= 0.5 * tr_area or (tr & b).get_area() >= 0.5 * tr_area:
                continue
            if tr.y0 >= top.y1 - 4.0 and tr.y1 <= bot.y0 + 4.0:
                if max(0.0, min(x_hi, tr.x1) - max(x_lo, tr.x0)) >= 15.0:
                    return True
        for rr in rules:
            if top.y1 + 0.5 < rr.y0 and rr.y1 < bot.y0 - 0.5 and rr.height <= 4.0:
                if max(0.0, min(x_hi, rr.x1) - max(x_lo, rr.x0)) >= 0.4 * (x_hi - x_lo):
                    return True

    if a.x1 <= b.x0 or b.x1 <= a.x0:
        left, right = (a, b) if a.x1 <= b.x0 else (b, a)
        y_lo, y_hi = min(a.y0, b.y0), max(a.y1, b.y1)
        for tb in text_blocks:
            if allow_axis_labels and _is_short_axis_label(tb, vertical_ok=True):
                continue
            tr = tb.rect
            tr_area = max(1.0, tr.get_area())
            if (tr & a).get_area() >= 0.5 * tr_area or (tr & b).get_area() >= 0.5 * tr_area:
                continue
            if tr.x0 >= left.x1 - 4.0 and tr.x1 <= right.x0 + 4.0:
                if max(0.0, min(y_hi, tr.y1) - max(y_lo, tr.y0)) >= 12.0:
                    return True
        for rr in rules:
            if left.x1 + 0.5 < rr.x0 and rr.x1 < right.x0 - 0.5 and rr.width <= 4.0:
                if max(0.0, min(y_hi, rr.y1) - max(y_lo, rr.y0)) >= 0.4 * (y_hi - y_lo):
                    return True

    return False


def _row_aligned_text_indices(
    rect: pymupdf.Rect, text_blocks: list[TextBlock], max_gap_x: float = 80.0
) -> list[int]:
    """Return sorted indices of regular horizontal text blocks sharing a table row with `rect`."""
    indices: list[int] = []
    for idx, tb in enumerate(text_blocks):
        if tb.kind != "text":
            continue
        tr = tb.rect
        # Never treat rotated Y-axis titles as horizontal table-row cells.
        if tr.width <= 28.0 and tr.height >= 1.8 * tr.width:
            continue
        if _horiz_overlap(rect, tr) > 5.0:
            continue
        gap_x = max(0.0, max(rect.x0, tr.x0) - min(rect.x1, tr.x1))
        if gap_x > max_gap_x:
            continue
        # Never treat adjacent Y-axis tick values, short particle/math symbols, or subpanel markers as table rows.
        cleaned = _clean_text(tb.text)
        tokens = cleaned.split()
        if not tokens or len(cleaned) <= 4 or all(len(tok) <= 2 for tok in tokens):
            continue
        if len(tokens) <= 4 and all(
            _TICK_TOKEN_RE.match(tok) or _SUBPANEL_LABEL_RE.match(tok) for tok in tokens
        ):
            continue
        vert_nested = (
            tr.y0 >= rect.y0 - 8.0
            and tr.y1 <= rect.y1 + 12.0
            and _vert_overlap(rect, tr) >= min(6.0, tr.height * 0.6)
        )
        top_aligned = (
            abs(tr.y0 - rect.y0) <= 12.0
            and _vert_overlap(rect, tr) >= 8.0
            and tr.height <= rect.height + 28.0
        )
        if vert_nested or top_aligned:
            indices.append(idx)
    indices.sort(key=lambda i: text_blocks[i].rect.x0)
    return indices


def _is_table_row_pair(a: pymupdf.Rect, b: pymupdf.Rect, text_blocks: list[TextBlock]) -> bool:
    """Return True if vertically stacked `a` and `b` align with separate adjacent table-row texts."""
    if min(a.width, b.width) >= 165.0:
        return False
    if not (a.y1 <= b.y0 + 2.0 or b.y1 <= a.y0 + 2.0):
        return False
    if _horiz_overlap(a, b) < 0.5 * min(a.width, b.width):
        return False
    ma = _row_aligned_text_indices(a, text_blocks, max_gap_x=80.0)
    mb = _row_aligned_text_indices(b, text_blocks, max_gap_x=80.0)
    return bool(ma and mb and ma[0] != mb[0])
