"""PyMuPDF lazy loader, PDF page rendering, JSON cropping/auto-trim, and in-memory image optimization."""

from __future__ import annotations

import json
import math
import os
import re
import struct
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from path_guards import (
    assert_local_no_unc_path,
    get_allowed_crop_input_roots,
    resolve_safe_crop_input_file,
    resolve_safe_crop_out_file,
    resolve_safe_out_directory,
)

if TYPE_CHECKING:
    import pymupdf

_pymupdf = None

_PAGE_TOKEN_SPLIT_RE = re.compile(r"[,;\s]+")
_PAGE_RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')

# Resource-exhaustion & decompression-bomb limits
MAX_RENDER_DIM = 6000
MAX_RENDER_PIXELS = 25_000_000  # 25 MP (~75 MB RGB Pixmap)
MAX_IMAGE_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per image file
MAX_IMAGE_PIXELS = 50_000_000  # 50 MP max decoded image pixels
MAX_IMAGE_DIM = 16000  # 16,000 px max single dimension


def compute_safe_render_zoom(width_pt: float, height_pt: float, desired_zoom: float) -> tuple[float, bool]:
    """Clamp PDF render zoom so rendered Pixmap stays within MAX_RENDER_DIM and MAX_RENDER_PIXELS."""
    w = max(1e-6, float(width_pt))
    h = max(1e-6, float(height_pt))
    z = max(1e-6, float(desired_zoom))
    max_z_dim = min(MAX_RENDER_DIM / w, MAX_RENDER_DIM / h)
    max_z_area = math.sqrt(MAX_RENDER_PIXELS / (w * h))
    cap_z = min(max_z_dim, max_z_area)
    if z > cap_z:
        return cap_z, True
    return z, False


