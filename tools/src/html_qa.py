"""HTML Auto-QA: single-pass DOM & security scanner (scripts, tags, URIs, CSS, images, tables, anchors)."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from reader_shell import extract_trusted_shell_scripts, normalize_script_body

_DATA_IMG_RX = re.compile(r"^data:image/(?:png|jpeg|jpg|webp|gif);base64,", re.IGNORECASE)
_EXTERNAL_URL_RX = re.compile(r"^(?:https?:)?//", re.IGNORECASE)
_ALLOWED_MATHJAX_SRC_RX = re.compile(
    r"^https://(?:"
    r"cdn\.jsdelivr\.net/npm/mathjax@3(?:\.\d+){0,2}/es5/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.js"
    r"|cdnjs\.cloudflare\.com/ajax/libs/mathjax/3(?:\.\d+){1,2}/es5/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.js"
    r")$",
    re.IGNORECASE,
)
_ALLOWED_CSS_REMOTE_RX = re.compile(
    r"^https://fonts\.(?:googleapis|gstatic)\.com(?:/|$)",
    re.IGNORECASE,
)
_FORBIDDEN_HTML_TAGS = frozenset(
    {
        "iframe",
        "object",
        "embed",
        "applet",
        "base",
        "form",
        "frame",
        "frameset",
        "portal",
        "fencedframe",
        "foreignobject",
        "animate",
        "animatemotion",
        "animatetransform",
        "set",
        "handler",
        "template",
        "noscript",
    }
)
_FORBIDDEN_META_HTTP_EQUIV = frozenset({"refresh", "set-cookie"})
# Browsers end a comment at `<!-->`, `<!--->` (empty comment) and at `--!>`, while Python's HTMLParser
# keeps reading until the next `-->`. Tags placed after these forms (e.g. <meta http-equiv="refresh">)
# would be live in the browser yet hidden from this scanner, so the forms are rejected outright.
_MALFORMED_COMMENT_RX = re.compile(r"<!---?>|--!>")
# Inside <svg>/<math> (foreign content) browsers parse <style>/<script>/<textarea>/... bodies as markup, while
# Python's HTMLParser treats them as raw text. Hidden tags there (e.g. <img onerror>, <script href>) would
# reach the browser unseen, so these elements are rejected outright inside foreign content.
_FOREIGN_CONTENT_ROOTS = ("svg", "math")
_FOREIGN_RAW_TEXT_TAGS = frozenset(
    {"script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript", "plaintext"}
)
_EVENT_HANDLER_ATTR_RX = re.compile(r"^on[a-z]+$", re.IGNORECASE)
_URI_ATTRS = frozenset({"href", "src", "xlink:href", "action", "formaction", "poster", "data", "background"})
_SVG_EXTERNAL_HREF_TAGS = frozenset({"image", "use", "feimage"})
_MEDIA_SRC_TAGS = frozenset({"audio", "video", "source", "track"})
_ALLOWED_LINK_RELS = frozenset({"stylesheet", "preconnect", "font"})
_STRIP_CTRL_WS_RX = re.compile(r"[\x00-\x20\x7f]+")
_URI_SCHEME_RX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_SAFE_LINK_SCHEME_RX = re.compile(r"^(?:https?://|mailto:)", re.IGNORECASE)
_DANGEROUS_URI_SCHEME_RX = re.compile(r"^(?:javascript|vbscript|file):", re.IGNORECASE)
_CSS_COMMENT_RX = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_ESCAPE_RX = re.compile(r"\\([0-9a-fA-F]{1,6})\s?|\\(.)")
_CSS_URL_RX = re.compile(
    r"""(?i)\burl\s*\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s"']+))\s*\)"""
    r"""|@import\s+(?:url\s*\(\s*)?(?:"([^"]*)"|'([^']*)'|([^;\s"']+))"""
)
_CSS_IMAGE_SET_RX = re.compile(r"""(?is)(?:-webkit-)?image-set\s*\(([^)]*)\)""")
_CSS_QUOTED_STR_RX = re.compile(r"""(?:"([^"]*)"|'([^']*)')""")
_LATEX_HREF_URL_RX = re.compile(r"""\\(?:href|url)\s*\{([^{}]*)\}""", re.IGNORECASE)
_LATEX_STYLE_RX = re.compile(r"""\\style\s*\{([^{}]*)\}""", re.IGNORECASE)
_LIGHTBOX_IDS = frozenset({"rsfv-img-lightbox", "img-lightbox"})
_HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_RAW_DOM_EXCLUDED_TAGS = frozenset({"script", "style", "textarea"})
_LATEX_IGNORED_TAGS = frozenset({"script", "style", "pre", "code", "textarea"})
_P_AUTO_CLOSE_TRIGGERS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "details",
        "dialog",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "li",
        "main",
        "menu",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    }
)
_P_SCOPE_BOUNDARIES = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "details",
        "dialog",
        "div",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "header",
        "html",
        "li",
        "main",
        "nav",
        "section",
        "table",
        "td",
        "th",
    }
)


