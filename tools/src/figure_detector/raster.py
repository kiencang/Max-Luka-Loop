"""Phase 2 — foreground raster regions; scanned-page detection; banner/watermark rejection."""

from __future__ import annotations

from image_ops import _ensure_rgb_or_gray, _find_ink_bounds

from .caption_match import (
    _match_caption,
)
from .geometry import (
    _count_words_inside,
    _is_edge_ornament,
    _is_full_bleed_edge_strip,
    _is_hero_header_banner,
    _is_page_background,
    _is_vertical_bleed_strip,
    _merge_touching,
    _vert_overlap,
)
from .model import (
    DEFAULT_CONFIG,
    DetectorConfig,
    PageContext,
    pymupdf,
)
from .text import (
    _is_short_axis_label,
)


def _image_ink_rect(ctx: PageContext, info: dict, cfg: DetectorConfig) -> pymupdf.Rect | None:
    """Page-space bounding box of the non-white pixels of an embedded image, or None if unknown.

    Embedded images often carry wide white margins (scans, exported plots); their placement box then covers
    nearby captions, body text or the running header. The image's own pixels are analysed (not a page render,
    which would also contain text printed over the margin) and mapped through the image's placement matrix,
    which also handles rotated/flipped placements.
    """
    xref = info.get("xref") or 0
    if not xref:
        return None  # inline image: no xref to decode
    w, h = info.get("width") or 0, info.get("height") or 0
    if w <= 0 or h <= 0 or w * h > cfg.raster_trim_max_pixels:
        return None
    doc = ctx.page.parent
    try:
        pix = pymupdf.Pixmap(doc, xref)
        smask = doc.xref_get_key(xref, "SMask")
        if smask[0] == "xref" and not pix.alpha:
            mask = pymupdf.Pixmap(doc, int(smask[1].split()[0]))
            if (mask.width, mask.height) == (pix.width, pix.height):
                pix = pymupdf.Pixmap(pix, mask)  # apply soft mask as alpha
        while pix.width > 1600 or pix.height > 1600:
            pix.shrink(1)
        pix = _ensure_rgb_or_gray(pix)
        bounds = _find_ink_bounds(pix, threshold=247, step=2)
    except Exception as exc:  # noqa: BLE001 - trimming is optional: any decode problem keeps the original box
        ctx.log(f"raster:trim_failed xref={xref} {type(exc).__name__}: {exc}")
        return None
    if bounds is None:
        return None
    x0, y0, x1, y1 = bounds
    pw, ph = float(pix.width), float(pix.height)
    unit = pymupdf.Rect(max(0, x0 - 2) / pw, max(0, y0 - 2) / ph, min(pw, x1 + 3) / pw, min(ph, y1 + 3) / ph)
    return unit * pymupdf.Matrix(info["transform"])


def _reattach_overlaid_labels(ctx: PageContext, original: pymupdf.Rect, trimmed: pymupdf.Rect) -> pymupdf.Rect:
    """Re-include short label text (axis titles, ticks, panel letters) printed over the trimmed white margin.

    Plots exported as images frequently get their axis labels as real PDF text drawn on top of the image's white
    border. Those blocks lie inside the original placement box and belong to the figure; captions, prose and the
    running header/footer in the page margins do not.
    """
    top_band = ctx.page_rect.y0 + 0.10 * ctx.ph  # running headers sit in the top ~10%
    bottom_band = ctx.page_rect.y1 - 0.06 * ctx.ph
    inside = pymupdf.Rect(original.x0 - 1.0, original.y0 - 1.0, original.x1 + 1.0, original.y1 + 1.0)
    out = pymupdf.Rect(trimmed)
    for tb in ctx.text_blocks:
        r = tb.rect
        if tb.kind != "text" or not inside.contains(r) or trimmed.contains(r):
            continue
        if r.y1 <= top_band or r.y0 >= bottom_band:
            continue
        if _is_short_axis_label(tb, vertical_ok=True):
            out |= r
    return out


