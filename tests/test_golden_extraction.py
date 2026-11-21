"""Golden snapshot of figure extraction for every bundled sample PDF (dev-only; needs PyMuPDF).

Guards refactors of figure_detector / manifest code: for each PDF in tests/fixtures and tests/layout_samples
the full manifest.json, the compacted stdout manifest and the SHA-256 of every extracted PNG must match
tests/golden/<pdf stem>.json exactly.

Regenerate only after an intended detection change (review the diff of tests/golden/ before committing):
    $env:MAX_LUKA_UPDATE_GOLDEN='1'; python -m unittest tests.test_golden_extraction
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "tools" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import figure_detector as fd  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
SAMPLE_PDFS = sorted(
    [
        *(REPO_ROOT / "tests" / "fixtures").glob("*.pdf"),
        *(REPO_ROOT / "tests" / "layout_samples").glob("*.pdf"),
    ]
)
_START = "=== MANIFEST JSON START ==="
_END = "=== MANIFEST JSON END ==="


def _snapshot(pdf: Path, out_dir: Path) -> dict:
    buf = StringIO()
    with redirect_stdout(buf):
        fd.extract_images(pdf, out_dir, 180, write_meta=True, stdout_meta=True, detector="heuristic")
    stdout = buf.getvalue()
    start, end = stdout.find(_START), stdout.find(_END)
    if start < 0 or end < 0:
        raise AssertionError(f"No stdout manifest block for {pdf.name}:\n{stdout}")
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    pngs = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out_dir.glob("*.png"))
    }
    return {
        "manifest": manifest,
        "stdout_manifest": json.loads(stdout[start + len(_START) : end]),
        "png_sha256": pngs,
    }


class TestGoldenExtraction(unittest.TestCase):
    def test_sample_pdfs_match_golden_snapshots(self) -> None:
        self.assertGreaterEqual(len(SAMPLE_PDFS), 6, "sample PDFs missing")
        update = os.environ.get("MAX_LUKA_UPDATE_GOLDEN") == "1"
        for pdf in SAMPLE_PDFS:
            with self.subTest(pdf=pdf.name), tempfile.TemporaryDirectory() as tmp:
                actual = _snapshot(pdf, Path(tmp) / "assets")
                golden_path = GOLDEN_DIR / f"{pdf.stem}.json"
                if update:
                    GOLDEN_DIR.mkdir(exist_ok=True)
                    golden_path.write_text(
                        json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
                    )
                    continue
                self.assertTrue(golden_path.is_file(), f"Missing golden file {golden_path}; see module docstring")
                expected = json.loads(golden_path.read_text(encoding="utf-8"))
                self.maxDiff = None
                self.assertEqual(actual, expected, f"Extraction output changed for {pdf.name}")


if __name__ == "__main__":
    unittest.main()
