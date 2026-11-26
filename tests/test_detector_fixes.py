"""Regression tests for raster white-margin trimming and line-level axis-label attachment (dev-only; PyMuPDF).

Both fixes came from the DocLayNet severity evaluation (dev/eval_doclaynet.py): extracted images that swallowed
nearby text through an embedded image's white border, and plots whose axis titles were cut off.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pymupdf

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "tools" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import figure_detector as fd  # noqa: E402

BODY = 10.0


def _png_with_white_margin(w: int, h: int, ink: tuple[int, int, int, int]) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    pix.set_rect(pymupdf.IRect(*ink), (30, 90, 160))
    return pix.tobytes("png")


def _paragraph(page: pymupdf.Page, y: float, lines: int, x0: float = 72.0) -> float:
    text = "The measured response follows the expected trend across all sampled operating conditions here"
    for i in range(lines):
        page.insert_text((x0, y + i * 13), text, fontsize=BODY)
    return y + lines * 13


class TestRasterWhiteMarginTrim(unittest.TestCase):
    def test_text_over_white_border_is_not_swallowed_but_overlaid_labels_are_kept(self) -> None:
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        _paragraph(page, 90, 3)
        # Placement box 72..540 x 120..420, but the image content only fills ~ 180..430 x 170..340 (page space)
        page.insert_image(pymupdf.Rect(72, 120, 540, 420), stream=_png_with_white_margin(936, 600, (216, 100, 716, 440)))
        page.insert_text((80, 135), "Body text sitting over the white border of the image", fontsize=BODY)
        page.insert_text((300, 352), "Time (s)", fontsize=8)  # axis title printed over the bottom white margin
        page.insert_text((72, 440), "Figure 1: Response of the sensor array under load.", fontsize=BODY)
        _paragraph(page, 470, 4)

        rects, _ = fd.collect_page_figures(page)
        self.assertEqual(len(rects), 1, rects)
        box = rects[0]
        self.assertGreater(box.y0, 140, f"image must not extend over the body text line at y=135: {box}")
        self.assertLess(box.x0, 185)
        self.assertGreater(box.x1, 425)
        self.assertGreaterEqual(box.y1, 353, f"axis title printed over the trimmed margin must be kept: {box}")
        self.assertLess(box.y1, 425)


    def test_image_decode_errors_fall_back_to_the_placement_box(self) -> None:
        # Real PDFs carry soft masks of a different size or images that already have alpha; PyMuPDF raises its own
        # exception types for those. Trimming is optional, so any failure must keep the original box, not crash.
        from unittest import mock

        import figure_detector.raster as raster

        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        _paragraph(page, 90, 3)
        page.insert_image(pymupdf.Rect(72, 120, 540, 420), stream=_png_with_white_margin(936, 600, (216, 100, 716, 440)))
        page.insert_text((72, 440), "Figure 1: Response of the sensor array under load.", fontsize=BODY)

        class FzLikeError(Exception):
            pass

        fd._ensure_pymupdf()
        with mock.patch.object(raster.pymupdf, "Pixmap", side_effect=FzLikeError("mask size mismatch")):
            rects, _ = fd.collect_page_figures(page)
        self.assertEqual(len(rects), 1)
        self.assertAlmostEqual(rects[0].y0, 120, delta=1)


class TestAxisLabelLineAttachment(unittest.TestCase):
    def _plot_page(self) -> tuple[pymupdf.Page, pymupdf.Rect]:
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 150), "Results Overview", fontsize=16)  # heading, set larger than body text
        page.insert_text((72, 176), "end of a sentence.", fontsize=BODY)  # tail of a paragraph above the figure
        frame = pymupdf.Rect(170, 210, 470, 420)
        shape = page.new_shape()
        shape.draw_rect(frame)
        pts = [pymupdf.Point(frame.x0 + i * 15, frame.y1 - 10 - (i * i) % 170) for i in range(21)]
        shape.draw_polyline(pts)
        for i in range(12):  # curved markers so the cluster reads as a plot
            c = pymupdf.Point(frame.x0 + 20 + i * 22, frame.y0 + 40 + (i % 4) * 30)
            shape.draw_circle(c, 3)
        shape.finish(color=(0, 0, 0), width=0.8)
        shape.commit()
        for i, x in enumerate(range(170, 471, 60)):  # x tick labels just below the frame
            page.insert_text((x - 4, 432), str(i), fontsize=8)
        page.insert_text((280, 456), "Elapsed time (minutes)", fontsize=9)  # x-axis title ~22 pt below the ticks row
        page.insert_text((150, 380), "Normalised signal", fontsize=9, rotate=90)  # y title 20+ pt left of frame
        page.insert_text((72, 490), "Figure 2: Normalised signal against elapsed time for all runs.", fontsize=BODY)
        _paragraph(page, 520, 5)
        return page, frame

    def test_axis_titles_beyond_the_old_16pt_reach_are_attached(self) -> None:
        page, frame = self._plot_page()
        rects, _ = fd.collect_page_figures(page)
        self.assertEqual(len(rects), 1, rects)
        box = rects[0]
        self.assertGreaterEqual(box.y1, 455, f"x-axis title must be inside the image: {box}")
        self.assertLessEqual(box.x0, 150, f"rotated y-axis title must be inside the image: {box}")
        self.assertLess(box.y1, 480, f"caption must stay outside: {box}")

    def test_heading_and_paragraph_tail_above_the_figure_stay_outside(self) -> None:
        page, frame = self._plot_page()
        box = fd.collect_page_figures(page)[0][0]
        self.assertGreater(box.y0, 180, f"heading / sentence tail above the plot must not be attached: {box}")


class TestPdfBombLimits(unittest.TestCase):
    """Page-tree and figure-count bombs fail fast. Uses the heuristic detector so the ONNX model is not needed;
    the caps sit in `extract_images` itself, shared by both detectors (test_powershell.ps1 covers the Egret exe)."""

    def test_page_limit_and_figure_limit_fail_fast_and_allow_dev_zero_override(self) -> None:
        import shutil
        import tempfile
        from unittest import mock

        import figure_detector.extract as ext
        import image_ops as iops

        self.assertEqual(iops.MAX_PDF_PAGES, 300)
        self.assertEqual(iops.MAX_EXTRACTED_FIGURES, 1000)

        tmp = Path(tempfile.mkdtemp(prefix="max_luka_bomb_"))
        self.addCleanup(shutil.rmtree, tmp, True)

        # Build a 301-page PDF; page 301 has one small raster figure.
        over_pdf = tmp / "p301.pdf"
        doc = pymupdf.open()
        for _ in range(300):
            doc.new_page(width=200, height=200)
        last = doc.new_page(width=300, height=300)
        last.insert_image(pymupdf.Rect(40, 40, 200, 200), stream=_png_with_white_margin(160, 160, (10, 10, 150, 150)))
        last.insert_text((40, 220), "Figure 1: Tail image.", fontsize=BODY)
        doc.save(over_pdf)
        doc.close()

        # 1. Default 300-page limit rejects a 301-page PDF before analysing any page or creating out_dir.
        out_301 = tmp / "out_301"
        with mock.patch.object(ext, "_run_page_pipeline", side_effect=AssertionError("must reject before pages")):
            with self.assertRaisesRegex(ValueError, "301 pages, exceeding the 300-page safety limit"):
                ext.extract_images(over_pdf, out_301, detector="heuristic")
        self.assertFalse(out_301.exists(), "rejected PDF must not create output directory")

        pages_301 = tmp / "pages_301"
        with self.assertRaisesRegex(ValueError, "301 pages, exceeding the 300-page safety limit"):
            iops.render_pages(over_pdf, pages_301, pages="1")
        self.assertFalse(pages_301.exists(), "rejected render_pages must not create output directory")

        # Boundary: exactly 300 pages is accepted.
        ok_300 = tmp / "p300.pdf"
        with pymupdf.open(over_pdf) as d:
            d.delete_page(300)
            d.save(ok_300)
        self.assertEqual(ext.extract_images(ok_300, tmp / "out_300", detector="heuristic"), [])

        # Dev override: max_pages=0 lifts the page cap.
        dev_saved = ext.extract_images(over_pdf, tmp / "out_dev", dpi=72, detector="heuristic", max_pages=0)
        self.assertEqual(len(dev_saved), 1)
        self.assertEqual(len(iops.render_pages(over_pdf, tmp / "pages_dev", scale=1.0, pages="301", max_pages=0)), 1)

        # 2. Figure-count limit aborts cleanly, removes partial PNGs & the newly created dir, and skips manifest.json.
        many_figs_pdf = tmp / "four_figs.pdf"
        doc2 = pymupdf.open()
        img_bytes = _png_with_white_margin(160, 160, (10, 10, 150, 150))
        for p_idx in range(4):
            pg = doc2.new_page(width=300, height=300)
            pg.insert_image(pymupdf.Rect(40, 40, 200, 200), stream=img_bytes)
            pg.insert_text((40, 220), f"Figure {p_idx + 1}: Repeated image.", fontsize=BODY)
        doc2.save(many_figs_pdf)
        doc2.close()

        capped_out = tmp / "capped_figs"
        with self.assertRaisesRegex(ValueError, "3-figure extraction safety limit"):
            ext.extract_images(
                many_figs_pdf, capped_out, dpi=72, write_meta=True, detector="heuristic", max_figures=3
            )
        self.assertFalse(capped_out.exists(), "partial PNGs and newly created empty directory must be cleaned up")

        # Dev override: max_figures=0 extracts all 4 figures.
        unlimited_out = tmp / "unlimited_figs"
        saved = ext.extract_images(many_figs_pdf, unlimited_out, dpi=72, detector="heuristic", max_figures=0)
        self.assertEqual(len(saved), 4)


if __name__ == "__main__":
    unittest.main()
