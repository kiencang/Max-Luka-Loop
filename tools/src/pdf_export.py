"""Headless Edge/Chrome PDF export of QA-verified HTML with an isolated profile and host allowlist."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from html_qa import run_html_qa_check
from output_paths import (
    clean_dir_after_outputs,
    find_next_available_index,
    get_indexed_file_path,
    prepare_sanitized_output_path,
)
from path_guards import (
    assert_local_no_unc_path,
    assert_safe_output_path,
    is_reparse_point,
    validate_clean_dir,
)
from reader_shell import extract_trusted_shell_scripts

MAX_INPUT_HTML_BYTES = 256 * 1024 * 1024  # 256 MB sanity ceiling for raw input HTML
_HEADLESS_ALLOWED_HOSTS_RULE = (
    "MAP * ~NOTFOUND, "
    "EXCLUDE cdn.jsdelivr.net, "
    "EXCLUDE cdnjs.cloudflare.com, "
    "EXCLUDE fonts.googleapis.com, "
    "EXCLUDE fonts.gstatic.com"
)
# Virtual-time budget (ms) for headless print: network fetches do not consume it, but MathJax typesetting does.
HEADLESS_VIRTUAL_TIME_BUDGET_MS = 7000


def _discard_partial_pdf(pdf_path: Path) -> None:
    """Best-effort removal of an empty/partial PDF left behind by a failed headless export."""
    for attempt in range(3):
        try:
            if not os.path.lexists(pdf_path) or is_reparse_point(pdf_path) or not os.path.isfile(pdf_path):
                return
            os.remove(pdf_path)
            print(f"Removed incomplete PDF -> {pdf_path}")
            return
        except OSError:
            if attempt < 2:
                time.sleep(0.4)
    print(f"WARNING: Could not remove incomplete PDF (file locked?): {pdf_path}", file=sys.stderr)


def find_headless_browser() -> str | None:
    """Locate Microsoft Edge (preferred) or Google Chrome executable on Windows."""
    roots_and_subpaths = [
        (os.environ.get("ProgramFiles(x86)", ""), os.path.join("Microsoft", "Edge", "Application", "msedge.exe")),
        (os.environ.get("ProgramFiles", ""), os.path.join("Microsoft", "Edge", "Application", "msedge.exe")),
        (os.environ.get("LocalAppData", ""), os.path.join("Microsoft", "Edge", "Application", "msedge.exe")),
        (os.environ.get("ProgramFiles", ""), os.path.join("Google", "Chrome", "Application", "chrome.exe")),
        (os.environ.get("ProgramFiles(x86)", ""), os.path.join("Google", "Chrome", "Application", "chrome.exe")),
        (os.environ.get("LocalAppData", ""), os.path.join("Google", "Chrome", "Application", "chrome.exe")),
    ]
    for base, sub in roots_and_subpaths:
        if not base or not base.strip():
            continue
        candidate = os.path.join(base, sub)
        if os.path.isfile(candidate):
            return candidate
    return None


def html_to_pdf(
    html_path: str | Path,
    out_pdf_path: str | Path = "",
    clean_dir: str = "",
    timeout_seconds: int = 60,
    *,
    _qa_verified: bool = False,
    shell_path: Path | None = None,
) -> Path | None:
    """Convert HTML to printable PDF via hardened headless Edge/Chrome after security Auto-QA."""
    if timeout_seconds < 5 or timeout_seconds > 600:
        raise ValueError(f"PdfTimeoutSeconds out of range (5..600): {timeout_seconds}")
    assert_local_no_unc_path(html_path, "-HtmlPath")
    assert_local_no_unc_path(out_pdf_path, "-OutPdfPath")
    assert_local_no_unc_path(clean_dir, "-CleanDir")

    raw_html = str(html_path or "").strip()
    if not raw_html or not os.path.isfile(raw_html):
        raise FileNotFoundError(f"HTML file not found: {html_path}")
    abs_html = Path(os.path.abspath(raw_html))
    assert_local_no_unc_path(abs_html, "-HtmlPath")
    html_sz = abs_html.stat().st_size
    if html_sz > MAX_INPUT_HTML_BYTES:
        raise ValueError(f"Refusing oversized HTML input ({html_sz:,} bytes > {MAX_INPUT_HTML_BYTES:,} byte limit): {abs_html}")

    if not _qa_verified:
        html_text = abs_html.read_text(encoding="utf-8-sig")
        trusted_scripts = extract_trusted_shell_scripts(shell_path=shell_path)
        run_html_qa_check(
            html_text,
            skip_table_wrapper_check=True,
            allowed_inline_scripts=trusted_scripts,
            shell_path=shell_path,
        )

    raw_pdf = str(out_pdf_path or "").strip()
    dest_pdf = prepare_sanitized_output_path(
        raw_pdf if raw_pdf else str(abs_html.with_suffix(".pdf")),
        label="-OutPdfPath",
        expected_ext=".pdf",
    )

    pdf_idx = find_next_available_index([dest_pdf])
    if pdf_idx > 1:
        dest_pdf = assert_safe_output_path(get_indexed_file_path(dest_pdf, pdf_idx), label="-OutPdfPath", is_directory=False)
        assert dest_pdf is not None
        print(f"Output collision avoided; auto-numbered -> {dest_pdf}")

    has_clean_dir = bool(clean_dir and clean_dir.strip())
    if has_clean_dir:
        validate_clean_dir(clean_dir, protected_paths=[dest_pdf])

    dest_pdf.parent.mkdir(parents=True, exist_ok=True)

    browser = find_headless_browser()
    if not browser:
        # stdout, not stderr: this line replaces "Exported PDF" and agents must see it in order (see SKILL.md Step 4).
        print(f"WARNING: Microsoft Edge/Chrome not found; skipped automatic PDF export for {abs_html}")
        return None

    tmp_profile = Path(tempfile.gettempdir()) / f"edge_pdf_{uuid.uuid4().hex}"
    tmp_profile.mkdir(parents=True, exist_ok=True)
    try:
        uri = abs_html.as_uri()
        err_log = tmp_profile / "edge_err.log"
        out_log = tmp_profile / "edge_out.log"
        cmd = [
            browser,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--log-level=3",
            "--disable-extensions",
            "--disable-sync",
            "--no-first-run",
            "--disable-default-apps",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-translate",
            f"--host-resolver-rules={_HEADLESS_ALLOWED_HOSTS_RULE}",
            "--run-all-compositor-stages-before-draw",
            f"--virtual-time-budget={HEADLESS_VIRTUAL_TIME_BUDGET_MS}",
            f"--user-data-dir={tmp_profile}",
            f"--print-to-pdf={dest_pdf}",
            uri,
        ]
        with open(out_log, "wb") as fout, open(err_log, "wb") as ferr:
            proc = subprocess.Popen(cmd, stdout=fout, stderr=ferr)
            try:
                proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except OSError:
                    pass
                _discard_partial_pdf(dest_pdf)
                raise TimeoutError(f"Headless browser timed out after {timeout_seconds} s while exporting PDF: {dest_pdf}")

        if not dest_pdf.is_file() or dest_pdf.stat().st_size == 0:
            err_detail = ""
            for lf in (err_log, out_log):
                if lf.is_file():
                    raw_log = lf.read_text(encoding="utf-8", errors="replace").strip()
                    if raw_log:
                        err_detail = ("..." + raw_log[-600:]) if len(raw_log) > 600 else raw_log
                        break
            msg = f"Headless browser failed to export PDF (exit={proc.returncode}): {dest_pdf}"
            if err_detail:
                msg += f" | Browser log: {err_detail}"
            _discard_partial_pdf(dest_pdf)
            raise RuntimeError(msg)

        pdf_sz = dest_pdf.stat().st_size
        print(f"Exported PDF -> {dest_pdf} ({pdf_sz:,} bytes)")
        if has_clean_dir:
            clean_dir_after_outputs(clean_dir, protected_paths=[dest_pdf])
        return dest_pdf
    finally:
        time.sleep(0.2)
        shutil.rmtree(tmp_profile, ignore_errors=True)
