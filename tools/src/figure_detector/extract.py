"""Phase 6 — render detected figures to PNG and build manifest entries (`extract_images()`)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from image_ops import (
    MAX_EXTRACTED_FIGURES,
    MAX_PDF_PAGES,
    MAX_RENDER_DIM,
    MAX_RENDER_PIXELS,
    compute_safe_render_zoom,
)
from manifest import emit_compacted_manifest_stdout
from path_guards import assert_local_no_unc_path, is_reparse_point, resolve_safe_out_directory

from .caption_match import (
    _is_table_row_pair,
    _row_aligned_text_indices,
)
from .geometry import (
    _horiz_overlap,
    _rect_gap,
)
from .model import (
    CandidateBox,
    PageContext,
    TextBlock,
    _ensure_pymupdf,
    pymupdf,
)
from .pipeline import (
    _run_page_pipeline,
)
from .text import (
    _clean_text,
)

DETECTORS = ("egret", "heuristic")
# Margin added around each box when cropping the PNG (PDF points per side). Egret follows Docling, which crops
# the picture box exactly (standard_pdf_pipeline.py: `page.image.crop(bbox)`); the legacy rule-based detector keeps
# its historical 4 pt so its regression snapshots stay valid.
CROP_PAD_PT = {"egret": 0.0, "heuristic": 4.0}


def _select_detector(detector: str):
    """Return the per-page runner; loads the Egret session up front so a broken install fails before any output."""
    if detector == "egret":
        from .egret import load_session, run_page_egret

        session = load_session()

        def run_page(page: pymupdf.Page):
            return run_page_egret(page, session=session)

        return run_page
    return _run_page_pipeline


def _extract_context_snippet(rect: pymupdf.Rect, text_blocks: list[TextBlock]) -> str | None:
    """Find concise nearby row or paragraph text when a figure has no explicit caption."""
    row_indices = _row_aligned_text_indices(rect, text_blocks, max_gap_x=120.0)
    if row_indices:
        joined = " | ".join(_clean_text(text_blocks[i].text) for i in row_indices)
        return joined[:220]

    best_tb: TextBlock | None = None
    best_gap = float("inf")
    for tb in text_blocks:
        gap = _rect_gap(rect, tb.rect)
        if gap < best_gap and gap <= 65.0 and tb.word_count >= 2:
            best_gap = gap
            best_tb = tb
    if best_tb is not None:
        return _clean_text(best_tb.text)[:220]
    return None


def _detect_table_placement(
    candidates: list[CandidateBox],
    idx: int,
    ctx: PageContext,
    table_bboxes: list[pymupdf.Rect],
) -> str:
    """Classify uncaptioned candidate as 'table_cell' or standalone 'figure'."""
    cand = candidates[idx]
    if cand.caption_idx is not None:
        return "figure"

    bb = cand.rect
    bb_area = max(1.0, bb.get_area())
    if any((bb & tb_rect).get_area() >= 0.65 * bb_area for tb_rect in table_bboxes):
        return "table_cell"

    row_indices = _row_aligned_text_indices(bb, ctx.text_blocks, max_gap_x=120.0)
    if len(row_indices) >= 2:
        return "table_cell"
    if len(row_indices) == 1 and ctx.text_blocks[row_indices[0]].word_count <= 25:
        if any(i != idx and _is_table_row_pair(bb, other.rect, ctx.text_blocks) for i, other in enumerate(candidates)):
            return "table_cell"
        row_span = bb | ctx.text_blocks[row_indices[0]].rect
        for tb in ctx.tab_captions:
            if 0.0 <= bb.y0 - tb.rect.y1 <= 55.0 and _horiz_overlap(tb.rect, row_span) >= 40.0:
                return "table_cell"

    return "figure"


def fill_heuristic_metadata(candidates: list[CandidateBox], ctx: PageContext) -> None:
    """Legacy heuristic detector only: caption text, placement and context from its own text rules.
    (Egret fills these fields from Docling's layout and reading order in `egret.run_page_egret`.)"""
    table_bboxes = [t.rect for t in ctx.get_page_tables()] if any(c.caption_idx is None for c in candidates) else []
    for idx, cand in enumerate(candidates):
        cand.caption_text = (
            _clean_text(ctx.fig_captions[cand.caption_idx].text) if cand.caption_idx is not None else None
        )
        cand.context = None if cand.caption_text is not None else _extract_context_snippet(cand.rect, ctx.text_blocks)
        cand.placement = _detect_table_placement(candidates, idx, ctx, table_bboxes)


def _normalize_box(bb: pymupdf.Rect, page_rect: pymupdf.Rect) -> list[float]:
    """Normalize `bb` onto [0.0, 1.0] relative to `page_rect` (handles CropBox offsets)."""
    pw = max(1.0, float(page_rect.width))
    ph = max(1.0, float(page_rect.height))

    def _norm(val: float, origin: float, span: float) -> float:
        return round(max(0.0, min(1.0, (val - origin) / span)), 3)

    return [
        _norm(bb.x0, page_rect.x0, pw),
        _norm(bb.y0, page_rect.y0, ph),
        _norm(bb.x1, page_rect.x0, pw),
        _norm(bb.y1, page_rect.y0, ph),
    ]


def _discard_partial_extracted(saved: list[Path], out_dir: Path, created_out_dir: bool) -> None:
    """Remove partial PNGs (and a newly created empty `out_dir`) when extraction aborts on a safety cap."""
    for p in saved:
        try:
            if os.path.lexists(p) and not is_reparse_point(p) and os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    if created_out_dir:
        try:
            out_dir.rmdir()
        except OSError:
            pass


def extract_images(
    pdf_path: Path,
    out_dir: Path,
    dpi: int = 180,
    write_meta: bool = False,
    stdout_meta: bool = False,
    max_meta_words: int = 20,
    max_meta_bytes: int = 16384,
    detector: str = "egret",
    *,
    max_pages: int = MAX_PDF_PAGES,
    max_figures: int = MAX_EXTRACTED_FIGURES,
) -> list[Path]:
    """Phase 6: Render every detected bitmap or vector figure region in `pdf_path` to PNG.

    `detector` picks how Phases 2–5 find figure boxes. "egret" (Egret Medium layout model via onnxruntime,
    see `egret.py`) is what the product uses: the CLI offers no other choice, and any failure to load or
    run the model stops extraction with an error — there is deliberately no fallback. "heuristic" (the
    former PyMuPDF geometry rules) stays reachable from Python only, for regression tests and dev tools.
    """
    _ensure_pymupdf()
    assert_local_no_unc_path(pdf_path, "ResolvedPdf")
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if dpi < 36 or dpi > 1200:
        raise ValueError(f"dpi must be between 36 and 1200 (got {dpi})")
    if detector not in DETECTORS:
        raise ValueError(f"detector must be one of {', '.join(DETECTORS)} (got {detector})")
    run_page = _select_detector(detector)

    safe_out_dir = resolve_safe_out_directory(out_dir, "-OutDir", create=False)
    saved: list[Path] = []
    scanned_pages: list[int] = []
    manifest_items: list[dict] = []

    with pymupdf.open(pdf_path) as doc:
        if doc.needs_pass:
            raise RuntimeError(f"PDF is password-protected/encrypted and cannot be extracted: {pdf_path}")

        total_pages = len(doc)
        if max_pages > 0 and total_pages > max_pages:
            raise ValueError(
                f"PDF has {total_pages:,} pages, exceeding the {max_pages:,}-page safety limit: {pdf_path} "
                f"(split the PDF into smaller parts/chapters before translating)."
            )

        created_out_dir = not safe_out_dir.exists()
        safe_out_dir.mkdir(parents=True, exist_ok=True)

        for pno, page in enumerate(doc, 1):
            ctx, candidates, is_scanned = run_page(page)
            if is_scanned:
                scanned_pages.append(pno)
            if write_meta and detector == "heuristic":
                fill_heuristic_metadata(candidates, ctx)

            for idx0, cand in enumerate(candidates):
                idx = idx0 + 1
                bb = cand.rect
                pad = CROP_PAD_PT[detector]
                clip = pymupdf.Rect(bb.x0 - pad, bb.y0 - pad, bb.x1 + pad, bb.y1 + pad) & ctx.page_rect
                if clip.is_empty:
                    continue
                if max_figures > 0 and len(saved) >= max_figures:
                    _discard_partial_extracted(saved, safe_out_dir, created_out_dir)
                    raise ValueError(
                        f"PDF exceeded the {max_figures:,}-figure extraction safety limit on page {pno}/{total_pages}: "
                        f"{pdf_path} (split the PDF into smaller parts/chapters before translating)."
                    )
                out_name = f"fig_p{pno}_{idx}.png"
                out_path = safe_out_dir / out_name
                desired_zoom = dpi / 72.0
                safe_zoom, was_clamped = compute_safe_render_zoom(clip.width, clip.height, desired_zoom)
                if was_clamped:
                    print(
                        f"WARNING: Clamped {out_name} render DPI ({dpi} -> {int(round(safe_zoom * 72.0))}) "
                        f"to stay within {MAX_RENDER_DIM}px / {MAX_RENDER_PIXELS:,}px safety limit.",
                        file=sys.stderr,
                    )
                pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(safe_zoom, safe_zoom))
                pix.save(out_path)
                saved.append(out_path)

                if write_meta:
                    manifest_items.append(
                        {
                            "file": out_name,
                            "page": pno,
                            "source": cand.source,
                            "drawings": cand.drawings,
                            "placement": cand.placement,
                            "box": _normalize_box(bb, ctx.page_rect),
                            "width_px": pix.width,
                            "height_px": pix.height,
                            "caption": cand.caption_text,
                            "context": cand.context,
                        }
                    )

    print(f"Extracted {len(saved)} figures -> {safe_out_dir}")
    if scanned_pages:
        print(f"[Note] Detected {len(scanned_pages)} scanned/full-page image page(s): {scanned_pages}")
    if write_meta:
        meta_path = safe_out_dir / "manifest.json"
        safe_pdf_name = re.sub(r"[\x00-\x1F\x7F]+", " ", pdf_path.name).strip()
        meta = {
            "pdf": safe_pdf_name,
            "dpi": dpi,
            "total_pages": total_pages,
            "scanned_pages": scanned_pages,
            "figures": manifest_items,
        }
        if detector != "heuristic":
            meta["detector"] = detector
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote manifest -> {meta_path}")
        if stdout_meta:
            emit_compacted_manifest_stdout(
                meta,
                meta_path,
                max_words=max_meta_words,
                max_bytes=max_meta_bytes,
            )
    return saved
