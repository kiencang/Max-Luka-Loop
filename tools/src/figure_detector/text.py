"""Phase 1 — page text analysis: caption classification, dict-block splitting, `analyze_page()`."""

from __future__ import annotations

import math

from .geometry import (
    _horiz_overlap,
)
from .model import (
    _COMMA_PROSE_AFTER_NUM_RE,
    _FIG_CAPTION_RE,
    _INLINE_REF_AFTER_NUM_RE,
    _LEAD_TRIM_RE,
    _PLURAL_CAPTION_NOUN_RE,
    _PLURAL_PROSE_AFTER_NUM_RE,
    _PROSE_AFTER_NUM_RE,
    _SECTION_HEADING_RE,
    _SUBPANEL_LABEL_RE,
    _TAB_CAPTION_RE,
    _TICK_TOKEN_RE,
    DEFAULT_CONFIG,
    DetectorConfig,
    PageContext,
    TextBlock,
    _ensure_pymupdf,
    pymupdf,
)


def _clean_text(text: str) -> str:
    """Collapse internal newlines/whitespace and normalize common PDF ligatures."""
    return (
        " ".join(text.strip().split())
        .replace("ﬁ", "fi")
        .replace("ﬂ", "fl")
        .replace("ﬀ", "ff")
        .replace("ﬃ", "ffi")
        .replace("ﬄ", "ffl")
    )


def _is_prose_after_label(cleaned: str, label_end: int) -> bool:
    """Return True when lowercase running prose (never capitalized caption titles) follows a label."""
    tail = cleaned[label_end:]
    if tail == "." or _INLINE_REF_AFTER_NUM_RE.match(tail):
        return True
    if _PROSE_AFTER_NUM_RE.match(tail) or _COMMA_PROSE_AFTER_NUM_RE.match(tail):
        return True
    return bool(
        _PLURAL_CAPTION_NOUN_RE.match(cleaned) and _PLURAL_PROSE_AFTER_NUM_RE.match(tail)
    )


def _classify_text_block(text: str) -> str:
    """Classify a text block as figure caption, table caption, or regular text."""
    collapsed = _clean_text(text)
    if not collapsed:
        return "text"
    cleaned = _LEAD_TRIM_RE.sub("", collapsed)
    fig_m = _FIG_CAPTION_RE.match(cleaned)
    if fig_m and not _is_prose_after_label(cleaned, fig_m.end()):
        return "fig_caption"
    tab_m = _TAB_CAPTION_RE.match(cleaned)
    if tab_m and not _is_prose_after_label(cleaned, tab_m.end()):
        return "tab_caption"
    return "text"


def _split_dict_block(blk: dict, cfg: DetectorConfig = DEFAULT_CONFIG) -> list[TextBlock]:
    """Split a PyMuPDF dict block across horizontal column jumps or mid-block captions."""
    _ensure_pymupdf()
    raw_lines: list[tuple[pymupdf.Rect, str]] = []
    for ln in blk.get("lines", ()):
        txt = "".join(s.get("text", "") for s in ln.get("spans", ())).strip()
        if not txt:
            continue
        r = pymupdf.Rect(ln["bbox"])
        if not r.is_empty:
            raw_lines.append((r, txt))

    if not raw_lines:
        return []

    groups: list[list[tuple[pymupdf.Rect, str]]] = []
    cur: list[tuple[pymupdf.Rect, str]] = []
    cur_rect: pymupdf.Rect | None = None

    for lr, ltxt in raw_lines:
        if not cur or cur_rect is None:
            cur = [(lr, ltxt)]
            cur_rect = pymupdf.Rect(lr)
            continue

        gap_x = max(cur_rect.x0, lr.x0) - min(cur_rect.x1, lr.x1)
        prev_r, prev_txt = cur[-1]
        cur_kind = _classify_text_block("\n".join(t for _, t in cur))
        line_kind = _classify_text_block(ltxt)
        caption_split = line_kind in ("fig_caption", "tab_caption") and (
            cur_kind == "text"
            or prev_txt.rstrip().endswith((".", "!", "?"))
            or (lr.y0 - prev_r.y1) >= 4.0
        )
        if gap_x >= cfg.col_split_gap_x or caption_split:
            groups.append(cur)
            cur = [(lr, ltxt)]
            cur_rect = pymupdf.Rect(lr)
        else:
            cur.append((lr, ltxt))
            cur_rect = cur_rect | lr

    if cur:
        groups.append(cur)

    result: list[TextBlock] = []
    for grp in groups:
        grp_rect = pymupdf.Rect(grp[0][0])
        for r, _ in grp[1:]:
            grp_rect = grp_rect | r
        joined = "\n".join(t for _, t in grp)
        result.append(TextBlock(grp_rect, joined, _classify_text_block(joined)))
    return result


