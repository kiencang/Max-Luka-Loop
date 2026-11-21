"""Rectangle geometry primitives and drawing-shape predicates (backgrounds, bleeds, ornaments, boxes)."""

from __future__ import annotations

import math

from .model import (
    DEFAULT_CONFIG,
    DetectorConfig,
    PageContext,
    TextBlock,
    pymupdf,
)


def _horiz_overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    return max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))


def _vert_overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    return max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))


def _rect_gap(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    """Euclidean gap between two rectangles (0 if overlapping)."""
    dx = max(0.0, max(a.x0, b.x0) - min(a.x1, b.x1))
    dy = max(0.0, max(a.y0, b.y0) - min(a.y1, b.y1))
    return math.hypot(dx, dy)


def _rect_center_inside(inner: pymupdf.Rect, outer: pymupdf.Rect) -> bool:
    """Return True if `inner`'s midpoint lies inside `outer` (or overlaps >=50%)."""
    cx = 0.5 * (inner.x0 + inner.x1)
    cy = 0.5 * (inner.y0 + inner.y1)
    if outer.x0 <= cx <= outer.x1 and outer.y0 <= cy <= outer.y1:
        return True
    return (inner & outer).get_area() >= 0.5 * max(1.0, inner.get_area())


def _is_frame_for(inner: pymupdf.Rect, outer: pymupdf.Rect) -> bool:
    """Return True if `inner` is just an enclosing border/cell box around `outer`."""
    outer_area = max(1.0, outer.get_area())
    return (inner & outer).get_area() >= 0.85 * outer_area and inner.get_area() >= 0.85 * outer_area


def _is_page_background(r: pymupdf.Rect, pw: float, ph: float, cfg: DetectorConfig = DEFAULT_CONFIG) -> bool:
    """Return True if rectangle covers almost the entire page/slide canvas."""
    area_ratio = (r.width * r.height) / max(1.0, pw * ph)
    return area_ratio >= cfg.bg_area_ratio or (r.width >= cfg.bg_width_ratio * pw and r.height >= cfg.bg_height_ratio * ph)


def _is_vertical_bleed_strip(r: pymupdf.Rect, page_rect: pymupdf.Rect, cfg: DetectorConfig = DEFAULT_CONFIG) -> bool:
    """Return True for narrow full-page-height decorative bleed strips along left/right edges."""
    pw, ph = page_rect.width, page_rect.height
    return (
        r.height >= cfg.vert_bleed_h_ratio * ph
        and r.width <= cfg.vert_bleed_w_ratio * pw
        and (r.x0 <= page_rect.x0 + 12.0 or r.x1 >= page_rect.x1 - 12.0)
    )


def _is_horizontal_bleed_strip(r: pymupdf.Rect, page_rect: pymupdf.Rect, cfg: DetectorConfig = DEFAULT_CONFIG) -> bool:
    """Return True for full-page-width decorative bleed bands along top/bottom edges."""
    pw, ph = page_rect.width, page_rect.height
    return (
        r.width >= cfg.horiz_bleed_w_ratio * pw
        and r.height <= cfg.horiz_bleed_h_ratio * ph
        and (r.y0 <= page_rect.y0 + 12.0 or r.y1 >= page_rect.y1 - 12.0)
    )


def _is_full_bleed_edge_strip(r: pymupdf.Rect, page_rect: pymupdf.Rect, cfg: DetectorConfig = DEFAULT_CONFIG) -> bool:
    return _is_vertical_bleed_strip(r, page_rect, cfg) or _is_horizontal_bleed_strip(r, page_rect, cfg)


def _count_words_inside(box: pymupdf.Rect, word_rects: list[pymupdf.Rect]) -> int:
    return sum(
        1
        for wr in word_rects
        if box.contains(wr) or (box & wr).get_area() >= 0.5 * max(1e-6, wr.get_area())
    )


def _is_hero_header_banner(
    r: pymupdf.Rect, ctx: PageContext, cfg: DetectorConfig = DEFAULT_CONFIG
) -> bool:
    """Return True for top full-bleed datasheet/brochure hero banners overlaid with title text."""
    if r.width < cfg.horiz_bleed_w_ratio * ctx.pw:
        return False
    if r.y0 > ctx.page_rect.y0 + 8.0 or r.height > cfg.hero_banner_h_ratio * ctx.ph:
        return False
    return _count_words_inside(r, ctx.word_rects) >= cfg.hero_banner_min_words


def _is_edge_ornament(r: pymupdf.Rect, page_rect: pymupdf.Rect, fig_captions: list[TextBlock]) -> bool:
    """Filter out small running header/footer logos, page badges, and margin bars."""
    if r.height >= 62.0:
        return False
    top_y, bot_y = page_rect.y0, page_rect.y1
    in_margin = (
        r.y1 < (top_y + 54.0)
        or r.y0 > (bot_y - 45.0)
        or (r.y0 < (top_y + 42.0) and r.height < 50.0)
        or (r.width >= 0.60 * page_rect.width and (r.y0 < (top_y + 36.0) or r.y1 > (bot_y - 36.0)))
    )
    if not in_margin:
        return False
    for cap in fig_captions:
        if _horiz_overlap(r, cap.rect) >= 20.0 and abs(cap.rect.y0 - r.y1) < 40.0:
            return False
    return True


def _merge_touching(
    rects: list[pymupdf.Rect],
    pad: float = 2.0,
    prevent_page_bg: tuple[float, float, DetectorConfig] | None = None,
) -> list[pymupdf.Rect]:
    """Merge overlapping or tightly touching rectangles within `pad` points."""
    merged: list[pymupdf.Rect] = []
    for r in sorted(rects, key=lambda x: (round(x.y0, 1), round(x.x0, 1))):
        cur = pymupdf.Rect(r)
        changed = True
        while changed:
            changed = False
            rest: list[pymupdf.Rect] = []
            for m in merged:
                expanded = pymupdf.Rect(m.x0 - pad, m.y0 - pad, m.x1 + pad, m.y1 + pad)
                if cur.intersects(expanded):
                    cand_union = cur | m
                    if prevent_page_bg is not None:
                        pw, ph, cfg = prevent_page_bg
                        if (
                            _is_page_background(cand_union, pw, ph, cfg)
                            and not _is_page_background(cur, pw, ph, cfg)
                            and not _is_page_background(m, pw, ph, cfg)
                        ):
                            rest.append(m)
                            continue
                    cur = cand_union
                    changed = True
                else:
                    rest.append(m)
            merged = rest
        merged.append(cur)
    return sorted(merged, key=lambda x: (round(x.y0, 1), round(x.x0, 1)))


def _is_light_gray_watermark_glyph(dr: dict) -> bool:
    """Return True if `dr` looks like an outlined light-gray diagonal watermark glyph."""
    if dr.get("color") is not None:
        return False
    fill = dr.get("fill")
    if fill is None or len(dr.get("items") or ()) < 10:
        return False
    r = dr["rect"]
    if max(r.width, r.height) > 95.0:
        return False
    if isinstance(fill, (int, float)):
        return float(fill) >= 0.68
    if isinstance(fill, (tuple, list)):
        if len(fill) == 1:
            return float(fill[0]) >= 0.68
        if len(fill) >= 3:
            rgb = [float(v) for v in fill[:3]]
            return min(rgb) >= 0.68 and (max(rgb) - min(rgb)) <= 0.06
    return False


def _is_rounded_rect_drawing(dr: dict) -> bool:
    """Return True if `dr` is a rounded rectangle or pill badge (axis-aligned sides + corner arcs).

    Handles both single-Bézier-per-corner renderers (ReportLab, LaTeX, Illustrator: 4–10 items)
    and multi-segment arc renderers (Chromium/Skia, WeasyPrint, Cairo: up to ~44 items).
    """
    items = dr.get("items") or ()
    if not (4 <= len(items) <= 44):
        return False
    r = dr["rect"]
    if r.width < 10.0 or r.height < 6.0:
        return False
    edge_tol = max(3.0, 0.12 * min(r.width, r.height))
    is_pill = max(r.width, r.height) >= 2.2 * min(r.width, r.height) and min(r.width, r.height) <= 24.0
    max_corner = (0.55 * min(r.width, r.height) + 2.0) if is_pill else max(16.0, 0.30 * min(r.width, r.height))
    corners = ((r.x0, r.y0), (r.x1, r.y0), (r.x0, r.y1), (r.x1, r.y1))

    def _near_corner(pt) -> bool:
        return any(max(abs(pt.x - cx), abs(pt.y - cy)) <= max_corner for cx, cy in corners)

    lines = 0
    curves = 0
    for it in items:
        kind = it[0]
        if kind == "l" and len(it) >= 3:
            p0, p1 = it[1], it[2]
            is_h = abs(p0.y - p1.y) <= 1.5
            is_v = abs(p0.x - p1.x) <= 1.5
            if not (is_h or is_v):
                return False
            if is_h and min(abs(p0.y - r.y0), abs(p0.y - r.y1)) > edge_tol:
                return False
            if is_v and min(abs(p0.x - r.x0), abs(p0.x - r.x1)) > edge_tol:
                return False
            if math.hypot(p0.x - p1.x, p0.y - p1.y) >= 1.5:
                lines += 1
        elif kind == "c" and len(it) >= 5:
            p0, p3 = it[1], it[4]
            if not (_near_corner(p0) and _near_corner(p3)):
                return False
            if math.hypot(p0.x - p3.x, p0.y - p3.y) > max_corner * 1.45:
                return False
            curves += 1
        elif kind == "re":
            continue
        else:
            return False
    return curves > 0 and lines >= 2


def _is_tiny_bullet_dot(dr: dict) -> bool:
    """Return True for a tiny strokeless filled dot/bullet (<= 6.5pt), e.g., an HTML list marker."""
    r = dr["rect"]
    return dr.get("color") is None and dr.get("fill") is not None and max(r.width, r.height) <= 6.5


def _is_simple_box_drawing(dr: dict) -> bool:
    """Return True if `dr` is a single rectangular or rounded-rectangular border/backdrop."""
    items = dr.get("items") or ()
    if not items:
        return False
    if len(items) == 1 and items[0][0] == "re":
        return True
    if _is_rounded_rect_drawing(dr):
        return True
    if len(items) <= 5 and all(
        it[0] == "l" and len(it) >= 3 and (abs(it[1].x - it[2].x) <= 1.5 or abs(it[1].y - it[2].y) <= 1.5)
        for it in items
    ):
        return True
    return False


def _count_non_grid_detail(drawings: list[dict] | None, rect: pymupdf.Rect, limit: int = 12) -> int:
    """Count true curves/diagonals of `drawings` inside `rect` (ignoring card corners), stopping at `limit`.

    The result is exact below `limit` and equals `limit` once reached, so `count >= k` answers
    "at least k curves?" for every k <= limit in a single pass.
    """
    if not drawings:
        return 0
    count = 0
    for dr in drawings:
        if not rect.contains(dr["rect"]):
            continue
        if _is_rounded_rect_drawing(dr):
            continue
        for item in dr.get("items") or ():
            kind = item[0]
            if kind in ("c", "qu"):
                count += 1
            elif kind == "l" and len(item) >= 3:
                p0, p1 = item[1], item[2]
                if abs(p0.x - p1.x) > 2.0 and abs(p0.y - p1.y) > 2.0:
                    count += 1
            if count >= limit:
                return limit
    return count
