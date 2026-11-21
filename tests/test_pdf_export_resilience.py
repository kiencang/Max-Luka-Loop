"""PDF export failure handling for packager + pdf_export (dev-only; stdlib unittest, no PyMuPDF/Edge required).

A fake headless browser stands in for Edge/Chrome so timeout, empty-PDF and success paths are deterministic.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "tools" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import output_paths  # noqa: E402
import packager as pkg  # noqa: E402
import pdf_export as pdfx  # noqa: E402

_DRAFT_HTML = (
    "<!DOCTYPE html><html lang='vi'><head><meta charset='UTF-8'><title>T</title></head>"
    "<body><h1 id='top'>Tiêu đề</h1><p><a href='#top'>Lên đầu</a></p></body></html>"
)


class _FakeBrowser:
    """Minimal stand-in for subprocess.Popen driven by a behaviour name."""

    calls: list[list[str]] = []
    behaviour = "ok"

    def __init__(self, cmd: list[str], stdout=None, stderr=None) -> None:
        type(self).calls.append(list(cmd))
        self.pid = 4294967
        self.returncode: int | None = None
        out_arg = next(a for a in cmd if a.startswith("--print-to-pdf="))
        self._pdf = Path(out_arg.split("=", 1)[1])
        if stderr is not None:
            stderr.write(b"fake browser log line")

    def wait(self, timeout: float | None = None) -> int:
        b = type(self).behaviour
        if b == "ok":
            self._pdf.write_bytes(b"%PDF-1.4\n%fake\n")
            self.returncode = 0
        elif b == "empty":
            self._pdf.write_bytes(b"")
            self.returncode = 1
        elif b == "hang":
            if self.returncode is None and timeout is not None and timeout > 5:
                self._pdf.write_bytes(b"%PDF-1.4\npartial")
                raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
            self.returncode = -9
        return self.returncode or 0

    def kill(self) -> None:
        self.returncode = -9


class TestPdfExportResilience(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.work = self.tmp / "work"
        self.out = self.tmp / "output"
        self.work.mkdir()
        self.out.mkdir()
        self.draft = self.work / "draft.html"
        self.draft.write_text(_DRAFT_HTML, encoding="utf-8")
        self._prev_cwd = os.getcwd()
        os.chdir(self.tmp)
        _FakeBrowser.calls = []
        fake_exe = self.tmp / "fake_browser.exe"
        fake_exe.write_bytes(b"")
        self._patches = [
            mock.patch.object(pdfx, "find_headless_browser", return_value=str(fake_exe)),
            mock.patch.object(pdfx.subprocess, "Popen", _FakeBrowser),
            mock.patch.object(pdfx.subprocess, "run", return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        os.chdir(self._prev_cwd)
        self._tmp_ctx.cleanup()

    def _package(self) -> tuple[Path, Path | None, str]:
        buf = StringIO()
        with redirect_stdout(buf):
            html, pdf = pkg.embed_images_and_package(
                html_path=self.draft,
                optimize_image_bytes_fn=lambda *_a: (_ for _ in ()).throw(AssertionError("no images expected")),
                out_html_path=str(self.out / "doc_vi.html"),
                also_pdf=True,
                clean_dir="work",
                timeout_seconds=6,
            )
        return html, pdf, buf.getvalue()

    def test_success_uses_7s_virtual_time_budget(self) -> None:
        _FakeBrowser.behaviour = "ok"
        html, pdf, log = self._package()
        self.assertEqual(pdf, self.out / "doc_vi.pdf")
        self.assertTrue(pdf.is_file())
        self.assertIn("Exported PDF ->", log)
        self.assertFalse(self.work.exists())
        self.assertEqual(pdfx.HEADLESS_VIRTUAL_TIME_BUDGET_MS, 7000)
        self.assertIn("--virtual-time-budget=7000", _FakeBrowser.calls[0])

    def _assert_degraded_to_html_only(self, html: Path, pdf: Path | None, log: str) -> None:
        self.assertIsNone(pdf)
        self.assertEqual(html, self.out / "doc_vi.html")
        self.assertTrue(html.is_file())
        self.assertIn("WARNING: PDF export failed; HTML output is complete ->", log)
        self.assertIn("Removed incomplete PDF ->", log)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["doc_vi.html"])
        self.assertFalse(self.work.exists(), "work/ must still be cleaned after a PDF-only failure")

    def test_empty_pdf_does_not_fail_packaging(self) -> None:
        _FakeBrowser.behaviour = "empty"
        html, pdf, log = self._package()
        self._assert_degraded_to_html_only(html, pdf, log)
        self.assertIn("Browser log: fake browser log line", log)

    def test_timeout_does_not_fail_packaging(self) -> None:
        _FakeBrowser.behaviour = "hang"
        html, pdf, log = self._package()
        self._assert_degraded_to_html_only(html, pdf, log)
        self.assertIn("timed out after 6 s", log)

    def test_missing_browser_reports_on_stdout_in_order(self) -> None:
        # The line replaces "Exported PDF" in SKILL.md Step 4, so it must be on stdout (stderr shows up
        # out of order when agents read piped output) and come after "Embedded" and before "Cleaned".
        err = StringIO()
        with mock.patch.object(pdfx, "find_headless_browser", return_value=None), redirect_stderr(err):
            html, pdf, log = self._package()
        self.assertIsNone(pdf)
        self.assertTrue(html.is_file())
        self.assertEqual(err.getvalue(), "")
        warn = log.index("WARNING: Microsoft Edge/Chrome not found; skipped automatic PDF export for ")
        self.assertLess(log.index("Embedded images into HTML ->"), warn)
        self.assertLess(warn, log.index("Cleaned temp directory ->"))
        self.assertEqual(_FakeBrowser.calls, [], "no browser must be launched")
        self.assertFalse(self.work.exists(), "work/ must still be cleaned when no browser is found")

    def test_rerun_after_failure_keeps_single_numbering(self) -> None:
        _FakeBrowser.behaviour = "empty"
        self._package()
        self.work.mkdir()
        self.draft.write_text(_DRAFT_HTML, encoding="utf-8")
        _FakeBrowser.behaviour = "ok"
        html2, pdf2, _ = self._package()
        self.assertEqual(html2.name, "doc_vi_2.html")
        self.assertEqual(pdf2.name, "doc_vi_2.pdf")
        self.assertFalse((self.out / "doc_vi.pdf").exists(), "no orphan empty PDF from the failed run")

    def test_unsafe_clean_dir_fails_before_any_output_is_written(self) -> None:
        _FakeBrowser.behaviour = "ok"
        with redirect_stdout(StringIO()):
            with self.assertRaisesRegex(ValueError, "Refusing to clean unsafe directory"):
                pkg.embed_images_and_package(
                    html_path=self.draft,
                    optimize_image_bytes_fn=lambda *_a: (_ for _ in ()).throw(AssertionError("no images expected")),
                    out_html_path=str(self.out / "doc_vi.html"),
                    also_pdf=True,
                    clean_dir="output",
                    timeout_seconds=6,
                )
        self.assertEqual(list(self.out.iterdir()), [], "output/ must stay untouched so a re-run never creates _2")
        self.assertEqual(_FakeBrowser.calls, [], "browser must not start when -CleanDir is invalid")
        self.assertTrue(self.draft.is_file())

    def test_clean_dir_containing_output_fails_before_writing(self) -> None:
        with redirect_stdout(StringIO()):
            with self.assertRaisesRegex(ValueError, "resides inside it"):
                pkg.embed_images_and_package(
                    html_path=self.draft,
                    optimize_image_bytes_fn=lambda *_a: (_ for _ in ()).throw(AssertionError("no images expected")),
                    out_html_path=str(self.work / "final_vi.html"),
                    clean_dir="work",
                    timeout_seconds=6,
                )
        self.assertFalse((self.work / "final_vi.html").exists())

    def test_cleanup_failure_after_outputs_only_warns(self) -> None:
        _FakeBrowser.behaviour = "ok"
        err = StringIO()
        with mock.patch.object(output_paths, "safe_clean_dir", side_effect=ValueError("junction appeared mid-run")):
            with mock.patch.object(sys, "stderr", err):
                html, pdf, log = self._package()
        self.assertTrue(html.is_file())
        self.assertIsNotNone(pdf)
        self.assertIn("WARNING: Skipped cleaning temp directory; outputs are complete", err.getvalue())
        self.assertIn("junction appeared mid-run", err.getvalue())

    def test_standalone_html_to_pdf_rejects_unsafe_clean_dir_before_export(self) -> None:
        _FakeBrowser.behaviour = "ok"
        target = self.out / "solo.pdf"
        with redirect_stdout(StringIO()):
            with self.assertRaisesRegex(ValueError, "Refusing to clean unsafe directory"):
                pdfx.html_to_pdf(self.draft, out_pdf_path=str(target), clean_dir="output", timeout_seconds=6)
        self.assertFalse(target.exists())
        self.assertEqual(_FakeBrowser.calls, [])

    def test_standalone_html_to_pdf_still_raises_and_leaves_no_pdf(self) -> None:
        _FakeBrowser.behaviour = "empty"
        target = self.out / "solo.pdf"
        with redirect_stdout(StringIO()):
            with self.assertRaises(RuntimeError):
                pdfx.html_to_pdf(self.draft, out_pdf_path=str(target), timeout_seconds=6)
        self.assertFalse(target.exists())
        self.assertTrue(self.work.exists(), "standalone HtmlToPdf must not clean work/ on failure")


if __name__ == "__main__":
    unittest.main()