def _merge_caption_continuations(
    blocks: list[TextBlock],
    rules: list[pymupdf.Rect],
    cfg: DetectorConfig = DEFAULT_CONFIG,
) -> list[TextBlock]:
    """Re-attach continuation lines of a multi-line caption split into adjacent dict blocks."""
    if len(blocks) < 2:
        return blocks

    consumed: set[int] = set()
    changed = True
    while changed:
        changed = False
        for i, cap in enumerate(blocks):
            if i in consumed or cap.kind not in ("fig_caption", "tab_caption"):
                continue
            cap_clean = _clean_text(cap.text)
            cap_ends_sentence = cap_clean.endswith((".", "!", "?"))

            best_j: int | None = None
            best_gap = cfg.caption_cont_max_gap_y + 0.1
            for j, nxt in enumerate(blocks):
                if j == i or j in consumed or nxt.kind != "text":
                    continue
                gap_y = nxt.rect.y0 - cap.rect.y1
                if not (-2.0 <= gap_y <= cfg.caption_cont_max_gap_y):
                    continue
                if nxt.rect.x0 < cap.rect.x0 - 10.0 or nxt.rect.x0 > cap.rect.x0 + 60.0:
                    continue
                if nxt.rect.x1 > cap.rect.x1 + 35.0:
                    continue
                if _horiz_overlap(cap.rect, nxt.rect) < 0.35 * min(cap.rect.width, nxt.rect.width):
                    continue
                nxt_clean = _clean_text(nxt.text)
                if not nxt_clean:
                    continue
                if cap_ends_sentence and not (nxt_clean[0].islower() or nxt_clean[0] in "(["):
                    continue
                if any(
                    rr.height <= 4.0
                    and cap.rect.y1 - 1.0 <= rr.y0 <= nxt.rect.y0 + 1.0
                    and _horiz_overlap(rr, cap.rect | nxt.rect) >= 0.4 * cap.rect.width
                    for rr in rules
                ):
                    continue
                if gap_y < best_gap:
                    best_gap = gap_y
                    best_j = j

            if best_j is not None:
                nxt = blocks[best_j]
                cap.rect = cap.rect | nxt.rect
                cap.text = cap.text.rstrip() + "\n" + nxt.text.lstrip()
                cap.word_count = len(cap.text.split())
                consumed.add(best_j)
                changed = True

    return [b for idx, b in enumerate(blocks) if idx not in consumed]


def _collect_separator_rules(drawings: list[dict], pw: float, ph: float) -> list[pymupdf.Rect]:
    """Identify long thin horizontal/vertical rules used as table/section dividers."""
    rules: list[pymupdf.Rect] = []
    for dr in drawings:
        r = dr["rect"]
        if r.height <= 4.0 and r.width >= 0.25 * pw:
            rules.append(r)
        elif r.width <= 4.0 and r.height >= 0.30 * ph:
            rules.append(r)
    return rules


def analyze_page(page: pymupdf.Page, cfg: DetectorConfig = DEFAULT_CONFIG) -> PageContext:
    """Phase 1: Build reusable `PageContext` once per page."""
    _ensure_pymupdf()
    page_rect = page.rect
    pw, ph = page_rect.width, page_rect.height

    drawings = page.get_drawings()
    rules = _collect_separator_rules(drawings, pw, ph) if drawings else []

    raw_blocks: list[TextBlock] = []
    for b in page.get_text("dict").get("blocks", ()):
        if b.get("type") != 0:
            continue
        raw_blocks.extend(_split_dict_block(b, cfg=cfg))
    text_blocks = _merge_caption_continuations(raw_blocks, rules, cfg=cfg)

    fig_captions = [tb for tb in text_blocks if tb.kind == "fig_caption"]
    tab_captions = [tb for tb in text_blocks if tb.kind == "tab_caption"]
    words = page.get_text("words")
    word_rects = [pymupdf.Rect(w[:4]) for w in words]

    return PageContext(
        page=page,
        page_rect=page_rect,
        pw=pw,
        ph=ph,
        text_blocks=text_blocks,
        fig_captions=fig_captions,
        tab_captions=tab_captions,
        words=words,
        word_rects=word_rects,
        drawings=drawings,
        separator_rules=rules,
    )


def _is_short_axis_label(tb: TextBlock, vertical_ok: bool = False) -> bool:
    """Return True for compact axis titles, rotated Y labels, tick-value rows, or subpanel markers."""
    if tb.kind != "text":
        return False
    cleaned = _clean_text(tb.text)
    if not cleaned or _SECTION_HEADING_RE.match(cleaned):
        return False
    tokens = cleaned.split()
    if vertical_ok and tb.rect.width <= 32.0 and (
        tb.rect.height >= 1.4 * tb.rect.width or (tb.rect.height <= 42.0 and len(tokens) <= 8)
    ):
        return True
    if tb.rect.height <= 30.0 and len(tokens) <= 4 and not cleaned.endswith("."):
        return True
    # Narrow inline math/chemical/axis label whose subscripts/superscripts split into extra short tokens
    if tb.rect.width <= 115.0 and tb.rect.height <= 26.0 and len(tokens) <= 10 and not cleaned.endswith("."):
        return True
    if tb.rect.height <= 26.0 and len(tokens) <= 12:
        tick_hits = sum(1 for tok in tokens if _TICK_TOKEN_RE.match(tok))
        if tick_hits >= max(2, int(math.ceil(0.60 * len(tokens)))):
            return True
    if tb.rect.height <= 26.0 and len(tokens) <= 16 and _SUBPANEL_LABEL_RE.match(cleaned):
        return True
    return False
