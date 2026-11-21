#!/usr/bin/env python3
# ==============================================================================
# [BUILD SOURCE / REFERENCE ONLY — DO NOT EXECUTE WITH SYSTEM PYTHON]
#
# Mục đích tệp này: Đây CHỈ là mã nguồn Python gốc dùng khi cần chỉnh sửa logic
# và đóng gói (PyInstaller) ra tệp chạy độc lập `tools\extract_assets\extract_assets.exe`.
#
# LƯU Ý CHO AI AGENT:
#   - KHÔNG chạy tệp `.py` này bằng `python` / `python3` / `py` / `pip`.
#   - Máy người dùng chạy qua bộ công cụ portable không cần Python hệ thống.
#   - Khi tách ảnh PDF, hãy gọi `tools\extract_pdf_assets.ps1` (tự động gọi
#     `tools\extract_assets\extract_assets.exe`) theo hướng dẫn trong SKILL.md.
# ==============================================================================
"""
CLI Entry Point & PyInstaller Build Source for `extract_assets.exe`.

Dispatches all portable operations across dedicated modules:
  - `figure_detector/`: Layout-aware figure/caption detection and extraction (package, one module per phase)
  - `image_ops.py`: Lazy PyMuPDF loader, page rendering, JSON cropping, image optimization
  - `packager.py`: Step 4 entry point — Base64 embedding, then reader shell, Auto-QA and optional PDF via:
      `reader_shell.py` (shell + CSP injection), `html_qa.py` (Auto-QA scanner),
      `pdf_export.py` (headless Edge/Chrome), `output_paths.py` (output naming & post-output cleanup)
  - `transcript.py`: Latest PDF attachment lookup in transcript.jsonl (Antigravity)
  - `manifest.py`: Compacted manifest stdout output (stdlib only, no project imports)
  - `path_guards.py`: Path safety, UNC/reparse-point guards, and safe cleanup

Build target:
  tools/extract_assets/extract_assets.exe (invoked via tools/*.ps1 wrappers)
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Callable
from pathlib import Path

from figure_detector import extract_images
from image_ops import _optimize_image_bytes, crop_from_json, render_pages
from packager import embed_images_and_package
from path_guards import assert_local_no_unc_path
from pdf_export import html_to_pdf
from transcript import find_latest_pdf_in_transcript

__all__ = ["main"]


def _configure_utf8_stdio() -> None:
    """Ensure stdout/stderr emit UTF-8 on Windows even when piped under cp1252."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ------------------------------------------------------------------------------
# argparse `type=` validators
# ------------------------------------------------------------------------------


def _number_in_range(cast: Callable[[str], float], lo: float, hi: float, flag: str) -> Callable[[str], float]:
    """Build a validator that parses with `cast` and requires `lo <= value <= hi` (NaN/inf rejected)."""

    def _parse(value: str) -> float:
        number = cast(value)
        if not math.isfinite(number) or number < lo or number > hi:
            shown = value if cast is float else number
            raise argparse.ArgumentTypeError(f"{flag} must be between {lo} and {hi} (got {shown})")
        return number

    _parse.__name__ = cast.__name__  # argparse shows it in "invalid <name> value: ..." errors
    return _parse


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"Expected non-negative integer (got {number})")
    return number


_non_negative_int.__name__ = "int"

_DPI = _number_in_range(int, 36, 1200, "--dpi")
_SCALE = _number_in_range(float, 0.5, 10.0, "--scale")
_QUALITY = _number_in_range(int, 1, 100, "--quality")
_MAX_WIDTH = _number_in_range(int, 0, 10000, "--max-width")
_TIMEOUT = _number_in_range(int, 5, 600, "--timeout-seconds")


# ------------------------------------------------------------------------------
# Modes: each one declares its arguments and runs its operation.
# Run functions look the operation up at call time, so tests can replace it.
# ------------------------------------------------------------------------------


def _add_extract_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--mode", choices=tuple(_MODES), default="extract", help="Operation mode (default: extract)")
    ap.add_argument("pdf", nargs="?", type=Path, default=None)
    ap.add_argument("--transcript", type=str, default="", help="Resolve latest PDF attachment from transcript.jsonl")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--dpi", type=_DPI, default=180)
    ap.add_argument("--meta", action="store_true", help="Write manifest.json mapping extracted images")
    ap.add_argument("--stdout-meta", action="store_true", help="Also print compacted manifest JSON to stdout")
    ap.add_argument("--max-meta-bytes", type=_non_negative_int, default=16384)
    ap.add_argument("--max-meta-words", type=_non_negative_int, default=20)
    ap.add_argument("--print-resolved", action="store_true", help="Print 'Resolved PDF -> ...' line")


