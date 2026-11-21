"""Inject tools/reader_shell.html (CSS, toolbar, script) and the CSP <meta> into translated HTML."""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
from typing import Callable

from path_guards import (
    assert_local_no_unc_path,
    get_tools_dir,
    is_reparse_point,
)

_HTML_IGNORED_SEGMENTS_RX = re.compile(
    r"(?is)<!--.*?-->|<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<textarea\b[^>]*>.*?</textarea>"
)
_SCRIPT_BODY_RX = re.compile(r"(?is)<script\b[^>]*>(.*?)</script>")
_CSP_META_TAG_RX = re.compile(r"""(?is)<meta\b[^>]*\bdata-max-luka-csp\s*=\s*["']1["'][^>]*>\s*""")
_CSP_SAFE_SOURCE_RX = re.compile(r"^https://[A-Za-z0-9.-]+/[A-Za-z0-9_.@/-]+$")


def _get_shell_section(template: str, tag_name: str) -> str:
    m = re.search(rf"(?is)<!--\s*{re.escape(tag_name)}_START\s*-->(.*?)<!--\s*{re.escape(tag_name)}_END\s*-->", template)
    if not m:
        raise ValueError(f"Reader shell template missing section: {tag_name}")
    return m.group(1).strip()


def _resolve_safe_shell_path(shell_path: Path | None = None, *, required: bool = True) -> Path | None:
    """Resolve tools/reader_shell.html while refusing symlinks/junctions."""
    resolved_shell = shell_path if shell_path is not None else (get_tools_dir() / "reader_shell.html")
    assert_local_no_unc_path(resolved_shell, "ReaderShellPath")
    if os.path.lexists(resolved_shell.parent) and is_reparse_point(resolved_shell.parent):
        raise ValueError(f"Refusing to read reader shell through symlink/junction: {resolved_shell.parent}")
    if os.path.lexists(resolved_shell) and is_reparse_point(resolved_shell):
        raise ValueError(f"Refusing to read symlink/junction reader shell: {resolved_shell}")
    if not resolved_shell.is_file():
        if required or shell_path is not None:
            raise FileNotFoundError(f"Reader shell template not found: {resolved_shell}")
        return None
    return resolved_shell


def _strip_html_comments(html_text: str) -> str:
    """Remove HTML comments while leaving <script>, <style>, and <textarea> contents intact."""
    return _HTML_IGNORED_SEGMENTS_RX.sub(
        lambda m: "" if m.group(0).startswith("<!--") else m.group(0),
        html_text,
    )


def sub_outside_ignored(
    text: str,
    target_rx: re.Pattern[str],
    repl: Callable[[re.Match[str]], str] | str,
    count: int = 0,
) -> tuple[str, int]:
    """Apply `target_rx` substitutions only on HTML markup outside comments, scripts, styles, and textareas."""
    parts: list[str] = []
    pos = 0
    total_subs = 0
    for ign in _HTML_IGNORED_SEGMENTS_RX.finditer(text):
        seg = text[pos : ign.start()]
        if seg and (count == 0 or total_subs < count):
            rem = (count - total_subs) if count > 0 else 0
            seg, n = target_rx.subn(repl, seg, count=rem)
            total_subs += n
        parts.append(seg)
        parts.append(ign.group(0))
        pos = ign.end()
    tail = text[pos:]
    if tail and (count == 0 or total_subs < count):
        rem = (count - total_subs) if count > 0 else 0
        tail, n = target_rx.subn(repl, tail, count=rem)
        total_subs += n
    parts.append(tail)
    return "".join(parts), total_subs


