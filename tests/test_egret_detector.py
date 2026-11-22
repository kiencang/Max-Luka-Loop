"""Egret ONNX figure detector (`figure_detector/egret.py`, dev-only; PyMuPDF).

- Post-processing and box rules run on synthetic tensors (need numpy only).
- End-to-end checks run when onnxruntime and tools/models/egret_medium.onnx are available
  (build the model with dev/egret/export_onnx.py); otherwise they are skipped.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import pymupdf

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "tools" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import figure_detector as fd  # noqa: E402
from figure_detector import docling_layout as dl  # noqa: E402
from figure_detector import egret  # noqa: E402

HAS_NUMPY = importlib.util.find_spec("numpy") is not None
HAS_ORT = importlib.util.find_spec("onnxruntime") is not None
HAS_MODEL = (REPO_ROOT / "tools" / "models" / egret.MODEL_FILENAME).is_file()


def _logit(p: float) -> float:
    import math

    return math.log(p / (1.0 - p))


def _det(label: int, score: float, box: tuple[float, float, float, float]) -> egret.Detection:
    return egret.Detection(label, score, box)


@unittest.skipUnless(HAS_NUMPY, "numpy not installed")
class TestPostprocess(unittest.TestCase):
    def test_sigmoid_topk_threshold_and_box_scaling(self) -> None:
        import numpy as np

        logits = np.full((1, 300, egret.NUM_CLASSES), -20.0, dtype=np.float32)
        boxes = np.zeros((1, 300, 4), dtype=np.float32)
        logits[0, 5, egret.PICTURE_LABEL] = _logit(0.9)
        boxes[0, 5] = (0.5, 0.25, 0.2, 0.1)  # cx, cy, w, h
        logits[0, 7, egret.TABLE_LABEL] = _logit(0.7)
        boxes[0, 7] = (0.5, 0.75, 1.0, 0.5)
        logits[0, 9, egret.PICTURE_LABEL] = _logit(0.55)  # below threshold 0.6

        dets = egret.postprocess(logits, boxes, 600.0, 800.0, 0.6)
        self.assertEqual([(d.name, round(d.score, 3)) for d in dets], [("Picture", 0.9), ("Table", 0.7)])
        for got, want in zip(dets[0].box, (240.0, 160.0, 360.0, 240.0), strict=True):
            self.assertAlmostEqual(got, want, places=3)
        self.assertEqual(len(egret.postprocess(logits, boxes, 600.0, 800.0, 0.5)), 3)

    def test_one_query_can_yield_several_labels(self) -> None:
        import numpy as np

        logits = np.full((1, 300, egret.NUM_CLASSES), -20.0, dtype=np.float32)
        boxes = np.zeros((1, 300, 4), dtype=np.float32)
        logits[0, 0, egret.PICTURE_LABEL] = _logit(0.8)
        logits[0, 0, egret.TABLE_LABEL] = _logit(0.9)
        dets = egret.postprocess(logits, boxes, 100.0, 100.0, 0.6)
        self.assertEqual([d.label for d in dets], [egret.TABLE_LABEL, egret.PICTURE_LABEL])

    def test_preprocess_layout_and_scale(self) -> None:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 640, 640), False)
        pix.set_rect(pix.irect, (255, 0, 51))
        t = egret.preprocess_pixmap(pix)
        self.assertEqual(t.shape, (1, 3, 640, 640))
        self.assertEqual(str(t.dtype), "float32")
        self.assertAlmostEqual(float(t[0, 0, 10, 10]), 1.0)
        self.assertAlmostEqual(float(t[0, 1, 10, 10]), 0.0)
        self.assertAlmostEqual(float(t[0, 2, 10, 10]), 0.2, places=6)
        with self.assertRaisesRegex(ValueError, "640x640 RGB"):
            egret.preprocess_pixmap(pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 320, 640), False))

    def test_render_page_input_is_exactly_640_square(self) -> None:
        with pymupdf.open() as doc:
            for w, h in ((595, 842), (612, 792), (842, 595), (301, 917)):
                page = doc.new_page(width=w, height=h)
                pix = egret.render_page_input(page)
                self.assertEqual((pix.width, pix.height, pix.n, pix.alpha), (640, 640, 3, 0))


class TestPictureRects(unittest.TestCase):
    PAGE = pymupdf.Rect(0, 0, 600, 800)

    # Rules below mirror docling/utils/layout_postprocessor.py (docling-slim 2.151.1).

    def test_larger_box_wins_its_overlap_group_unless_much_less_confident(self) -> None:
        panel_a = (100, 100, 290, 300)
        panel_b = (310, 100, 500, 300)
        whole = (95, 90, 505, 305)
        # whole only 0.15 below the panels: the larger box wins the group
        dets = [_det(egret.PICTURE_LABEL, 0.95, panel_a), _det(egret.PICTURE_LABEL, 0.94, panel_b),
                _det(egret.PICTURE_LABEL, 0.80, whole)]
        self.assertEqual(egret._picture_rects(dets, self.PAGE), [pymupdf.Rect(whole)])
        # whole 0.45 below: Docling keeps the first (most confident) panel only — one box per overlap group
        dets = [_det(egret.PICTURE_LABEL, 0.95, panel_a), _det(egret.PICTURE_LABEL, 0.94, panel_b),
                _det(egret.PICTURE_LABEL, 0.50, whole)]
        self.assertEqual(egret._picture_rects(dets, self.PAGE), [pymupdf.Rect(panel_a)])

    def test_non_overlapping_panels_stay_separate(self) -> None:
        dets = [_det(egret.PICTURE_LABEL, 0.83, (285, 300, 471, 454)), _det(egret.PICTURE_LABEL, 0.82, (123, 304, 276, 453))]
        self.assertEqual(len(egret._picture_rects(dets, self.PAGE)), 2)

    def test_picture_on_a_table_box_loses_unless_clearly_more_confident(self) -> None:
        box = (40, 135, 292, 260)
        for pic_score, table_score, kept in ((0.54, 0.87, False), (0.80, 0.75, False), (0.90, 0.75, True)):
            dets = [_det(egret.TABLE_LABEL, table_score, box), _det(egret.PICTURE_LABEL, pic_score, box)]
            got = egret._picture_rects(dets, self.PAGE)
            self.assertEqual(got == [pymupdf.Rect(box)], kept, (pic_score, table_score))

    def test_table_cell_images_survive_unless_grouped_with_a_table_shaped_picture(self) -> None:
        table = (40, 135, 292, 260)
        thumb = (45, 140, 90, 180)  # image inside a table cell: small IoU with the table, kept
        dets = [_det(egret.TABLE_LABEL, 0.87, table), _det(egret.PICTURE_LABEL, 0.70, thumb)]
        self.assertEqual(egret._picture_rects(dets, self.PAGE), [pymupdf.Rect(thumb)])
        # Docling resolves picture overlaps before picture/table pairs: the thumbnail joins the group of the
        # table-shaped picture (> 80% inside it), that picture wins the group, then loses to the table.
        dets.insert(1, _det(egret.PICTURE_LABEL, 0.54, table))
        self.assertEqual(egret._picture_rects(dets, self.PAGE), [])

    def test_confidence_thresholds_are_inclusive(self) -> None:
        t = egret.CONFIDENCE_THRESHOLDS["Picture"]
        self.assertEqual(t, 0.5)
        dets = [_det(egret.PICTURE_LABEL, t, (10, 10, 200, 200)), _det(egret.PICTURE_LABEL, t - 0.0016, (300, 10, 500, 200))]
        self.assertEqual(egret._picture_rects(dets, self.PAGE), [pymupdf.Rect(10, 10, 200, 200)])

    def test_page_background_picture_is_dropped(self) -> None:
        dets = [
            _det(egret.PICTURE_LABEL, 0.97, (0, 0, 600, 800)),       # background: 100% of the page
            _det(egret.PICTURE_LABEL, 0.90, (20, 20, 580, 760)),     # 88.7% of the page: still a figure
            _det(egret.PICTURE_LABEL, 0.90, (5, 5, 595, 795)),       # 97.1%: background
        ]
        self.assertEqual(egret._picture_rects(dets, self.PAGE), [pymupdf.Rect(20, 20, 580, 760)])

    def test_other_labels_are_never_pictures(self) -> None:
        dets = [_det(egret.LABELS.index(name), 0.99, (10, 400, 500, 500)) for name in ("Text", "Formula", "Caption")]
        self.assertEqual(egret._picture_rects(dets, self.PAGE), [])


class TestDoclingLayout(unittest.TestCase):
    """Reading order and relations ported from Docling (`figure_detector/docling_layout.py`)."""

    PAGE = pymupdf.Rect(0, 0, 600, 800)

    @staticmethod
    def _lines(*specs: tuple[tuple[float, float, float, float], str]) -> list:
        return [dl.TextCell(i, pymupdf.Rect(box), text) for i, (box, text) in enumerate(specs)]

    def _relations(self, dets, cells):
        layout = dl.postprocess_layout(dets, cells, self.PAGE)
        ordered = dl.reading_order(layout, self.PAGE)
        caps = dl.match_captions(ordered)
        labels = [layout.clusters[n.cid].label for n in ordered]
        captions = {layout.clusters[g].label + str(round(layout.clusters[g].rect.y0)): layout.clusters[c].text
                    for g, c in caps.items()}
        return layout, ordered, labels, captions

    def test_caption_below_or_above_its_picture(self) -> None:
        cells = self._lines(((60, 80, 540, 92), "Intro text line"), ((60, 330, 300, 342), "Figure 1: Below the plot."),
                            ((60, 360, 300, 372), "Table 1: Above the table."), ((60, 600, 540, 612), "Body text"))
        dets = [
            _det(egret.LABELS.index("Text"), 0.9, (60, 80, 540, 92)),
            _det(egret.PICTURE_LABEL, 0.9, (60, 100, 540, 320)),
            _det(egret.LABELS.index("Caption"), 0.9, (60, 330, 300, 342)),
            _det(egret.LABELS.index("Caption"), 0.9, (60, 360, 300, 372)),
            _det(egret.TABLE_LABEL, 0.9, (60, 380, 540, 590)),
            _det(egret.LABELS.index("Text"), 0.9, (60, 600, 540, 612)),
        ]
        _, _, labels, captions = self._relations(dets, cells)
        self.assertEqual(labels, ["Text", "Picture", "Caption", "Caption", "Table", "Text"])
        self.assertEqual(captions, {"Picture100": "Figure 1: Below the plot.", "Table380": "Table 1: Above the table."})

    def test_a_caption_owns_one_graphic_and_prose_breaks_the_run(self) -> None:
        # Two panels side by side above one caption: Docling links the caption to one of them only.
        cells = self._lines(((60, 330, 540, 342), "Figure 2: Two panels."), ((60, 400, 540, 412), "Prose in between."),
                            ((60, 640, 540, 652), "Figure 3: Far away."))
        dets = [
            _det(egret.PICTURE_LABEL, 0.9, (60, 100, 290, 320)),
            _det(egret.PICTURE_LABEL, 0.9, (310, 100, 540, 320)),
            _det(egret.LABELS.index("Caption"), 0.9, (60, 330, 540, 342)),
            _det(egret.LABELS.index("Text"), 0.9, (60, 400, 540, 412)),
            _det(egret.PICTURE_LABEL, 0.9, (60, 420, 540, 630)),
            _det(egret.LABELS.index("Caption"), 0.9, (60, 640, 540, 652)),
        ]
        layout, _, _, captions = self._relations(dets, cells)
        self.assertEqual(sorted(captions.values()), ["Figure 2: Two panels.", "Figure 3: Far away."])
        self.assertEqual(sum(1 for t in captions.values() if t.startswith("Figure 2")), 1)

    def test_caption_without_alternative_displaces_one_that_has(self) -> None:
        # Picture A, caption X, picture B, caption Y in one column: X could take A or B, Y only B.
        cells = self._lines(((60, 230, 540, 242), "Caption X"), ((60, 470, 540, 482), "Caption Y"))
        dets = [
            _det(egret.PICTURE_LABEL, 0.9, (60, 100, 540, 220)),
            _det(egret.LABELS.index("Caption"), 0.9, (60, 230, 540, 242)),
            _det(egret.PICTURE_LABEL, 0.9, (60, 245, 540, 460)),
            _det(egret.LABELS.index("Caption"), 0.9, (60, 470, 540, 482)),
        ]
        _, _, _, captions = self._relations(dets, cells)
        self.assertEqual(captions, {"Picture100": "Caption X", "Picture245": "Caption Y"})

    def test_two_columns_are_read_column_by_column(self) -> None:
        cells = self._lines(((60, 80, 280, 92), "L1"), ((60, 100, 280, 112), "L2"),
                            ((320, 80, 540, 92), "R1"), ((320, 100, 540, 112), "R2"))
        dets = [_det(egret.LABELS.index("Text"), 0.9, tuple(c.rect)) for c in cells]
        layout, ordered, _, _ = self._relations(dets, cells)
        self.assertEqual([layout.clusters[n.cid].text for n in ordered], ["L1", "L2", "R1", "R2"])

    def test_orphan_text_between_picture_and_caption_breaks_the_link(self) -> None:
        cells = self._lines(((60, 325, 540, 337), "stray line"), ((60, 345, 540, 357), "Figure 4: Caption."))
        dets = [_det(egret.PICTURE_LABEL, 0.9, (60, 100, 540, 320)), _det(egret.LABELS.index("Caption"), 0.9, (60, 345, 540, 357))]
        layout, _, labels, captions = self._relations(dets, cells)
        self.assertEqual(labels, ["Picture", "Text", "Caption"])  # the unlabelled line becomes an orphan Text cluster
        self.assertEqual(captions, {})

    def test_footnote_and_table_gate(self) -> None:
        cells = self._lines(((60, 325, 540, 337), "* footnote"),)
        dets = [
            _det(egret.TABLE_LABEL, 0.9, (40, 380, 560, 700)),
            _det(egret.PICTURE_LABEL, 0.9, (60, 100, 540, 320)),
            _det(egret.LABELS.index("Footnote"), 0.9, (60, 325, 540, 337)),
            _det(egret.PICTURE_LABEL, 0.9, (50, 400, 150, 480)),   # fully inside the table
            _det(egret.PICTURE_LABEL, 0.9, (500, 650, 590, 760)),  # only ~44% inside
        ]
        layout = dl.postprocess_layout(dets, cells, self.PAGE)
        ordered = dl.reading_order(layout, self.PAGE)
        foot = dl.match_footnotes(ordered)
        pics = {round(c.rect.y0): cid for cid, c in enumerate(layout.clusters) if c.label == "Picture"}
        self.assertIn(pics[100], foot)
        self.assertIsNotNone(dl.inside_table(layout.clusters[pics[400]], layout))
        self.assertIsNone(dl.inside_table(layout.clusters[pics[650]], layout))

    def test_text_is_joined_like_docling(self) -> None:
        self.assertEqual(dl.sanitize_text(["Figure 1: algo-", "rithms for n-", "octanal ﬁ eld"]),
                         "Figure 1: algorithms for n-octanal field")
        self.assertEqual(dl.sanitize_text(["value -", "x", "6-methyl-", "5-hepten"]), "value - x 6-methyl-5-hepten")
        self.assertEqual(dl.normalize_extracted_text("“q” ’"), "\"q\" '")


class TestModelLoading(unittest.TestCase):
    def test_missing_model_fails_with_build_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, "export_onnx.py"):
                egret.load_session(Path(tmp) / "missing.onnx")

    def test_unknown_detector_is_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "a.pdf"
            with pymupdf.open() as doc:
                doc.new_page()
                doc.save(pdf)
            out = Path(tmp) / "out"
            with self.assertRaisesRegex(ValueError, "detector must be one of"):
                fd.extract_images(pdf, out, 180, detector="yolo")
            self.assertFalse(out.exists())

    def test_egret_is_the_default_and_a_broken_install_stops_extraction(self) -> None:
        """No fallback: a missing model must raise before any PNG or manifest is written."""
        from unittest import mock

        missing = FileNotFoundError("Egret ONNX model not found: x.onnx")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(egret, "load_session", side_effect=missing):
            pdf = Path(tmp) / "a.pdf"
            with pymupdf.open() as doc:
                doc.new_page()
                doc.save(pdf)
            buf = io.StringIO()
            with redirect_stdout(buf), self.assertRaisesRegex(FileNotFoundError, "Egret ONNX model not found"):
                fd.extract_images(pdf, Path(tmp) / "out", 180, write_meta=True)  # default detector
            self.assertFalse((Path(tmp) / "out").exists())
            self.assertNotIn("heuristic", buf.getvalue())

    def test_missing_onnxruntime_is_reported_as_runtime_error(self) -> None:
        import builtins
        from unittest import mock

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "onnxruntime":
                raise ImportError("DLL load failed")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "m.onnx"
            model.write_bytes(b"x")
            with mock.patch("builtins.__import__", side_effect=fake_import):
                with self.assertRaisesRegex(RuntimeError, "onnxruntime is missing or broken"):
                    egret.load_session(model)

    @unittest.skipUnless(HAS_ORT, "onnxruntime not installed")
    def test_corrupt_model_is_reported_with_a_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "m.onnx"
            model.write_bytes(b"not an onnx model")
            with self.assertRaisesRegex(RuntimeError, "Egret model could not be loaded .*re-extract the release package"):
                egret.load_session(model)


@unittest.skipUnless(HAS_NUMPY and HAS_ORT and HAS_MODEL, "onnxruntime or tools/models/egret_medium.onnx missing")
class TestEgretEndToEnd(unittest.TestCase):
    def _extract(self, pdf: Path, tmp: str) -> dict:
        with redirect_stdout(io.StringIO()):
            fd.extract_images(pdf, Path(tmp) / "assets", 180, write_meta=True, detector="egret")
        return json.loads((Path(tmp) / "assets" / "manifest.json").read_text(encoding="utf-8"))

    def test_scanned_pages_get_raster_crops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            man = self._extract(REPO_ROOT / "tests" / "fixtures" / "synthetic_scanned_memo.pdf", tmp)
        self.assertEqual(man["detector"], "egret")
        self.assertGreaterEqual(len(man["figures"]), 2)
        self.assertEqual({f["source"] for f in man["figures"]}, {"raster"})
        self.assertEqual(man["scanned_pages"], [])

    def test_panels_follow_docling_and_reading_order(self) -> None:
        # The whole-figure box of Figure 2 scores 0.4984 < 0.5, so (as in Docling) its two panels stay separate
        # images; Docling links a caption to one graphic only, so one panel carries "Figure 2" and the other none.
        # Figures are numbered top-to-bottom, left-to-right.
        with tempfile.TemporaryDirectory() as tmp:
            man = self._extract(REPO_ROOT / "tests" / "layout_samples" / "journal_2col_academic.pdf", tmp)
        p3 = [f for f in man["figures"] if f["page"] == 3 and f["placement"] == "figure"]
        self.assertEqual(sorted((f["caption"] or "")[:8] for f in p3), ["", "Figure 2", "Figure 3"], p3)
        tops = [(f["page"], f["box"][1], f["box"][0]) for f in man["figures"]]
        self.assertEqual(tops, sorted(tops), "Docling tblr order: page, then top, then left")

    def test_table_is_not_embedded_as_picture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            man = self._extract(REPO_ROOT / "tests" / "layout_samples" / "executive_magazine_mixed.pdf", tmp)
        p2 = [f for f in man["figures"] if f["page"] == 2]
        self.assertEqual(len(p2), 1, p2)
        self.assertGreaterEqual(p2[0]["box"][1], 0.33, "the box must start below the two tables")


if __name__ == "__main__":
    unittest.main()
