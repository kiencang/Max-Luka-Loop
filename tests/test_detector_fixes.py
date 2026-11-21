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


if __name__ == "__main__":
    unittest.main()