def _peek_image_dimensions(img_path: Path) -> tuple[int, int] | None:
    """Read (width, height) from PNG/JPEG/GIF/BMP/WebP headers without decompressing pixel payloads."""
    try:
        with open(img_path, "rb") as fh:
            hdr = fh.read(32)
            if len(hdr) < 10:
                return None
            # PNG: 8-byte signature + IHDR chunk length/type + 4-byte BE width + 4-byte BE height
            if hdr[:8] == b"\x89PNG\r\n\x1a\n" and len(hdr) >= 24 and hdr[12:16] == b"IHDR":
                w, h = struct.unpack(">II", hdr[16:24])
                return int(w), int(h)
            # GIF87a / GIF89a
            if hdr[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", hdr[6:10])
                return int(w), int(h)
            # BMP
            if hdr[:2] == b"BM" and len(hdr) >= 26:
                w, h = struct.unpack("<ii", hdr[18:26])
                return abs(int(w)), abs(int(h))
            # WebP (VP8X / VP8L / VP8 )
            if hdr[:4] == b"RIFF" and len(hdr) >= 30 and hdr[8:12] == b"WEBP":
                chunk = hdr[12:16]
                if chunk == b"VP8X":
                    w = 1 + int.from_bytes(hdr[24:27], "little")
                    h = 1 + int.from_bytes(hdr[27:30], "little")
                    return w, h
                if chunk == b"VP8L" and hdr[20] == 0x2F:
                    bits = struct.unpack("<I", hdr[21:25])[0]
                    return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
                if chunk == b"VP8 " and hdr[23:26] == b"\x9d\x01\x2a":
                    w, h = struct.unpack("<HH", hdr[26:30])
                    return w & 0x3FFF, h & 0x3FFF
            # JPEG: scan SOF0..SOF15 markers (excluding DHT/JPG/DAC) without decoding entropy stream
            if hdr[:2] == b"\xff\xd8":
                fh.seek(2)
                sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
                bytes_scanned = 2
                while bytes_scanned < 262144:
                    b = fh.read(1)
                    if not b:
                        break
                    bytes_scanned += 1
                    if b[0] != 0xFF:
                        continue
                    while True:
                        m = fh.read(1)
                        if not m:
                            return None
                        bytes_scanned += 1
                        if m[0] != 0xFF:
                            marker = m[0]
                            break
                    if marker in (0xD8, 0xD9, 0x01) or (0xD0 <= marker <= 0xD7):
                        continue
                    if marker == 0xDA:  # Start of Scan (image data begins)
                        break
                    seg_len_b = fh.read(2)
                    if len(seg_len_b) < 2:
                        break
                    bytes_scanned += 2
                    seg_len = struct.unpack(">H", seg_len_b)[0]
                    if seg_len < 2:
                        break
                    if marker in sof_markers:
                        sof = fh.read(5)
                        if len(sof) == 5:
                            h, w = struct.unpack(">HH", sof[1:5])
                            return int(w), int(h)
                        break
                    fh.seek(seg_len - 2, os.SEEK_CUR)
                    bytes_scanned += seg_len - 2
    except OSError:
        return None
    return None


def assert_safe_image_file(img_path: Path) -> None:
    """Reject oversized image files and decompression bombs before decoding into memory."""
    if not img_path.is_file():
        raise FileNotFoundError(f"Image file not found: {img_path}")
    file_bytes = img_path.stat().st_size
    if file_bytes > MAX_IMAGE_FILE_BYTES:
        raise ValueError(
            f"Refusing oversized image file ({file_bytes:,} bytes > {MAX_IMAGE_FILE_BYTES:,} byte limit): {img_path}"
        )
    dims = _peek_image_dimensions(img_path)
    if dims is not None:
        w, h = dims
        if w <= 0 or h <= 0 or max(w, h) > MAX_IMAGE_DIM or (w * h) > MAX_IMAGE_PIXELS:
            raise ValueError(
                f"Refusing decompression-bomb / oversized image ({w}x{h} = {w * h:,} px; "
                f"limit {MAX_IMAGE_DIM}px/edge, {MAX_IMAGE_PIXELS:,} px total): {img_path}"
            )


def ensure_pymupdf():
    """Lazily import PyMuPDF so non-PDF/0-image commands avoid loading MuPDF DLLs."""
    global _pymupdf
    if _pymupdf is None:
        # Silence PyMuPDF 1.28+ optional layout-package nag on clean structured stdout.
        os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")
        import pymupdf as _pm

        _pymupdf = _pm
    return _pymupdf


def _read_json_utf8(path: Path) -> object:
    """Load a UTF-8 JSON file (accepting optional BOM)."""
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _ensure_rgb_or_gray(pix: pymupdf.Pixmap) -> pymupdf.Pixmap:
    """Convert non-gray/non-RGB pixmaps (e.g., CMYK or None colorspace) into RGB."""
    pm = ensure_pymupdf()
    if pix.colorspace is None or (pix.n - pix.alpha) not in (1, 3):
        return pm.Pixmap(pm.csRGB, pix)
    return pix


def _crop_pixmap(pix: pymupdf.Pixmap, x0: int, y0: int, x1: int, y1: int) -> pymupdf.Pixmap:
    """Copy rectangular region [x0, y0, x1, y1) from `pix` into a zero-origin Pixmap."""
    pm = ensure_pymupdf()
    rect = pm.IRect(x0, y0, x1, y1)
    out = pm.Pixmap(pix.colorspace, rect, bool(pix.alpha))
    out.copy(pix, rect)
    out.set_origin(0, 0)
    return out


def _decode_pixel_rgb_alpha(
    mv: memoryview, idx: int, color_n: int, has_alpha_chan: bool
) -> tuple[int, int, int, int]:
    """Read pixel at byte offset `idx`, un-premultiplying alpha into straight (r, g, b, a)."""
    a = mv[idx + color_n] if has_alpha_chan else 255
    if color_n == 1:
        r = g = b = mv[idx]
    else:
        r, g, b = mv[idx], mv[idx + 1], mv[idx + 2]
    if has_alpha_chan and 0 < a < 255:
        half = a >> 1
        r = min(255, (r * 255 + half) // a)
        g = min(255, (g * 255 + half) // a)
        b = min(255, (b * 255 + half) // a)
    return r, g, b, a


def _parse_page_list(raw_pages: str, total_pages: int) -> list[int]:
    """Parse optional page filter (e.g. '2', '2,5', '[1, 3]', '2-4') into sorted 1-based pages."""
    if total_pages < 1:
        return []
    cleaned = (raw_pages or "").strip().strip("[]").strip()
    if not cleaned:
        return list(range(1, total_pages + 1))

    tokens = [tok for tok in _PAGE_TOKEN_SPLIT_RE.split(cleaned) if tok]
    if not tokens:
        return list(range(1, total_pages + 1))

    seen: set[int] = set()
    for tok in tokens:
        m = _PAGE_RANGE_RE.match(tok)
        if m:
            start_p = int(m.group(1))
            end_p = int(m.group(2))
            if start_p < 1 or end_p < start_p or end_p > total_pages:
                raise ValueError(f"Page range '{tok}' out of valid range (1..{total_pages}).")
            seen.update(range(start_p, end_p + 1))
        elif tok.isdigit():
            p = int(tok)
            if p < 1 or p > total_pages:
                raise ValueError(f"Page number {p} out of valid range (1..{total_pages}).")
            seen.add(p)
        else:
            raise ValueError(
                f"Invalid -Pages token '{tok}'. Expected positive integers or ranges like '2,5' or '2-4'."
            )
    return sorted(seen)


def render_pages(
    pdf_path: Path, out_dir: Path, scale: float = 2.5, pages: str = ""
) -> list[Path]:
    """Render selected PDF pages to opaque white-background PNGs (`page_1.png`, ...)."""
    pm = ensure_pymupdf()
    assert_local_no_unc_path(pdf_path, "-PdfPath")
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not math.isfinite(scale) or scale < 0.5 or scale > 10.0:
        raise ValueError(f"RenderScale out of safe range (0.5..10.0): {scale}")

    safe_out_dir = resolve_safe_out_directory(out_dir, "-OutDir", create=True)
    saved: list[Path] = []
    with pm.open(pdf_path) as doc:
        if doc.needs_pass:
            raise RuntimeError(f"PDF is password-protected/encrypted and cannot be rendered: {pdf_path}")
        total_pages = len(doc)
        target_pages = _parse_page_list(pages, total_pages)

        for pno in target_pages:
            page = doc[pno - 1]
            target_w = max(800, int(round(page.rect.width * scale)))
            desired_zoom = target_w / max(1e-6, page.rect.width)
            zoom, was_clamped = compute_safe_render_zoom(page.rect.width, page.rect.height, desired_zoom)
            if was_clamped:
                print(
                    f"WARNING: Clamped page {pno} render scale ({desired_zoom:.2f}x -> {zoom:.2f}x) "
                    f"to stay within {MAX_RENDER_DIM}px / {MAX_RENDER_PIXELS:,}px safety limit.",
                    file=sys.stderr,
                )
            pix = page.get_pixmap(matrix=pm.Matrix(zoom, zoom), alpha=False)
            out_png = safe_out_dir / f"page_{pno}.png"
            out_png.write_bytes(pix.tobytes("png"))
            saved.append(out_png)
            print(f"Rendered page {pno}/{total_pages} -> {out_png} ({pix.width}px wide)")
    return saved


def _scan_ink_range(
    mv: memoryview,
    start_idx: int,
    stop_idx: int,
    idx_step: int,
    color_n: int,
    has_alpha: bool,
    threshold: int,
) -> bool:
    """Return True if any sampled pixel offset in range has visible non-white ink."""
    for idx in range(start_idx, stop_idx, idx_step):
        if has_alpha:
            a = mv[idx + color_n]
            if a <= 10:
                continue
            if a < 255:
                half = a >> 1
                if color_n == 1:
                    if min(255, (mv[idx] * 255 + half) // a) < threshold:
                        return True
                elif (
                    min(255, (mv[idx] * 255 + half) // a) < threshold
                    or min(255, (mv[idx + 1] * 255 + half) // a) < threshold
                    or min(255, (mv[idx + 2] * 255 + half) // a) < threshold
                ):
                    return True
                continue
        if color_n == 1:
            if mv[idx] < threshold:
                return True
        elif mv[idx] < threshold or mv[idx + 1] < threshold or mv[idx + 2] < threshold:
            return True
    return False


def _find_ink_bounds(
    pix: pymupdf.Pixmap, threshold: int = 247, step: int = 2
) -> tuple[int, int, int, int] | None:
    """Return inclusive grid bounds (min_x, min_y, max_x, max_y) of non-white visible ink."""
    w, h = pix.width, pix.height
    if w <= 0 or h <= 0:
        return None
    inc = max(1, step)
    color_n = pix.n - pix.alpha
    has_alpha = bool(pix.alpha)
    n = pix.n
    stride = w * n
    mv = pix.samples_mv

    ys = list(range(0, h, inc))
    xs = list(range(0, w, inc))

    min_y: int | None = None
    for y in ys:
        row_off = y * stride
        if _scan_ink_range(mv, row_off, row_off + stride, inc * n, color_n, has_alpha, threshold):
            min_y = y
            break
    if min_y is None:
        return None

    max_y = min_y
    for y in reversed(ys):
        if y <= min_y:
            break
        row_off = y * stride
        if _scan_ink_range(mv, row_off, row_off + stride, inc * n, color_n, has_alpha, threshold):
            max_y = y
            break

    col_step = inc * stride
    min_x = xs[0]
    for x in xs:
        col_off = x * n
        if _scan_ink_range(
            mv, min_y * stride + col_off, max_y * stride + col_off + 1, col_step, color_n, has_alpha, threshold
        ):
            min_x = x
            break

    max_x = min_x
    for x in reversed(xs):
        if x <= min_x:
            break
        col_off = x * n
        if _scan_ink_range(
            mv, min_y * stride + col_off, max_y * stride + col_off + 1, col_step, color_n, has_alpha, threshold
        ):
            max_x = x
            break

    return min_x, min_y, max_x, max_y


def _trim_white_margins(
    pix: pymupdf.Pixmap, threshold: int = 247, pad: int = 6
) -> pymupdf.Pixmap:
    """Crop excess white/transparent borders around visible ink with padding."""
    bounds = _find_ink_bounds(pix, threshold=threshold, step=2)
    if bounds is None:
        return pix
    min_x, min_y, max_x, max_y = bounds
    x0 = max(0, min_x - pad)
    y0 = max(0, min_y - pad)
    x1 = min(pix.width - 1, max_x + pad)
    y1 = min(pix.height - 1, max_y + pad)
    if x0 == 0 and y0 == 0 and x1 == pix.width - 1 and y1 == pix.height - 1:
        return pix
    return _crop_pixmap(pix, x0, y0, x1 + 1, y1 + 1)


def _validate_crop_box(box: object, out_name: str) -> tuple[float, float, float, float]:
    """Validate normalized [x0, y0, x1, y1] box coordinates in [0.0, 1.0] with x1 > x0, y1 > y0."""
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError(f"Invalid crop box for '{out_name}': expected 4 numeric elements [x0, y0, x1, y1].")
    vals: list[float] = []
    for idx, raw in enumerate(box):
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"Invalid crop box coordinate at index {idx} for '{out_name}'.")
        val = float(raw)
        if not math.isfinite(val) or val < 0.0 or val > 1.0:
            raise ValueError(
                f"Crop box coordinate {raw} at index {idx} out of normalized range [0.0, 1.0] for '{out_name}'."
            )
        vals.append(val)
    if vals[2] <= vals[0] or vals[3] <= vals[1]:
        raise ValueError(f"Invalid crop box {vals} for '{out_name}': require x1 > x0 and y1 > y0.")
    return vals[0], vals[1], vals[2], vals[3]


def crop_from_json(spec_path: Path, out_dir: Path) -> list[Path]:
    """Crop normalized [x0, y0, x1, y1] regions defined in JSON spec with optional white-border auto-trim."""
    pm = ensure_pymupdf()
    assert_local_no_unc_path(spec_path, "-SpecJson")
    raw = _read_json_utf8(spec_path)
    if isinstance(raw, dict) and "items" in raw:
        items = raw["items"]
    elif isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = [raw]
    else:
        raise ValueError(f"Crop spec JSON must be an array or object with 'items': {spec_path}")
    if not isinstance(items, list):
        raise ValueError(f"Invalid crop spec items list in {spec_path}")

    safe_out_dir = resolve_safe_out_directory(out_dir, "-OutDir", create=True)
    abs_json = Path(os.path.abspath(str(spec_path)))
    allowed_roots = get_allowed_crop_input_roots(json_dir=abs_json.parent, dest_dir=safe_out_dir)

    saved: list[Path] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each crop spec item must be a JSON object.")
        out_name = str(item.get("out_name", "")).strip()
        out_file = resolve_safe_crop_out_file(safe_out_dir, out_name, _INVALID_FILENAME_CHARS)
        src_raw = str(item.get("src_path") or item.get("page_png") or "").strip()
        src_path = resolve_safe_crop_input_file(src_raw, allowed_roots)

        bx0, by0, bx1, by1 = _validate_crop_box(item.get("box"), out_name)
        assert_safe_image_file(src_path)
        pix = _ensure_rgb_or_gray(pm.Pixmap(str(src_path)))
        bw, bh = pix.width, pix.height
        if max(bw, bh) > MAX_IMAGE_DIM or (bw * bh) > MAX_IMAGE_PIXELS:
            raise ValueError(f"Refusing oversized decoded crop source image ({bw}x{bh}): {src_path}")
        x0 = max(0, int(round(bx0 * bw)))
        y0 = max(0, int(round(by0 * bh)))
        x1 = min(bw, int(round(bx1 * bw)))
        y1 = min(bh, int(round(by1 * bh)))
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"Invalid crop box [{bx0},{by0},{bx1},{by1}] for {out_name}")

        cropped = _crop_pixmap(pix, x0, y0, x1, y1)
        if item.get("auto_trim", True) is not False:
            cropped = _trim_white_margins(cropped)

        out_file.write_bytes(cropped.tobytes("png"))
        saved.append(out_file)
        print(f"Cropped {out_name} -> {out_file} ({cropped.width}x{cropped.height})")
    return saved


def _analyze_sample_grid(pix: pymupdf.Pixmap) -> tuple[int, bool]:
    """Sample a ~60x60 pixel grid to count distinct 15-bit colors (or 8-bit gray tones) and alpha presence."""
    w, h = pix.width, pix.height
    if w <= 0 or h <= 0:
        return 0, False
    step_x = max(1, int(round(w / 60.0)))
    step_y = max(1, int(round(h / 60.0)))
    color_n = pix.n - pix.alpha
    has_alpha_chan = bool(pix.alpha)
    n = pix.n
    mv = pix.samples_mv

    colors: set[int] = set()
    gray_tones: set[int] = set()
    all_gray = True
    has_alpha = False
    for y in range(0, h, step_y):
        row_off = y * w
        for x in range(0, w, step_x):
            idx = (row_off + x) * n
            r, g, b, a = _decode_pixel_rgb_alpha(mv, idx, color_n, has_alpha_chan)
            if a < 250:
                has_alpha = True
            if all_gray:
                if max(r, g, b) - min(r, g, b) <= 2:
                    gray_tones.add((54 * r + 183 * g + 19 * b) >> 8)
                else:
                    all_gray = False
            q = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
            colors.add(q)
    return (len(gray_tones) if all_gray else len(colors)), has_alpha


def _optimize_image_bytes(
    img_path: Path, quality: int = 95, max_width: int = 1400
) -> tuple[bytes, str, int]:
    """Analyze, resize if wider than `max_width`, and selectively compress one image in memory."""
    pm = ensure_pymupdf()
    assert_safe_image_file(img_path)

    orig_bytes = img_path.read_bytes()
    orig_len = len(orig_bytes)
    orig_mime = "image/jpeg" if img_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

    pix = _ensure_rgb_or_gray(pm.Pixmap(str(img_path)))
    if max(pix.width, pix.height) > MAX_IMAGE_DIM or (pix.width * pix.height) > MAX_IMAGE_PIXELS:
        raise ValueError(f"Refusing oversized decoded image ({pix.width}x{pix.height}): {img_path}")
    distinct_colors, has_alpha = _analyze_sample_grid(pix)
    is_rich_photo = distinct_colors >= 200

    work_pix = pix
    was_resized = False
    if max_width > 0 and pix.width > max_width:
        new_w = max_width
        new_h = max(1, int(round(pix.height * (max_width / float(pix.width)))))
        work_pix = pm.Pixmap(pix, new_w, new_h, None)
        was_resized = True

    if not has_alpha and (is_rich_photo or (was_resized and orig_mime == "image/jpeg")):
        jpg_pix = pm.Pixmap(work_pix, 0) if work_pix.alpha else work_pix
        jpg_bytes = jpg_pix.tobytes("jpeg", jpg_quality=quality)
        if len(jpg_bytes) < orig_len and (was_resized or len(jpg_bytes) <= int(orig_len * 0.85)):
            return jpg_bytes, "image/jpeg", orig_len

    if was_resized and orig_mime == "image/png":
        png_bytes = work_pix.tobytes("png")
        if len(png_bytes) < orig_len:
            return png_bytes, "image/png", orig_len

    return orig_bytes, orig_mime, orig_len
