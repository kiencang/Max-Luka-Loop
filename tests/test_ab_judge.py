"""Scoring logic of the blind A/B judging tool dev/ab_judge.py (standard library only)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "dev"))

import ab_judge  # noqa: E402


class TestDecode(unittest.TestCase):
    def test_sides_are_mapped_through_the_hidden_key(self) -> None:
        items = [{"id": 1, "new_on_left": True}, {"id": 2, "new_on_left": False},
                 {"id": 3, "new_on_left": True}, {"id": 4, "new_on_left": False}]
        res = ab_judge.decode("LLEX", items)
        self.assertEqual(res, {"new_better": [1], "old_better": [2], "equal": [3], "both_bad": [4]})

    def test_length_and_symbol_errors(self) -> None:
        with self.assertRaises(ValueError):
            ab_judge.decode("LL", [{"id": 1, "new_on_left": True}])
        with self.assertRaises(ValueError):
            ab_judge.decode("Q", [{"id": 1, "new_on_left": True}])

    def test_archived_rounds_still_decode_to_their_recorded_results(self) -> None:
        keys = sorted((REPO_ROOT / "dev" / "ab_history").glob("ab_key_*.json"))
        self.assertTrue(keys)
        for kf in keys:
            key = json.loads(kf.read_text(encoding="utf-8"))
            self.assertEqual(ab_judge.decode(key["answers"], key["items"]), key["result"], kf.name)


class TestStatistics(unittest.TestCase):
    def test_sign_test(self) -> None:
        self.assertAlmostEqual(ab_judge.sign_test(9, 1), 22 / 1024, places=6)
        self.assertEqual(ab_judge.sign_test(0, 0), 1.0)
        self.assertEqual(ab_judge.sign_test(5, 5), 1.0)

    def test_wilson_interval(self) -> None:
        lo, hi = ab_judge.wilson(51, 55)
        self.assertAlmostEqual(lo, 0.83, places=2)
        self.assertAlmostEqual(hi, 0.97, places=2)


if __name__ == "__main__":
    unittest.main()