def detect_raster_regions(
    ctx: PageContext, cfg: DetectorConfig = DEFAULT_CONFIG
) -> tuple[list[pymupdf.Rect], bool]:
    """Phase 2: Collect foreground raster regions and report whether a full-page image exists."""
    raw_rects: list[pymupdf.Rect] = []
    has_full_page_img = False

    infos = ctx.page.get_image_info(xrefs=True)
    trim_allowed = len(infos) <= cfg.raster_trim_max_images
    for info in infos:
        r = pymupdf.Rect(info["bbox"]) & ctx.page_rect
        if r.is_empty or r.width < 1.0 or r.height < 1.0:
            continue
        if _is_page_background(r, ctx.pw, ctx.ph, cfg):
            has_full_page_img = True
            ctx.log(f"raster:skip page_background {r}")
            continue
        if _is_vertical_bleed_strip(r, ctx.page_rect, cfg) and _match_caption(r, ctx.fig_captions, ctx.text_blocks, cfg) is None:
            ctx.log(f"raster:skip vertical_bleed {r}")
            continue
        # Trim white image margins only after the page-background checks above, so a scanned page with white
        # borders is still recognised as a background instead of turning into one giant "figure".
        if trim_allowed and r.get_area() >= cfg.min_raster_area:
            ink = _image_ink_rect(ctx, info, cfg)
            if ink is not None:
                trimmed = ink & r
                if trimmed.is_empty:
                    ctx.log(f"raster:skip blank_image {r}")
                    continue
                if trimmed.get_area() < (1.0 - cfg.raster_trim_min_gain) * r.get_area():
                    trimmed = _reattach_overlaid_labels(ctx, r, trimmed)
                    ctx.log(f"raster:trim_white_margin {r} -> {trimmed}")
                    r = trimmed
        raw_rects.append(r)

    merged = _merge_touching(raw_rects, pad=cfg.touch_pad)
    kept: list[pymupdf.Rect] = []
    for r in merged:
        if _is_page_background(r, ctx.pw, ctx.ph, cfg):
            has_full_page_img = True
            ctx.log(f"raster:skip tiled_page_background {r}")
            continue
        is_normal_box = r.width >= cfg.min_raster_dim and r.height >= cfg.min_raster_dim and r.get_area() >= cfg.min_raster_area
        is_banner_strip = (
            min(r.width, r.height) >= cfg.min_strip_short_dim
            and max(r.width, r.height) >= cfg.min_strip_long_dim
            and r.get_area() >= cfg.min_strip_area
        )
        if not (is_normal_box or is_banner_strip):
            continue

        has_cap = _match_caption(r, ctx.fig_captions, ctx.text_blocks, cfg) is not None
        if not has_cap and (_is_full_bleed_edge_strip(r, ctx.page_rect, cfg) or _is_hero_header_banner(r, ctx, cfg)):
            ctx.log(f"raster:skip edge_or_hero_banner {r}")
            continue
        if _is_edge_ornament(r, ctx.page_rect, ctx.fig_captions):
            ctx.log(f"raster:skip edge_ornament {r}")
            continue

        if not has_cap:
            if not is_normal_box:
                if r.width < cfg.min_raster_dim and r.height >= 0.45 * ctx.ph:
                    continue
                if any(
                    r.intersects(wr) and _vert_overlap(r, wr) >= 0.45 * min(r.height, wr.height)
                    for wr in ctx.word_rects
                ):
                    ctx.log(f"raster:skip text_overlaid_strip {r}")
                    continue
            else:
                prose_blocks = [
                    tb
                    for tb in ctx.text_blocks
                    if tb.kind == "text"
                    and tb.word_count >= 10
                    and (tb.rect & r).get_area() >= 0.5 * min(tb.rect.get_area(), r.get_area())
                ]
                is_single_col_prose = (
                    _count_words_inside(r, ctx.word_rects) >= 85
                    and any(
                        (tb.rect & r).get_area() >= 0.75 * max(1.0, r.get_area()) and tb.word_count >= 85
                        for tb in prose_blocks
                    )
                )
                if (len(prose_blocks) >= 3 and sum(tb.word_count for tb in prose_blocks) >= 85) or is_single_col_prose:
                    ctx.log(f"raster:skip prose_backdrop_watermark {r}")
                    continue
        kept.append(r)

    return kept, has_full_page_img