def _run_extract(args: argparse.Namespace) -> None:
    if args.pdf is not None and str(args.pdf).strip():
        assert_local_no_unc_path(args.pdf, "-PdfPath")
        if not args.pdf.is_file():
            raise FileNotFoundError(f"Resolved PDF file does not exist: {args.pdf}")
        target_pdf = Path(os.path.abspath(str(args.pdf)))
    elif args.transcript and args.transcript.strip():
        target_pdf = find_latest_pdf_in_transcript(args.transcript)
    else:
        raise ValueError("Either pdf path or --transcript must be provided.")

    if args.print_resolved or args.transcript:
        print(f"Resolved PDF -> {target_pdf}")

    extract_images(
        target_pdf,
        args.out_dir,
        args.dpi,
        write_meta=args.meta,
        stdout_meta=args.stdout_meta,
        max_meta_words=args.max_meta_words,
        max_meta_bytes=args.max_meta_bytes,
        detector="egret",  # the only detector the product uses; failures stop the run (no fallback)
    )


def _add_render_pages_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--scale", type=_SCALE, default=2.5)
    ap.add_argument("--pages", type=str, default="")


def _run_render_pages(args: argparse.Namespace) -> None:
    render_pages(args.pdf, args.out_dir, scale=args.scale, pages=args.pages)


def _add_crop_json_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)


def _run_crop_json(args: argparse.Namespace) -> None:
    crop_from_json(args.spec, args.out_dir)


def _add_embed_images_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--html", type=Path, required=True)
    ap.add_argument("--out-html", type=str, default="")
    ap.add_argument("--out-pdf", type=str, default="")
    ap.add_argument("--also-pdf", action="store_true")
    ap.add_argument("--preserve-layout", action="store_true")
    ap.add_argument("--quality", type=_QUALITY, default=95)
    ap.add_argument("--max-width", type=_MAX_WIDTH, default=1400)
    ap.add_argument("--clean-dir", type=str, default="")
    ap.add_argument("--timeout-seconds", type=_TIMEOUT, default=60)


def _run_embed_images(args: argparse.Namespace) -> None:
    embed_images_and_package(
        html_path=args.html,
        optimize_image_bytes_fn=_optimize_image_bytes,
        out_html_path=args.out_html,
        out_pdf_path=args.out_pdf,
        also_pdf=args.also_pdf,
        preserve_layout=args.preserve_layout,
        quality=args.quality,
        max_width=args.max_width,
        clean_dir=args.clean_dir,
        timeout_seconds=args.timeout_seconds,
    )


def _add_html_to_pdf_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--html", type=Path, required=True)
    ap.add_argument("--out-pdf", type=str, default="")
    ap.add_argument("--clean-dir", type=str, default="")
    ap.add_argument("--timeout-seconds", type=_TIMEOUT, default=60)


def _run_html_to_pdf(args: argparse.Namespace) -> None:
    html_to_pdf(
        html_path=args.html,
        out_pdf_path=args.out_pdf,
        clean_dir=args.clean_dir,
        timeout_seconds=args.timeout_seconds,
    )


# mode -> (parser description, argument declarations, operation); the first entry is the default mode.
_MODES: dict[
    str,
    tuple[str, Callable[[argparse.ArgumentParser], None], Callable[[argparse.Namespace], None]],
] = {
    "extract": (
        "Layout-aware figure image extractor & standalone PDF/HTML packager (PyMuPDF)",
        _add_extract_args,
        _run_extract,
    ),
    "render-pages": ("Render PDF pages to PNG images", _add_render_pages_args, _run_render_pages),
    "crop-json": (
        "Crop PNG regions from JSON spec with optional auto-trim",
        _add_crop_json_args,
        _run_crop_json,
    ),
    "embed-images": (
        "Embed images in memory, inject reader shell, run QA, and optionally export PDF",
        _add_embed_images_args,
        _run_embed_images,
    ),
    "html-to-pdf": (
        "Convert self-contained HTML to PDF via headless Edge/Chrome",
        _add_html_to_pdf_args,
        _run_html_to_pdf,
    ),
}


def _dispatch_cli(raw_argv: list[str]) -> None:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--mode", choices=tuple(_MODES), default=None)
    known, rest = pre.parse_known_args(raw_argv)
    description, add_args, run = _MODES[known.mode or "extract"]
    ap = argparse.ArgumentParser(description=description)
    add_args(ap)
    run(ap.parse_args(rest))


def main(argv: list[str] | None = None) -> None:
    _configure_utf8_stdio()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        _dispatch_cli(raw_argv)
    except (ValueError, FileNotFoundError, RuntimeError, TimeoutError, PermissionError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
