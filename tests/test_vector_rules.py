"""Unit tests for the Phase 3 vector-cluster rules in figure_detector/vector.py (dev-only; needs PyMuPDF).

Each rule takes a `_ClusterFeatures`; these tests feed hand-built stand-ins, so every rule and its guards
can be checked without building a PDF page. End-to-end behaviour stays covered by test_golden_extraction.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pymupdf

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "tools" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import figure_detector.geometry as geo  # noqa: E402
import figure_detector.vector as vec  # noqa: E402
from figure_detector.model import DetectorConfig, FilterDecision  # noqa: E402

PAGE = pymupdf.Rect(0, 0, 600, 800)


def _features(rect: pymupdf.Rect, **overrides) -> SimpleNamespace:
    """A `_ClusterFeatures` stand-in for an uncaptioned, raster-free, text-free, curve-free cluster."""
    base = dict(
        rect=rect,
        ctx=SimpleNamespace(pw=PAGE.width, ph=PAGE.height, page_rect=PAGE, fig_captions=[], tab_captions=[], text_blocks=[]),
        cfg=DetectorConfig(),
        has_raster=False,
        has_fig_cap=False,
        has_tab_cap=False,
        word_count=0,
        non_tick_word_count=0,
        inside_rects=[],
        inside_drawings=[],
        page_raw_clusters=0,
        has_curves_1=False,
        has_curves_2=False,
        has_curves_12=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _reason(decision: FilterDecision | None) -> str | None:
    return None if decision is None else decision.reason


class TestRuleTable(unittest.TestCase):
    def test_rule_order_is_unchanged(self) -> None:
        # Order decides which reason wins; change it only deliberately (and re-check the golden snapshots).
        self.assertEqual(
            [r.__name__ for r in vec._VECTOR_CLUSTER_RULES],
            [
                "_reject_page_background",
                "_reject_too_small",
                "_reject_edge_ornament",
                "_reject_inner_table_caption",
                "_reject_excessive_words",
                "_reject_uncaptioned_high_words",
                "_reject_table_caption",
                "_reject_pymupdf_table",
                "_reject_prose_box",
                "_reject_trivial_shape",
                "_reject_tall_narrow_column",
                "_reject_ui_text_card",
                "_reject_financial_numeric_table",
                "_reject_hairline_table_grid",
                "_reject_outlined_glyph_confetti",
                "_reject_dense_poster_fragment",
            ],
        )

    def test_first_decision_wins_and_default_is_keep(self) -> None:
        calls: list[str] = []

        def rule(name: str, decision: FilterDecision | None):
            def _r(_f):
                calls.append(name)
                return decision
            return _r

        original = vec._VECTOR_CLUSTER_RULES
        try:
            vec._VECTOR_CLUSTER_RULES = (
                rule("a", None),
                rule("b", FilterDecision(False, "reject:b")),
                rule("c", FilterDecision(False, "reject:c")),
            )
            dec = vec._evaluate_vector_cluster(None, PAGE, [], [], 0)
            self.assertEqual(dec.reason, "reject:b")
            self.assertEqual(calls, ["a", "b"], "rules after the first decision must not run")

            vec._VECTOR_CLUSTER_RULES = (rule("a", None),)
            self.assertEqual(vec._evaluate_vector_cluster(None, PAGE, [], [], 0), FilterDecision(True, "keep:vector_figure"))
        finally:
            vec._VECTOR_CLUSTER_RULES = original

    def test_expensive_features_are_lazy(self) -> None:
        class _NoTextPage:
            def get_text(self, *_a, **_k):
                raise AssertionError("get_text must not run for a cluster rejected by an earlier rule")

        ctx = SimpleNamespace(pw=PAGE.width, ph=PAGE.height, page_rect=PAGE, page=_NoTextPage())
        dec = vec._evaluate_vector_cluster(ctx, pymupdf.Rect(PAGE), [], [], 0)
        self.assertEqual(dec.reason, "reject:page_background")


class TestCountNonGridDetail(unittest.TestCase):
    @staticmethod
    def _curves(n: int, rect: pymupdf.Rect) -> list[dict]:
        p = pymupdf.Point
        items = [("c", p(10, 10), p(12, 14), p(16, 18), p(20, 20)) for _ in range(n)]
        return [{"rect": rect, "items": items}]

    def test_count_is_exact_below_limit_and_capped_at_limit(self) -> None:
        box = pymupdf.Rect(0, 0, 100, 100)
        inner = pymupdf.Rect(5, 5, 50, 50)
        self.assertEqual(geo._count_non_grid_detail(None, box), 0)
        self.assertEqual(geo._count_non_grid_detail(self._curves(5, inner), box, limit=12), 5)
        self.assertEqual(geo._count_non_grid_detail(self._curves(40, inner), box, limit=12), 12)
        outside = pymupdf.Rect(150, 150, 160, 160)
        self.assertEqual(geo._count_non_grid_detail(self._curves(5, outside), box, limit=12), 0)


class TestIndividualRules(unittest.TestCase):
    def test_page_background(self) -> None:
        self.assertEqual(_reason(vec._reject_page_background(_features(pymupdf.Rect(PAGE)))), "reject:page_background")
        self.assertIsNone(vec._reject_page_background(_features(pymupdf.Rect(50, 50, 300, 300))))

    def test_edge_ornament(self) -> None:
        header_logo = pymupdf.Rect(20, 5, 120, 30)
        self.assertEqual(_reason(vec._reject_edge_ornament(_features(header_logo))), "reject:edge_ornament")
        self.assertIsNone(vec._reject_edge_ornament(_features(pymupdf.Rect(100, 300, 300, 330))))

    def test_word_count_limits(self) -> None:
        r = pymupdf.Rect(50, 100, 400, 400)
        cfg = DetectorConfig()
        self.assertEqual(
            _reason(vec._reject_excessive_words(_features(r, non_tick_word_count=cfg.max_vector_words + 1))),
            "reject:excessive_words",
        )
        self.assertIsNone(vec._reject_excessive_words(_features(r, non_tick_word_count=cfg.max_vector_words)))
        over_uncap = cfg.max_uncaptioned_vector_words + 1
        self.assertEqual(
            _reason(vec._reject_uncaptioned_high_words(_features(r, non_tick_word_count=over_uncap))),
            "reject:uncaptioned_high_words",
        )
        self.assertIsNone(
            vec._reject_uncaptioned_high_words(_features(r, non_tick_word_count=over_uncap, has_fig_cap=True)),
            "a figure caption allows more text",
        )

    def test_table_caption_requires_text_and_no_figure_caption(self) -> None:
        r = pymupdf.Rect(50, 100, 400, 400)
        self.assertEqual(
            _reason(vec._reject_table_caption(_features(r, word_count=6, has_tab_cap=True))), "reject:table_caption"
        )
        self.assertIsNone(vec._reject_table_caption(_features(r, word_count=5, has_tab_cap=True)))
        self.assertIsNone(vec._reject_table_caption(_features(r, word_count=6, has_tab_cap=True, has_fig_cap=True)))

    def test_tall_narrow_column(self) -> None:
        column = pymupdf.Rect(10, 100, 60, 600)  # 50 x 500 on a 600 x 800 page
        self.assertEqual(_reason(vec._reject_tall_narrow_column(_features(column))), "reject:tall_narrow_column")
        self.assertIsNone(vec._reject_tall_narrow_column(_features(column, has_raster=True)))
        self.assertIsNone(vec._reject_tall_narrow_column(_features(column, has_fig_cap=True)))
        self.assertIsNone(vec._reject_tall_narrow_column(_features(pymupdf.Rect(10, 100, 200, 600))))

    def test_trivial_shape(self) -> None:
        r = pymupdf.Rect(50, 100, 300, 300)
        two = [pymupdf.Rect(60, 110, 100, 150), pymupdf.Rect(110, 110, 150, 150)]
        self.assertEqual(_reason(vec._reject_trivial_shape(_features(r, inside_rects=two))), "reject:trivial_shape")
        self.assertIsNone(vec._reject_trivial_shape(_features(r, inside_rects=two * 2)))
        self.assertIsNone(vec._reject_trivial_shape(_features(r, inside_rects=two, has_raster=True)))

    def test_hairline_table_grid(self) -> None:
        r = pymupdf.Rect(100, 100, 400, 300)
        h_rules = [pymupdf.Rect(100, y, 400, y + 1) for y in (100, 200, 299)]
        v_rules = [pymupdf.Rect(x, 100, x + 1, 300) for x in (100, 399)]
        grid = h_rules + v_rules
        drawings = [{"rect": x, "fill": None} for x in grid]
        f = _features(r, inside_rects=grid, inside_drawings=drawings)
        self.assertEqual(_reason(vec._reject_hairline_table_grid(f)), "reject:hairline_table_grid")
        thick = grid + [pymupdf.Rect(150, 150, 200, 200)]  # one non-hairline shape (a bar) disqualifies the grid
        self.assertIsNone(vec._reject_hairline_table_grid(_features(r, inside_rects=thick, inside_drawings=drawings)))
        self.assertIsNone(vec._reject_hairline_table_grid(_features(r, inside_rects=grid, has_fig_cap=True)))

    def test_dense_poster_fragment(self) -> None:
        r = pymupdf.Rect(100, 100, 160, 160)  # 3,600 pt^2 < 3% of a 600 x 800 page
        parts = [pymupdf.Rect(100 + i, 100, 110 + i, 110) for i in range(5)]
        f = _features(r, inside_rects=parts, page_raw_clusters=80)
        self.assertEqual(_reason(vec._reject_dense_poster_fragment(f)), "reject:dense_poster_fragment")
        self.assertIsNone(vec._reject_dense_poster_fragment(_features(r, inside_rects=parts, page_raw_clusters=79)))
        self.assertIsNone(
            vec._reject_dense_poster_fragment(_features(r, inside_rects=parts, page_raw_clusters=80, word_count=1))
        )
        big = pymupdf.Rect(100, 100, 300, 300)
        self.assertIsNone(vec._reject_dense_poster_fragment(_features(big, inside_rects=parts, page_raw_clusters=80)))

    def test_outlined_glyph_confetti(self) -> None:
        r = pymupdf.Rect(100, 100, 400, 200)
        glyphs = [pymupdf.Rect(100 + 7 * i, 150, 105 + 7 * i, 157) for i in range(40)]
        drawings = [{"rect": g, "color": None, "fill": (0, 0, 0)} for g in glyphs]
        f = _features(r, inside_rects=glyphs, inside_drawings=drawings)
        self.assertEqual(_reason(vec._reject_outlined_glyph_confetti(f)), "reject:outlined_glyph_confetti")
        stroked = [{"rect": g, "color": (0, 0, 0), "fill": None} for g in glyphs]
        self.assertIsNone(vec._reject_outlined_glyph_confetti(_features(r, inside_rects=glyphs, inside_drawings=stroked)))


if __name__ == "__main__":
    unittest.main()
