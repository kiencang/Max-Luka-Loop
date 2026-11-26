"""Runtime link guard for MathJax: strip non-allowlisted `href`s from every typeset formula."""

from __future__ import annotations

import re

# Fixed MathJax configuration injected right before the MathJax <script> (both reader-shell and PreserveLayout
# outputs). A `renderActions` step runs after MathJax has inserted each formula into the page (priority 210, after
# the built-in `update` at 200) and removes every `href` that is not http(s), mailto or an in-page `#anchor`.
#
# It is the runtime backstop for the static LaTeX checks in html_qa.py: it looks at the links MathJax actually
# built, so it holds whatever TeX produced them (`\href`, `\mmlToken`, tricks nobody has thought of yet). The
# printed PDF is covered too, because headless Edge prints after typesetting. MathJax's own `ui/safe` extension is
# not used: its protocol test (`/^\s*([a-z]+):/`) treats `search-ms:` / `ms-settings:` (hyphenated) as relative
# URLs and lets them through, and it allows `file:` by default.
MATHJAX_LINK_GUARD_BODY = """
(function () {
    var SAFE = /^\\s*(?:https?:|mailto:|#)/i;
    function clean(root) {
        if (!root || !root.querySelectorAll) return;
        var nodes = root.querySelectorAll('[href]');
        for (var i = 0; i < nodes.length; i++) {
            if (!SAFE.test(nodes[i].getAttribute('href') || '')) nodes[i].removeAttribute('href');
        }
    }
    window.MathJax = {
        options: {
            renderActions: {
                maxLukaLinkGuard: [
                    210,
                    function () {
                        var boxes = document.querySelectorAll('mjx-container');
                        for (var i = 0; i < boxes.length; i++) clean(boxes[i]);
                    },
                    function (math) { clean(math.typesetRoot); }
                ]
            }
        }
    };
})();
"""

MATHJAX_LINK_GUARD_TAG = f'<script data-max-luka-mathjax-guard="1">{MATHJAX_LINK_GUARD_BODY}</script>\n'

# Comments, scripts, styles and textareas, as in reader_shell: a MathJax tag is only real outside comments/textareas.
_HTML_SEGMENTS_RX = re.compile(
    r"(?is)<!--.*?-->|<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<textarea\b[^>]*>.*?</textarea>"
)
_MATHJAX_SCRIPT_OPEN_RX = re.compile(
    r"""(?is)^<script\b[^>]*?\bsrc\s*=\s*(?:"[^"]*mathjax[^"]*"|'[^']*mathjax[^']*'|[^\s>]*mathjax[^\s>]*)[^>]*>"""
)


def inject_mathjax_link_guard(html_text: str) -> tuple[str, bool]:
    """Idempotently place the link guard immediately before the first MathJax <script src>; no-op without MathJax."""
    cleaned = html_text.replace(MATHJAX_LINK_GUARD_TAG, "")
    for seg in _HTML_SEGMENTS_RX.finditer(cleaned):
        if _MATHJAX_SCRIPT_OPEN_RX.match(seg.group(0)):
            return cleaned[: seg.start()] + MATHJAX_LINK_GUARD_TAG + cleaned[seg.start() :], True
    return cleaned, False
