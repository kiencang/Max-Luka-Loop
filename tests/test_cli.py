"""CLI contract of extract_assets.py: argument parsing, defaults, validation errors and dispatch (stdlib only).

The real work functions are replaced by recorders, so these tests only pin how each `--mode` turns argv
into a call: which function, with which arguments, and which exit code / message for bad input.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "tools" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import extract_assets as ea  # noqa: E402

HANDLERS = ("extract_images", "render_pages", "crop_from_json", "embed_images_and_package", "html_to_pdf")


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.pdf = self.tmp / "doc.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n")
        self.calls: list[tuple[str, tuple, dict]] = []
        self._patches = [
            mock.patch.object(ea, name, side_effect=self._recorder(name)) for name in HANDLERS
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _recorder(self, name: str):
        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return _record

    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with redirect_stdout(out), redirect_stderr(err):
            try:
                ea.main(list(argv))
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    # --- extract -------------------------------------------------------------------------------

    def test_extract_defaults(self) -> None:
        code, out, _ = self._run(str(self.pdf), "--out-dir", "o")
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "no 'Resolved PDF' line without --print-resolved")
        self.assertEqual(
            self.calls,
            [(
                "extract_images",
                (Path(os.path.abspath(self.pdf)), Path("o"), 180),
                dict(write_meta=False, stdout_meta=False, max_meta_words=20, max_meta_bytes=16384,
                     detector="egret"),
            )],
        )

    def test_extract_all_flags_with_explicit_mode_and_separator(self) -> None:
        code, out, _ = self._run(
            "--mode", "extract", "--out-dir=o", "--dpi=250", "--meta", "--stdout-meta",
            "--max-meta-bytes=100", "--max-meta-words=5", "--print-resolved", "--", str(self.pdf),
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, f"Resolved PDF -> {os.path.abspath(self.pdf)}\n")
        self.assertEqual(
            self.calls,
            [(
                "extract_images",
                (Path(os.path.abspath(self.pdf)), Path("o"), 250),
                dict(write_meta=True, stdout_meta=True, max_meta_words=5, max_meta_bytes=100, detector="egret"),
            )],
        )

    def test_extract_has_no_detector_choice(self) -> None:
        # Egret is the only detector: the rule-based one must not be reachable from the exe.
        for value in ("heuristic", "egret"):
            code, _, err = self._run(str(self.pdf), "--out-dir", "o", f"--detector={value}")
            self.assertEqual(code, 2)
            self.assertIn("unrecognized arguments", err)
        self.assertEqual(self.calls, [])

    def test_extract_via_transcript_prints_resolved_pdf(self) -> None:
        with mock.patch.object(ea, "find_latest_pdf_in_transcript", return_value=self.pdf) as find:
            code, out, _ = self._run("--out-dir", "o", "--transcript", "t.jsonl")
        self.assertEqual(code, 0)
        find.assert_called_once_with("t.jsonl")
        self.assertEqual(out, f"Resolved PDF -> {self.pdf}\n")
        self.assertEqual(self.calls[0][1], (self.pdf, Path("o"), 180))

    def test_extract_errors_exit_1(self) -> None:
        code, _, err = self._run("--out-dir", "o")
        self.assertEqual((code, err), (1, "ERROR: Either pdf path or --transcript must be provided.\n"))
        code, _, err = self._run(str(self.tmp / "missing.pdf"), "--out-dir", "o")
        self.assertEqual(code, 1)
        self.assertIn("ERROR: Resolved PDF file does not exist:", err)
        code, _, err = self._run(r"\\server\share\a.pdf", "--out-dir", "o")
        self.assertEqual(code, 1)
        self.assertIn("ERROR: Refusing UNC/network path for -PdfPath", err)
        self.assertEqual(self.calls, [])

    # --- other modes ---------------------------------------------------------------------------

    def test_render_pages(self) -> None:
        self.assertEqual(self._run("--mode", "render-pages", "--out-dir", "p", "--", "a.pdf")[0], 0)
        self._run("--mode", "render-pages", "--out-dir", "p", "--scale=3", "--pages=2-4", "--", "a.pdf")
        self.assertEqual(
            self.calls,
            [
                ("render_pages", (Path("a.pdf"), Path("p")), dict(scale=2.5, pages="")),
                ("render_pages", (Path("a.pdf"), Path("p")), dict(scale=3.0, pages="2-4")),
            ],
        )

    def test_crop_json(self) -> None:
        self.assertEqual(self._run("--mode", "crop-json", "--spec=s.json", "--out-dir=o")[0], 0)
        self.assertEqual(self.calls, [("crop_from_json", (Path("s.json"), Path("o")), {})])

    def test_embed_images_defaults_and_flags(self) -> None:
        self._run("--mode", "embed-images", "--html=d.html")
        self._run(
            "--mode", "embed-images", "--html=d.html", "--out-html=o.html", "--out-pdf=o.pdf", "--also-pdf",
            "--preserve-layout", "--quality=80", "--max-width=0", "--clean-dir=work", "--timeout-seconds=30",
        )
        common = dict(html_path=Path("d.html"), optimize_image_bytes_fn=ea._optimize_image_bytes)
        self.assertEqual(
            self.calls,
            [
                ("embed_images_and_package", (), dict(common, out_html_path="", out_pdf_path="", also_pdf=False,
                 preserve_layout=False, quality=95, max_width=1400, clean_dir="", timeout_seconds=60)),
                ("embed_images_and_package", (), dict(common, out_html_path="o.html", out_pdf_path="o.pdf",
                 also_pdf=True, preserve_layout=True, quality=80, max_width=0, clean_dir="work",
                 timeout_seconds=30)),
            ],
        )

    def test_html_to_pdf(self) -> None:
        self._run("--mode", "html-to-pdf", "--html=d.html")
        self._run("--mode", "html-to-pdf", "--html=d.html", "--out-pdf=o.pdf", "--clean-dir=work",
                  "--timeout-seconds=5")
        self.assertEqual(
            self.calls,
            [
                ("html_to_pdf", (), dict(html_path=Path("d.html"), out_pdf_path="", clean_dir="",
                 timeout_seconds=60)),
                ("html_to_pdf", (), dict(html_path=Path("d.html"), out_pdf_path="o.pdf", clean_dir="work",
                 timeout_seconds=5)),
            ],
        )

    # --- validation ----------------------------------------------------------------------------

    def test_out_of_range_values_exit_2_with_clear_message(self) -> None:
        cases = [
            (("--out-dir=o", "--dpi=35", str(self.pdf)), "--dpi must be between 36 and 1200 (got 35)"),
            (("--out-dir=o", "--dpi=1201", str(self.pdf)), "--dpi must be between 36 and 1200 (got 1201)"),
            (("--out-dir=o", "--max-meta-bytes=-1", str(self.pdf)), "Expected non-negative integer (got -1)"),
            (("--out-dir=o", "--max-meta-words=-3", str(self.pdf)), "Expected non-negative integer (got -3)"),
            (("--mode", "render-pages", "--out-dir=p", "--scale=0.4", "a.pdf"),
             "--scale must be between 0.5 and 10.0 (got 0.4)"),
            (("--mode", "render-pages", "--out-dir=p", "--scale=nan", "a.pdf"),
             "--scale must be between 0.5 and 10.0 (got nan)"),
            (("--mode", "embed-images", "--html=d", "--quality=0"), "--quality must be between 1 and 100 (got 0)"),
            (("--mode", "embed-images", "--html=d", "--quality=101"), "--quality must be between 1 and 100 (got 101)"),
            (("--mode", "embed-images", "--html=d", "--max-width=-1"),
             "--max-width must be between 0 and 10000 (got -1)"),
            (("--mode", "embed-images", "--html=d", "--timeout-seconds=4"),
             "--timeout-seconds must be between 5 and 600 (got 4)"),
            (("--mode", "html-to-pdf", "--html=d", "--timeout-seconds=601"),
             "--timeout-seconds must be between 5 and 600 (got 601)"),
        ]
        for argv, message in cases:
            with self.subTest(argv=argv):
                code, _, err = self._run(*argv)
                self.assertEqual(code, 2)
                self.assertIn(message, err)
        self.assertEqual(self.calls, [])

    def test_boundary_values_are_accepted(self) -> None:
        for argv in (
            ("--out-dir=o", "--dpi=36", str(self.pdf)),
            ("--out-dir=o", "--dpi=1200", "--max-meta-bytes=0", "--max-meta-words=0", str(self.pdf)),
            ("--mode", "render-pages", "--out-dir=p", "--scale=0.5", "a.pdf"),
            ("--mode", "render-pages", "--out-dir=p", "--scale=10", "a.pdf"),
            ("--mode", "embed-images", "--html=d", "--quality=1", "--max-width=10000", "--timeout-seconds=600"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self._run(*argv)[0], 0)
        self.assertEqual(len(self.calls), 5)

    def test_non_numeric_value_and_unknown_mode_exit_2(self) -> None:
        code, _, err = self._run("--out-dir=o", "--dpi=abc", str(self.pdf))
        self.assertEqual(code, 2)
        self.assertIn("argument --dpi: invalid", err)
        code, _, err = self._run("--mode", "nope")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice: 'nope'", err)
        code, _, err = self._run("--mode", "crop-json", "--out-dir=o")
        self.assertEqual(code, 2)
        self.assertIn("the following arguments are required: --spec", err)


if __name__ == "__main__":
    unittest.main()
