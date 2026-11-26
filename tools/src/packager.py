"""Step 4 packaging: embed local images as Base64, inject reader shell, run Auto-QA, optional PDF."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Callable

from html_qa import run_html_qa_check
from mathjax_guard import inject_mathjax_link_guard
from output_paths import (
    assert_expected_output_extension,
    clean_dir_after_outputs,
    find_next_available_index,
    get_indexed_file_path,
    prepare_sanitized_output_path,
)
from path_guards import (
    assert_local_no_unc_path,
    assert_safe_output_path,
    resolve_safe_sub_image_path,
    validate_clean_dir,
)
from pdf_export import MAX_INPUT_HTML_BYTES, html_to_pdf
from reader_shell import inject_csp_meta, inject_reader_shell, sub_outside_ignored

IMG_TAG_RX = re.compile(r'(?is)<img\b((?:[^>"\']|"[^"]*"|\'[^\']*\')*)>')
IMG_SRC_RX = re.compile(r'(?is)((?:^|\s)src\s*=\s*)(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'=<>`]+))')
_EXT_IMG_RX = re.compile(r"(?i)^(?:data:|https?://)")
_LOCAL_OPT_EXT_RX = re.compile(r"(?i)\.(?:png|jpe?g)$")


def _get_img_src_value(src_match: re.Match[str]) -> str:
    if src_match.group(2) is not None:
        return src_match.group(2)
    if src_match.group(3) is not None:
        return src_match.group(3)
    return src_match.group(4) or ""


def embed_images_and_package(
    html_path: str | Path,
    optimize_image_bytes_fn: Callable[[Path, int, int], tuple[bytes, str, int]],
    out_html_path: str = "",
    out_pdf_path: str = "",
    also_pdf: bool = False,
    preserve_layout: bool = False,
    quality: int = 95,
    max_width: int = 1400,
    clean_dir: str = "",
    timeout_seconds: int = 60,
    shell_path: Path | None = None,
) -> tuple[Path, Path | None]:
    """Embed & optimize local images in memory, inject reader shell, run Auto-QA, and optionally export PDF."""
    if quality < 1 or quality > 100:
        raise ValueError(f"JpegQuality out of valid range (1..100): {quality}")
    if max_width < 0 or max_width > 10000:
        raise ValueError(f"MaxImageWidth out of valid range (0..10000): {max_width}")
    if timeout_seconds < 5 or timeout_seconds > 600:
        raise ValueError(f"PdfTimeoutSeconds out of range (5..600): {timeout_seconds}")

    assert_local_no_unc_path(html_path, "-HtmlPath")
    assert_local_no_unc_path(out_html_path, "-OutHtmlPath")
    assert_local_no_unc_path(out_pdf_path, "-OutPdfPath")
    assert_local_no_unc_path(clean_dir, "-CleanDir")

    raw_in = str(html_path or "").strip()
    if not raw_in or not os.path.isfile(raw_in):
        raise FileNotFoundError(f"HTML file not found: {html_path}")
    abs_html = Path(os.path.abspath(raw_in))
    assert_local_no_unc_path(abs_html, "-HtmlPath")
    html_sz = abs_html.stat().st_size
    if html_sz > MAX_INPUT_HTML_BYTES:
        raise ValueError(f"Refusing oversized HTML input ({html_sz:,} bytes > {MAX_INPUT_HTML_BYTES:,} byte limit): {abs_html}")
    base_dir = abs_html.parent
    content = abs_html.read_text(encoding="utf-8-sig")

    opt_cache: dict[str, tuple[str, int, int]] = {}
    stats = {"total": 0, "compressed": 0, "orig_bytes": 0, "final_bytes": 0}

    def _replace_src(src_match: re.Match[str]) -> str:
        prefix = src_match.group(1)
        rel = _get_img_src_value(src_match).strip()
        if not rel or _EXT_IMG_RX.match(rel):
            return src_match.group(0)
        if _LOCAL_OPT_EXT_RX.search(rel):
            img_path = resolve_safe_sub_image_path(base_dir, rel)
            if img_path is not None:
                key = str(img_path).lower()
                if key not in opt_cache:
                    out_bytes, mime, orig_len = optimize_image_bytes_fn(img_path, quality, max_width)
                    b64 = base64.b64encode(out_bytes).decode("ascii")
                    opt_cache[key] = (f"data:{mime};base64,{b64}", orig_len, len(out_bytes))
                data_uri, orig_len, final_len = opt_cache[key]
                stats["total"] += 1
                stats["orig_bytes"] += orig_len
                stats["final_bytes"] += final_len
                if final_len < orig_len:
                    stats["compressed"] += 1
                return f'{prefix}"{data_uri}"'
        return src_match.group(0)

    def _replace_img_tag(img_match: re.Match[str]) -> str:
        return "<img" + IMG_SRC_RX.sub(_replace_src, img_match.group(1)) + ">"

    updated, _ = sub_outside_ignored(content, IMG_TAG_RX, _replace_img_tag)

    shell_injected: list[str] = []
    if not preserve_layout:
        updated, shell_injected = inject_reader_shell(updated, shell_path=shell_path)

    updated, guard_injected = inject_mathjax_link_guard(updated)

    updated = updated.replace("\r\n", "\n").replace("\r", "\n")
    qa_scanner = run_html_qa_check(
        updated,
        skip_table_wrapper_check=preserve_layout,
        shell_path=shell_path,
        require_mathjax_guard=True,
    )
    updated = inject_csp_meta(
        updated,
        mathjax_srcs=qa_scanner.mathjax_srcs,
        inline_script_raw_bodies=qa_scanner.allowed_inline_script_raw_bodies,
    )

    has_explicit_out_html = bool(out_html_path and out_html_path.strip())
    if has_explicit_out_html:
        dest = prepare_sanitized_output_path(out_html_path, label="-OutHtmlPath", expected_ext=".html")
    else:
        assert_expected_output_extension(abs_html, ".html", "-HtmlPath", raw_display=raw_in)
        dest = assert_safe_output_path(abs_html, label="-OutHtmlPath", is_directory=False)
        assert dest is not None

    has_custom_out_pdf = bool(out_pdf_path and out_pdf_path.strip())
    want_pdf = also_pdf or has_custom_out_pdf
    pdf_protected: Path | None = None
    if want_pdf:
        if has_custom_out_pdf:
            pdf_protected = prepare_sanitized_output_path(out_pdf_path, label="-OutPdfPath", expected_ext=".pdf")
        else:
            pdf_protected = assert_safe_output_path(dest.with_suffix(".pdf"), label="-OutPdfPath", is_directory=False)

    if has_explicit_out_html and not has_custom_out_pdf:
        candidates = [dest, pdf_protected] if pdf_protected is not None else [dest]
        pair_idx = find_next_available_index(candidates)
        if pair_idx > 1:
            dest = assert_safe_output_path(get_indexed_file_path(dest, pair_idx), label="-OutHtmlPath", is_directory=False)
            assert dest is not None
            print(f"Output collision avoided; auto-numbered -> {dest}")
            if pdf_protected is not None:
                pdf_protected = assert_safe_output_path(
                    get_indexed_file_path(pdf_protected, pair_idx), label="-OutPdfPath", is_directory=False
                )
    else:
        if has_explicit_out_html:
            html_idx = find_next_available_index([dest])
            if html_idx > 1:
                dest = assert_safe_output_path(get_indexed_file_path(dest, html_idx), label="-OutHtmlPath", is_directory=False)
                assert dest is not None
                print(f"Output collision avoided; auto-numbered -> {dest}")
        if pdf_protected is not None:
            pdf_idx = find_next_available_index([pdf_protected])
            if pdf_idx > 1:
                pdf_protected = assert_safe_output_path(
                    get_indexed_file_path(pdf_protected, pdf_idx), label="-OutPdfPath", is_directory=False
                )

    # Validate -CleanDir before writing anything: a bad value must fail while output\ is still untouched.
    has_clean_dir = bool(clean_dir and clean_dir.strip())
    if has_clean_dir:
        validate_clean_dir(clean_dir, protected_paths=[dest] + ([pdf_protected] if pdf_protected else []))

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(updated, encoding="utf-8", newline="\n")
    sz = dest.stat().st_size

    if stats["total"] > 0:
        saved_kb = round((stats["orig_bytes"] - stats["final_bytes"]) / 1024.0, 1)
        print(f"Optimized {stats['compressed']}/{stats['total']} images (Quality={quality}%, saved {saved_kb:,.1f} KB raw)")

    if preserve_layout:
        print("PreserveLayout mode: skipped reader shell injection")
    elif shell_injected:
        print(f"Injected reader shell -> {', '.join(shell_injected)}")
    else:
        print("Reader shell already present (skipped injection)")

    if guard_injected:
        print("Injected MathJax link guard (non-http(s)/mailto/# links in formulas are disabled)")
    print(f"Embedded images into HTML -> {dest} ({sz:,} bytes)")

    exported_pdf: Path | None = None
    if want_pdf and pdf_protected is not None:
        try:
            exported_pdf = html_to_pdf(
                dest,
                out_pdf_path=pdf_protected,
                clean_dir="",
                timeout_seconds=timeout_seconds,
                _qa_verified=True,
                shell_path=shell_path,
            )
        except (RuntimeError, OSError) as exc:
            # HTML is already written and QA-verified: degrade to HTML-only instead of failing the run,
            # so agents do not re-run packaging and create duplicate `_2`, `_3` outputs.
            reason = " ".join(str(exc).split())
            print(f"WARNING: PDF export failed; HTML output is complete -> {dest} | Reason: {reason}")
            exported_pdf = None

    if has_clean_dir:
        protected = [dest] + ([exported_pdf] if exported_pdf is not None else [pdf_protected] if pdf_protected else [])
        clean_dir_after_outputs(clean_dir, protected_paths=protected)

    return dest, exported_pdf