def _decode_css_escapes(text: str) -> str:
    """Decode CSS backslash escapes (e.g. `\\68 ttps://`) before URL scheme inspection."""

    def _repl(m: re.Match[str]) -> str:
        hex_part = m.group(1)
        if hex_part is not None:
            try:
                cp = int(hex_part, 16)
                if 0 < cp <= 0x10FFFF:
                    return chr(cp)
            except ValueError:
                pass
            return ""
        return m.group(2) or ""

    return _CSS_ESCAPE_RX.sub(_repl, text)


def _is_allowed_css_url(raw_url: str) -> bool:
    """Allowlist-only CSS URL filter: permits empty, #fragment, Base64 raster images, and Google Fonts."""
    cleaned = _STRIP_CTRL_WS_RX.sub("", raw_url)
    if not cleaned or cleaned.startswith("#"):
        return True
    if _DATA_IMG_RX.match(cleaned) or _ALLOWED_CSS_REMOTE_RX.match(cleaned):
        return True
    return False


def _format_sample_items(items: list[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    if len(items) > limit:
        shown += f" (+{len(items) - limit} more)"
    return shown


class _QADOMScanner(HTMLParser):
    """Single-pass DOM & security scanner tracking tag nesting while ignoring HTML comments and raw blocks."""

    def __init__(
        self,
        *,
        allowed_inline_scripts: frozenset[str] = frozenset(),
        allow_external_images: bool = False,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self._allowed_inline_scripts = allowed_inline_scripts
        self._allow_external_images = allow_external_images
        self._open_stack: list[tuple[str, bool, str]] = []
        self._prose_buf: list[str] = []
        self._active_script: dict[str, object] | None = None
        self._style_buf: list[str] = []
        self.has_head_open = False
        self.has_head_close = False
        self.has_body_open = False
        self.has_body_close = False
        self.b64_count = 0
        self.unembedded_imgs = 0
        self.unembedded_img_srcs: list[str] = []
        self._seen_unembedded_imgs: set[str] = set()
        self.external_img_srcs: list[str] = []
        self._seen_ext_imgs: set[str] = set()
        self.missing_alt_imgs = 0
        self.table_count = 0
        self.wrapped_table_count = 0
        self.has_latex = False
        self.has_mathjax_in_head = False
        self.mathjax_srcs: list[str] = []
        # Open <svg>/<math> counted by explicit start/end tags only (not the implied-close stack), so the
        # scanner never believes foreign content ended while the browser still considers it open.
        self._foreign_depth: dict[str, int] = {name: 0 for name in _FOREIGN_CONTENT_ROOTS}
        self.allowed_inline_script_raw_bodies: list[str] = []
        self.seen_ids: set[str] = set()
        self.anchor_refs: list[str] = []
        self.disallowed_scripts: list[str] = []
        self._seen_scripts: set[str] = set()
        self.disallowed_tags: list[str] = []
        self._seen_tags: set[str] = set()
        self.disallowed_event_handlers: list[str] = []
        self._seen_handlers: set[str] = set()
        self.dangerous_uris: list[str] = []
        self._seen_uris: set[str] = set()
        self.disallowed_external_resources: list[str] = []
        self._seen_ext_res: set[str] = set()

    @staticmethod
    def _add_issue(bucket: list[str], seen: set[str], value: str) -> None:
        if value not in seen:
            seen.add(value)
            bucket.append(value)

    def _in_tags(self, tag_set: frozenset[str]) -> bool:
        return any(t in tag_set for t, _, _ in self._open_stack)

    def _current_raw_tag(self) -> str | None:
        for t, _, _ in reversed(self._open_stack):
            if t in _RAW_DOM_EXCLUDED_TAGS:
                return t
        return None

    def _flush_prose(self) -> None:
        if not self._prose_buf:
            return
        chunk = "".join(self._prose_buf)
        self._prose_buf.clear()
        if not self.has_latex and (r"\(" in chunk or r"\[" in chunk):
            self.has_latex = True
        if "\\" in chunk:
            for m in _LATEX_HREF_URL_RX.finditer(chunk):
                raw_target = _STRIP_CTRL_WS_RX.sub("", m.group(1) or "")
                if raw_target and not (
                    raw_target.startswith("#") or _SAFE_LINK_SCHEME_RX.match(raw_target)
                ):
                    self._add_issue(
                        self.dangerous_uris,
                        self._seen_uris,
                        f'LaTeX \\href{{{raw_target[:60]}}}',
                    )
            for m in _LATEX_STYLE_RX.finditer(chunk):
                css_payload = m.group(1) or ""
                if css_payload:
                    self._scan_css_text(css_payload, source="LaTeX \\style")
                    if "expression(" in _STRIP_CTRL_WS_RX.sub("", css_payload).lower():
                        self._add_issue(
                            self.disallowed_external_resources,
                            self._seen_ext_res,
                            "LaTeX \\style expression(...)",
                        )

    def _close_implicit_p(self) -> None:
        for idx in range(len(self._open_stack) - 1, -1, -1):
            t, _, _ = self._open_stack[idx]
            if t == "p":
                del self._open_stack[idx:]
                return
            if t in _P_SCOPE_BOUNDARIES:
                return

    def _pop_open_tag(self, target_tag: str) -> None:
        for idx in range(len(self._open_stack) - 1, -1, -1):
            if self._open_stack[idx][0] == target_tag:
                del self._open_stack[idx:]
                return

    def _scan_css_text(self, css_text: str, source: str) -> None:
        stripped = _decode_css_escapes(_CSS_COMMENT_RX.sub("", css_text))
        for m in _CSS_URL_RX.finditer(stripped):
            raw_url = next((g for g in m.groups() if g is not None), "")
            if raw_url and not _is_allowed_css_url(raw_url):
                self._add_issue(
                    self.disallowed_external_resources,
                    self._seen_ext_res,
                    f"{source} url({raw_url.strip()[:100]})",
                )
        for im in _CSS_IMAGE_SET_RX.finditer(stripped):
            body = im.group(1) or ""
            for qm in _CSS_QUOTED_STR_RX.finditer(body):
                cand_url = qm.group(1) if qm.group(1) is not None else (qm.group(2) or "")
                if cand_url and not _is_allowed_css_url(cand_url):
                    self._add_issue(
                        self.disallowed_external_resources,
                        self._seen_ext_res,
                        f"{source} image-set({cand_url.strip()[:100]})",
                    )

    def _finalize_style_block(self) -> None:
        if not self._style_buf:
            return
        self._scan_css_text("".join(self._style_buf), source="<style>")
        self._style_buf.clear()

    def _finalize_active_script(self) -> None:
        if self._active_script is None:
            return
        info = self._active_script
        self._active_script = None
        in_head = bool(info["in_head"])
        src_val = info["src"]
        body_chunks = info["body"]
        assert isinstance(body_chunks, list)
        raw_body = "".join(body_chunks)
        body_norm = normalize_script_body(raw_body)

        if src_val is not None:
            cleaned_src = str(src_val).strip()
            if in_head and not body_norm and _ALLOWED_MATHJAX_SRC_RX.match(cleaned_src):
                self.has_mathjax_in_head = True
                if cleaned_src not in self.mathjax_srcs:
                    self.mathjax_srcs.append(cleaned_src)
                return
            desc = f'<script src="{cleaned_src[:100]}">' if cleaned_src else '<script src="">'
            self._add_issue(self.disallowed_scripts, self._seen_scripts, desc)
            return

        if body_norm and body_norm in self._allowed_inline_scripts:
            self.allowed_inline_script_raw_bodies.append(raw_body)
            return

        snippet = (body_norm[:40] + "...") if len(body_norm) > 40 else (body_norm or "<empty>")
        self._add_issue(self.disallowed_scripts, self._seen_scripts, f"<script>{snippet}</script>")

    # --- Start tags -------------------------------------------------------------------------------------------
    # `_process_start_tag` runs the checks below in a fixed order. Several results are ordered lists, so keep the
    # order of the calls (and of the per-attribute checks) when changing anything here.

    def _process_start_tag(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        self._flush_prose()
        t = tag.lower()
        if self._in_tags(_RAW_DOM_EXCLUDED_TAGS):
            return

        self._track_structure_open(t, self_closing)

        if t == "head":
            self.has_head_open = True
        elif t == "body":
            self.has_body_open = True
        elif t == "script":
            self._start_script(attrs, self_closing)
        elif t == "style" and not self_closing:
            self._style_buf.clear()
        elif t == "img":
            self._start_img(attrs)
        elif t == "table":
            self._start_table()

        is_wrapper, elem_id, meta_http_equiv = self._scan_attributes(t, attrs)

        if t == "meta" and meta_http_equiv in _FORBIDDEN_META_HTTP_EQUIV:
            self._add_issue(self.disallowed_tags, self._seen_tags, f'<meta http-equiv="{meta_http_equiv}">')

        if not self_closing and t not in _HTML_VOID_TAGS:
            self._open_stack.append((t, is_wrapper, elem_id))

    def _track_structure_open(self, t: str, self_closing: bool) -> None:
        """Close an implicit <p>, flag forbidden tags and raw-text tags inside SVG/MathML, track foreign depth."""
        if t in _P_AUTO_CLOSE_TRIGGERS:
            self._close_implicit_p()

        if t in _FORBIDDEN_HTML_TAGS:
            self._add_issue(self.disallowed_tags, self._seen_tags, f"<{t}>")

        if t in _FOREIGN_RAW_TEXT_TAGS:
            foreign_root = next((name for name in _FOREIGN_CONTENT_ROOTS if self._foreign_depth[name] > 0), None)
            if foreign_root is not None:
                self._add_issue(
                    self.disallowed_tags,
                    self._seen_tags,
                    f"<{t}> inside <{foreign_root}> (parsed as markup by browsers)",
                )
        if t in self._foreign_depth and not self_closing:
            self._foreign_depth[t] += 1

    def _start_script(self, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        """Reject self-closing / duplicate-src scripts; otherwise buffer the script for `_finalize_active_script`."""
        in_head = any(t_name == "head" for t_name, _, _ in self._open_stack)
        script_srcs = ["" if v is None else v for k, v in attrs if (k or "").lower() == "src"]
        if self_closing:
            first_src = script_srcs[0].strip()[:80] if script_srcs else ""
            desc = f'<script src="{first_src}"/>' if script_srcs else "<script/>"
            self._add_issue(self.disallowed_scripts, self._seen_scripts, desc)
        elif len(script_srcs) > 1:
            self._add_issue(self.disallowed_scripts, self._seen_scripts, "<script (duplicate src)>")
            self._active_script = {"in_head": False, "src": script_srcs[0], "body": []}
        else:
            script_src = script_srcs[0] if script_srcs else None
            self._active_script = {"in_head": in_head, "src": script_src, "body": []}

    def _start_img(self, attrs: list[tuple[str, str | None]]) -> None:
        """Count embedded/unembedded/external images and missing alt (dangerous schemes: `_check_img_src_uri`)."""
        has_alt = False
        has_nonempty_src = False
        in_lightbox = any(
            t_name == "div" and eid in _LIGHTBOX_IDS
            for t_name, _, eid in self._open_stack
        )
        for k, v in attrs:
            kl = (k or "").lower()
            if kl == "alt":
                has_alt = True
            elif kl == "src" and v is not None:
                src_val = v.strip()
                if not src_val:
                    continue
                has_nonempty_src = True
                norm_uri = _STRIP_CTRL_WS_RX.sub("", src_val)
                if _DATA_IMG_RX.match(norm_uri):
                    self.b64_count += 1
                elif (
                    norm_uri.startswith(("//", "\\\\"))
                    or (_URI_SCHEME_RX.match(norm_uri) and not _EXTERNAL_URL_RX.match(norm_uri))
                ):
                    pass  # Reported by the URI allowlist in `_check_uri_attr`
                elif _EXTERNAL_URL_RX.match(norm_uri):
                    if not self._allow_external_images:
                        self._add_issue(self.external_img_srcs, self._seen_ext_imgs, src_val[:120])
                else:
                    self.unembedded_imgs += 1
                    self._add_issue(self.unembedded_img_srcs, self._seen_unembedded_imgs, src_val[:120])
        if not has_nonempty_src and not in_lightbox:
            self.unembedded_imgs += 1
            self._add_issue(self.unembedded_img_srcs, self._seen_unembedded_imgs, "<empty src>")
        if not has_alt:
            self.missing_alt_imgs += 1

    def _start_table(self) -> None:
        self.table_count += 1
        if any(is_w for _, is_w, _ in self._open_stack):
            self.wrapped_table_count += 1

    def _scan_attributes(self, t: str, attrs: list[tuple[str, str | None]]) -> tuple[bool, str, str]:
        """Check every attribute of `<t>`; return (is table wrapper, lower-cased id, meta http-equiv)."""
        is_wrapper = False
        elem_id = ""
        meta_http_equiv = ""
        link_rels: set[str] = set()
        for k, v in attrs:
            kl = (k or "").lower()
            if kl == "rel" and t == "link" and v:
                link_rels.update(tok for tok in v.lower().split() if tok)

        for k, v in attrs:
            kl = (k or "").lower()
            val_str = "" if v is None else v
            self._check_active_attr(t, kl, val_str)

            if kl == "id" and val_str:
                id_val = val_str.strip()
                if id_val:
                    elem_id = id_val.lower()
                    self.seen_ids.add(id_val)
            elif kl == "class" and val_str and t != "table":
                if "table-wrapper" in val_str.lower().split():
                    is_wrapper = True
            elif kl == "http-equiv" and t == "meta" and val_str:
                meta_http_equiv = val_str.strip().lower()
            elif kl == "style" and val_str:
                self._scan_css_text(val_str, source=f"<{t} style>")

            if kl in _URI_ATTRS and val_str:
                self._check_uri_attr(t, kl, val_str, link_rels)
                if kl == "href":
                    href_val = val_str.strip()
                    if href_val.startswith("#") and len(href_val) > 1:
                        self.anchor_refs.append(href_val[1:])
        return is_wrapper, elem_id, meta_http_equiv

    def _check_active_attr(self, t: str, kl: str, val_str: str) -> None:
        """Flag event handlers, srcdoc/ping, srcset and MathJax DOM clobbering via id/name."""
        if _EVENT_HANDLER_ATTR_RX.match(kl) or kl in ("srcdoc", "ping"):
            self._add_issue(self.disallowed_event_handlers, self._seen_handlers, f"<{t} {kl}>")
        if kl == "srcset" and val_str.strip():
            self._add_issue(
                self.disallowed_external_resources,
                self._seen_ext_res,
                f'<{t} srcset="{val_str.strip()[:100]}">',
            )
        if kl in ("id", "name") and val_str.strip().lower() == "mathjax":
            self._add_issue(
                self.disallowed_tags,
                self._seen_tags,
                f'<{t} {kl}="MathJax"> (DOM clobbering)',
            )

    def _check_uri_attr(self, t: str, kl: str, val_str: str, link_rels: set[str]) -> None:
        """Strict URI allowlist by element/attribute role."""
        norm_uri = _STRIP_CTRL_WS_RX.sub("", val_str)
        if not norm_uri:
            return
        if norm_uri.startswith(("//", "\\\\")):
            self._add_issue(self.dangerous_uris, self._seen_uris, f'<{t} {kl}="{norm_uri[:60]}">')
        elif t in ("a", "area") and kl == "href":
            if _URI_SCHEME_RX.match(norm_uri) and not _SAFE_LINK_SCHEME_RX.match(norm_uri):
                self._add_issue(self.dangerous_uris, self._seen_uris, f'<{t} {kl}="{norm_uri[:60]}">')
        elif t == "link" and kl == "href":
            self._check_link_href(norm_uri, val_str, link_rels)
        elif t == "img" and kl == "src":
            self._check_img_src_uri(norm_uri)
        elif t == "script" and kl == "src":
            self._check_script_src_uri(norm_uri)
        else:
            self._check_other_uri(t, kl, norm_uri, val_str)

    def _check_link_href(self, norm_uri: str, val_str: str, link_rels: set[str]) -> None:
        """<link href>: only the allowed remote stylesheets/fonts, with allowed rel values."""
        if _URI_SCHEME_RX.match(norm_uri) and not _ALLOWED_CSS_REMOTE_RX.match(norm_uri):
            if _DANGEROUS_URI_SCHEME_RX.match(norm_uri) or norm_uri.lower().startswith("data:"):
                self._add_issue(self.dangerous_uris, self._seen_uris, f'<link href="{norm_uri[:60]}">')
            else:
                self._add_issue(
                    self.disallowed_external_resources,
                    self._seen_ext_res,
                    f'<link href="{val_str.strip()[:100]}">',
                )
        elif not _ALLOWED_CSS_REMOTE_RX.match(norm_uri) or (link_rels and not (link_rels <= _ALLOWED_LINK_RELS)):
            self._add_issue(
                self.disallowed_external_resources,
                self._seen_ext_res,
                f'<link href="{val_str.strip()[:100]}">',
            )

    def _check_img_src_uri(self, norm_uri: str) -> None:
        """<img src>: any scheme other than data:image or http(s) is dangerous (counting is in `_start_img`)."""
        if _URI_SCHEME_RX.match(norm_uri) and not (_DATA_IMG_RX.match(norm_uri) or _EXTERNAL_URL_RX.match(norm_uri)):
            self._add_issue(self.dangerous_uris, self._seen_uris, f'<img src="{norm_uri[:60]}">')

    def _check_script_src_uri(self, norm_uri: str) -> None:
        """<script src>: a non-http scheme is dangerous (allowlisting happens in `_finalize_active_script`)."""
        if (
            _URI_SCHEME_RX.match(norm_uri)
            and not _ALLOWED_MATHJAX_SRC_RX.match(norm_uri)
            and not _EXTERNAL_URL_RX.match(norm_uri)
        ):
            self._add_issue(self.dangerous_uris, self._seen_uris, f'<script src="{norm_uri[:60]}">')

    def _check_other_uri(self, t: str, kl: str, norm_uri: str, val_str: str) -> None:
        """All remaining URI attributes (SVG <use>/<image>/<feImage>, <audio>/<video>/<source>,
        background/poster/data/action/formaction): allow only internal #fragment references."""
        if norm_uri.startswith("#"):
            return
        if _EXTERNAL_URL_RX.match(norm_uri) and (
            (t in _SVG_EXTERNAL_HREF_TAGS and kl in ("href", "xlink:href"))
            or (t in _MEDIA_SRC_TAGS and kl == "src")
            or kl in ("background", "poster")
        ):
            self._add_issue(
                self.disallowed_external_resources,
                self._seen_ext_res,
                f'<{t} {kl}="{val_str.strip()[:100]}">',
            )
        elif _URI_SCHEME_RX.match(norm_uri):
            self._add_issue(self.dangerous_uris, self._seen_uris, f'<{t} {kl}="{norm_uri[:60]}">')
        else:
            self._add_issue(
                self.disallowed_external_resources,
                self._seen_ext_res,
                f'<{t} {kl}="{val_str.strip()[:100]}">',
            )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._process_start_tag(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._process_start_tag(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        self._flush_prose()
        t = tag.lower()
        raw_tag = self._current_raw_tag()
        if raw_tag is not None:
            if t != raw_tag:
                return
            if raw_tag == "script":
                self._finalize_active_script()
            elif raw_tag == "style":
                self._finalize_style_block()
            self._pop_open_tag(t)
            return
        if t == "head":
            self.has_head_close = True
        elif t == "body":
            self.has_body_close = True
        elif t in self._foreign_depth and self._foreign_depth[t] > 0:
            self._foreign_depth[t] -= 1
        self._pop_open_tag(t)

    def handle_data(self, data: str) -> None:
        if self._active_script is not None:
            body_chunks = self._active_script["body"]
            assert isinstance(body_chunks, list)
            body_chunks.append(data)
            return
        if self._current_raw_tag() == "style":
            self._style_buf.append(data)
            return
        if self._in_tags(_LATEX_IGNORED_TAGS):
            return
        self._prose_buf.append(data)

    def handle_comment(self, data: str) -> None:
        self._flush_prose()

    def close(self) -> None:
        self._flush_prose()
        self._finalize_active_script()
        self._finalize_style_block()
        super().close()


def run_html_qa_check(
    html_text: str,
    skip_table_wrapper_check: bool = False,
    *,
    allowed_inline_scripts: frozenset[str] | None = None,
    shell_path: Path | None = None,
    allow_external_images: bool = False,
) -> _QADOMScanner:
    """Validate structure, security policy, Base64 images, alt tags, .table-wrapper nesting, MathJax, and anchors."""
    if allowed_inline_scripts is None:
        allowed_scripts = (
            frozenset()
            if skip_table_wrapper_check
            else extract_trusted_shell_scripts(shell_path=shell_path)
        )
    else:
        allowed_scripts = allowed_inline_scripts

    scanner = _QADOMScanner(
        allowed_inline_scripts=allowed_scripts,
        allow_external_images=allow_external_images,
    )
    scanner.feed(html_text)
    scanner.close()

    issues: list[str] = []
    if not (
        scanner.has_head_open
        and scanner.has_head_close
        and scanner.has_body_open
        and scanner.has_body_close
    ):
        issues.append("HTML must contain complete <head>...</head> and <body>...</body> sections.")

    if scanner.disallowed_scripts:
        issues.append(
            f"Disallowed <script> tag(s) (only trusted MathJax CDN in <head> is permitted): "
            f"{_format_sample_items(scanner.disallowed_scripts)}"
        )
    if scanner.disallowed_tags:
        issues.append(f"Disallowed HTML tag(s): {_format_sample_items(scanner.disallowed_tags)}")
    malformed_comments = sorted({m.group(0) for m in _MALFORMED_COMMENT_RX.finditer(html_text)})
    if malformed_comments:
        issues.append(
            "Disallowed malformed HTML comment(s) (browsers end the comment early; "
            f"write comments as <!-- ... -->): {_format_sample_items(malformed_comments)}"
        )
    if scanner.disallowed_event_handlers:
        issues.append(
            f"Disallowed inline event handler attribute(s): {_format_sample_items(scanner.disallowed_event_handlers)}"
        )
    if scanner.dangerous_uris:
        issues.append(f"Disallowed dangerous URI(s): {_format_sample_items(scanner.dangerous_uris)}")
    if scanner.external_img_srcs:
        issues.append(
            f"Disallowed external <img> URL(s) (images must be local Base64 assets): "
            f"{_format_sample_items(scanner.external_img_srcs)}"
        )
    if scanner.disallowed_external_resources:
        issues.append(
            f"Disallowed external resource reference(s): "
            f"{_format_sample_items(scanner.disallowed_external_resources)}"
        )

    if scanner.unembedded_imgs > 0:
        detail = f": {_format_sample_items(scanner.unembedded_img_srcs)}" if scanner.unembedded_img_srcs else ""
        issues.append(f"Found {scanner.unembedded_imgs} un-embedded local <img> src link(s){detail}.")
    if scanner.missing_alt_imgs > 0:
        issues.append(f"Found {scanner.missing_alt_imgs} <img> tag(s) missing alt attribute.")

    unwrapped_tables = scanner.table_count - scanner.wrapped_table_count
    if not skip_table_wrapper_check and unwrapped_tables > 0:
        issues.append(
            f"Found {unwrapped_tables} <table> element(s) not wrapped inside a .table-wrapper container."
        )

    if scanner.has_latex and not scanner.has_mathjax_in_head:
        issues.append("Detected LaTeX math delimiters without MathJax <script> in <head>.")

    broken_anchors: list[str] = []
    seen_broken: set[str] = set()
    for anchor in scanner.anchor_refs:
        if anchor not in scanner.seen_ids and anchor not in seen_broken:
            seen_broken.add(anchor)
            broken_anchors.append(f"#{anchor}")
    if broken_anchors:
        issues.append(f"Broken internal anchor(s): {', '.join(broken_anchors)}")

    if issues:
        raise ValueError("HTML Auto-QA FAILED:\n - " + "\n - ".join(issues))

    table_status = (
        f"Tables: {scanner.table_count} (wrapper optional)"
        if skip_table_wrapper_check
        else f"Tables wrapped: {scanner.wrapped_table_count}/{scanner.table_count}"
    )
    print(f"[QA PASS] Base64 images: {scanner.b64_count} | {table_status} | LaTeX/MathJax OK | Broken anchors: 0")
    return scanner