def inject_reader_shell(html_text: str, shell_path: Path | None = None) -> tuple[str, list[str]]:
    """Idempotently inject reader CSS, toolbar, and script from tools/reader_shell.html."""
    resolved_shell = _resolve_safe_shell_path(shell_path, required=True)
    assert resolved_shell is not None
    dom_check = _HTML_IGNORED_SEGMENTS_RX.sub("", html_text)
    if (
        not re.search(r"(?i)</head>", dom_check)
        or not re.search(r"(?i)<body\b[^>]*>", dom_check)
        or not re.search(r"(?i)</body>", dom_check)
    ):
        raise ValueError("HTML must contain <head>...</head> and <body>...</body> for reader shell injection.")

    tpl = resolved_shell.read_text(encoding="utf-8-sig")
    shell_css = _get_shell_section(tpl, "SHELL_CSS")
    shell_toolbar = _get_shell_section(tpl, "SHELL_TOOLBAR")
    shell_script = _get_shell_section(tpl, "SHELL_SCRIPT")

    injected: list[str] = []
    out = html_text
    no_comments = _strip_html_comments(out)

    has_css = bool(
        re.search(r'(?i)data-reader-shell\s*=\s*"1"', no_comments)
        or (re.search(r"(?i)\.reader-toolbar\b", no_comments) and re.search(r"(?i)\.img-lightbox\b", no_comments))
    )
    if not has_css:
        out, _ = sub_outside_ignored(out, re.compile(r"(?i)</head>"), lambda m: f"{shell_css}\n{m.group(0)}", count=1)
        injected.append("CSS")

    has_toolbar = bool(
        re.search(r'(?i)data-reader-shell\s*=\s*"toolbar"', no_comments)
        or re.search(r'(?i)class\s*=\s*"[^"]*\b(?:rsfv-toolbar|reader-toolbar)\b', no_comments)
    )
    if not has_toolbar:
        out, _ = sub_outside_ignored(
            out,
            re.compile(r"(?i)<body\b[^>]*>"),
            lambda m: f"{m.group(0)}\n{shell_toolbar}",
            count=1,
        )
        injected.append("Toolbar")

    has_script = bool(
        re.search(r'(?i)data-reader-shell\s*=\s*"script"', no_comments)
        or re.search(r'(?i)\bid\s*=\s*"(?:rsfv-img-lightbox|img-lightbox)"', no_comments)
    )
    if not has_script:
        out, _ = sub_outside_ignored(out, re.compile(r"(?i)</body>"), lambda m: f"{shell_script}\n{m.group(0)}", count=1)
        injected.append("Script")

    return out, injected


def normalize_script_body(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def extract_trusted_shell_scripts(shell_path: Path | None = None) -> frozenset[str]:
    """Return normalized exact inline JS bodies allowed from the trusted reader_shell.html template."""
    resolved_shell = _resolve_safe_shell_path(shell_path, required=False)
    if resolved_shell is None:
        return frozenset()
    tpl = resolved_shell.read_text(encoding="utf-8-sig")
    shell_script_section = _get_shell_section(tpl, "SHELL_SCRIPT")
    bodies = {
        normalize_script_body(m.group(1))
        for m in _SCRIPT_BODY_RX.finditer(shell_script_section)
        if m.group(1).strip()
    }
    return frozenset(bodies)


def mathjax_csp_sources(mathjax_srcs: list[str]) -> list[str]:
    """Return the `.../es5/` directory of each QA-approved MathJax src as a path-restricted CSP source.

    MathJax loads its components and fonts from that directory, so allowing the whole CDN origin is
    unnecessary — and unsafe, since anyone can publish scripts to jsDelivr/cdnjs.
    """
    sources: list[str] = []
    for src in mathjax_srcs:
        cut = src.lower().find("/es5/")
        if cut < 0 or not _CSP_SAFE_SOURCE_RX.match(src):
            raise ValueError(f"Unexpected MathJax src for CSP: {src[:100]}")
        base = src[: cut + len("/es5/")]
        if base not in sources:
            sources.append(base)
    return sources


def inject_csp_meta(
    html_text: str,
    *,
    mathjax_srcs: list[str],
    inline_script_raw_bodies: list[str],
) -> str:
    """Idempotently inject a defense-in-depth Content-Security-Policy <meta> right inside <head>."""
    cleaned, _ = sub_outside_ignored(html_text, _CSP_META_TAG_RX, "")
    mathjax_sources = mathjax_csp_sources(mathjax_srcs)

    script_tokens: list[str] = []
    seen_hashes: set[str] = set()
    for raw_body in inline_script_raw_bodies:
        norm_lf = raw_body.replace("\r\n", "\n").replace("\r", "\n")
        if not norm_lf.strip():
            continue
        digest = base64.b64encode(hashlib.sha256(norm_lf.encode("utf-8")).digest()).decode("ascii")
        token = f"'sha256-{digest}'"
        if token not in seen_hashes:
            seen_hashes.add(token)
            script_tokens.append(token)
    script_tokens.extend(mathjax_sources)
    script_src = " ".join(script_tokens) if script_tokens else "'none'"

    font_tokens = ["https://fonts.gstatic.com", "data:"]
    font_tokens.extend(mathjax_sources)
    font_src = " ".join(font_tokens)

    policy = (
        f"default-src 'none'; "
        f"img-src data:; "
        f"style-src 'unsafe-inline' https://fonts.googleapis.com; "
        f"font-src {font_src}; "
        f"script-src {script_src}; "
        f"connect-src 'none'; "
        f"object-src 'none'; "
        f"frame-src 'none'; "
        f"base-uri 'none'; "
        f"form-action 'none';"
    )
    meta_tag = f'<meta http-equiv="Content-Security-Policy" data-max-luka-csp="1" content="{policy}">'
    updated, count = sub_outside_ignored(
        cleaned,
        re.compile(r"(?i)<head\b[^>]*>"),
        lambda m: f"{m.group(0)}\n{meta_tag}",
        count=1,
    )
    return updated if count > 0 else cleaned
