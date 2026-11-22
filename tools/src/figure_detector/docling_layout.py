"""Docling's layout post-processing, rule-based reading order and caption/footnote relations, without Docling.

Egret only proposes labelled boxes. What Docling does with them afterwards is ported here so the manifest
says what Docling would say about each picture:

- `postprocess_layout`  <- docling/utils/layout_postprocessor.py (`LayoutPostprocessor.postprocess`):
  thresholds, text-cell assignment, orphan text, overlap groups, picture/table/container handling;
- `reading_order`       <- docling/models/postprocessing/reading_order_rb.py (`ReadingOrderPredictor`)
  and the container nesting of docling/models/stages/reading_order/readingorder_model.py;
- `match_captions`, `match_footnotes` <- `ReadingOrderPredictor._find_to_captions` / `_find_to_footnotes`;
- `inside_table`        <- `ReadingOrderModel._match_table_pictures` (first gate, see below);
- `_Node` predicates    <- docling_core/types/doc/base.py (`BoundingBox`, bottom-left origin).

Sources and licenses (MIT):
    docling-slim 2.151.1 — Copyright The Docling Contributors; full text in licenses/docling-MIT.txt.
    docling-core 2.108.0 — Copyright (c) 2024 International Business Machines; licenses/docling-core-MIT.txt.

Docling also runs OCR on bitmap regions by default; there is no OCR here, so a scanned page has no text
cells and its pictures get no caption.

Differences from upstream, all because the rest of Docling is not here:
- text cells are PyMuPDF text lines in PyMuPDF order (Docling uses docling-parse text lines);
- R-tree queries are brute-force scans with the same inclusive rectangle test;
- page separators are off, as in Docling's default (`ReadingOrderOptions.use_page_separators = False`);
- there is no TableFormer, so a picture counts as sitting in a table when at least 80% of it lies inside
  the Table box — Docling's first gate before it looks for the table cell.
Keep the logic in step with upstream rather than tuning it locally.
"""

from __future__ import annotations

import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field, replace
from functools import cmp_to_key
from itertools import islice, takewhile

from .model import pymupdf

# ---- LayoutPostprocessor constants ----
CONFIDENCE_THRESHOLDS = {  # kept when score >= threshold
    "Caption": 0.5, "Footnote": 0.5, "Formula": 0.5, "List-item": 0.5, "Page-footer": 0.5, "Page-header": 0.5,
    "Picture": 0.5, "Section-header": 0.45, "Table": 0.5, "Text": 0.5, "Title": 0.45, "Code": 0.45,
    "Checkbox-Selected": 0.45, "Checkbox-Unselected": 0.45, "Form": 0.45, "Key-Value Region": 0.45,
    "Document Index": 0.45,
}
LABEL_REMAPPING = {"Title": "Section-header"}
OVERLAP_PARAMS = {
    "regular": {"area_threshold": 1.3, "conf_threshold": 0.05},
    "picture": {"area_threshold": 2.0, "conf_threshold": 0.3},
    "wrapper": {"area_threshold": 2.0, "conf_threshold": 0.2},
}
OVERLAP_IOU = 0.8            # _remove_overlapping_clusters(overlap_threshold=0.8)
OVERLAP_CONTAINMENT = 0.8    # _remove_overlapping_clusters(containment_threshold=0.8)
COINCIDENT_IOU = 0.8         # _resolve_coincident_pairs(iou_threshold=0.8)
COINCIDENT_CONF_TOLERANCE = 0.1  # _resolve_coincident_pairs(conf_tolerance=0.1)
FULL_PAGE_PICTURE_RATIO = 0.9    # pictures covering > 90% of the page are dropped
CHILD_CONTAINMENT = 0.8          # regular clusters > 80% inside a picture/table become its children
CELL_MIN_OVERLAP = 0.2           # _assign_cells_to_clusters(min_overlap=0.2)
CONTAINER_TYPES = {"Form", "Key-Value Region"}
TABLE_TYPES = {"Table", "Document Index"}
SPECIAL_TYPES = CONTAINER_TYPES | TABLE_TYPES | {"Picture"}

# ---- ReadingOrderPredictor / ReadingOrderModel constants ----
GRAPHIC_LABELS = {"Table", "Picture", "Code"}
HORIZONTAL_DILATION_THRESHOLD_NORM = 0.15
VERTICAL_OVERLAP_IOU_THRESHOLD = 0.8
RTREE_QUERY_PADDING = 0.1
NEAR_VERTICAL_OVERLAP_THRESHOLD_NORM = 0.0025
LEFT_EDGE_ALIGNMENT_THRESHOLD_NORM = 0.01
INTERRUPTION_QUERY_PADDING = 1.0
RICH_CELL_PICTURE_COVERAGE_THRESHOLD = 0.8


@dataclass(eq=False)
class TextCell:
    index: int
    rect: pymupdf.Rect
    text: str


@dataclass(eq=False)
class Cluster:
    id: int
    label: str
    rect: pymupdf.Rect
    score: float
    cells: list[TextCell] = field(default_factory=list)
    children: list[Cluster] = field(default_factory=list)

    @property
    def text(self) -> str:
        """`PageAssembleModel.sanitize_text(cell_text_lines(cells))`."""
        return sanitize_text(cell_text_lines(self.cells))


# ---- docling/utils/text_normalization.py and PageAssembleModel.sanitize_text ----
_TYPOGRAPHIC_MAP = {"\u2044": "/", "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2022": "\u00b7"}
_LIGATURE_MAP = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st", "\u0132": "IJ", "\u0133": "ij", "\uf0a0": ""}
_LIGATURE_RE = re.compile("([\ufb00-\ufb06]|\u0132|\u0133|\uf0a0)( (?=\\w))?")
_ARABIC_PRESENTATION_RE = re.compile("[\ufb50-\ufdff\ufe70-\ufeff]+")


def cell_text_lines(cells: list[TextCell]) -> list[str]:
    return [c.text.replace("\x02", "-").strip() for c in cells if len(c.text.strip()) > 0]


def normalize_extracted_text(text: str) -> str:
    for raw, clean in _TYPOGRAPHIC_MAP.items():
        text = text.replace(raw, clean)
    text = _LIGATURE_RE.sub(
        lambda m: _LIGATURE_MAP[m.group(1)] + ("" if "\ufb00" <= m.group(1) <= "\ufb06" else (m.group(2) or "")),
        text,
    )
    return _ARABIC_PRESENTATION_RE.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)


def sanitize_text(lines: list[str]) -> str:
    """Join lines with a space, closing up a hyphen that splits a word over the line break."""
    if not lines:
        return ""
    lines = list(lines)
    for ix, line in enumerate(lines[1:]):
        prev = lines[ix]
        if prev.endswith("-"):
            prev_words = re.findall(r"\b[\w]+\b", prev)
            line_words = re.findall(r"\b[\w]+\b", line)
            attached = len(prev) > 1 and prev[-2].isalnum()
            if (
                attached and prev_words and line_words and prev_words[-1].isalnum() and len(prev_words[-1]) > 1
                and line_words[0].isalnum() and not line_words[0][0].isdigit()
            ):
                lines[ix] = prev[:-1]
            elif not attached:
                lines[ix] += " "
        else:
            lines[ix] += " "
    return normalize_extracted_text("".join(lines)).strip()


def page_cells(page: pymupdf.Page) -> list[TextCell]:
    """Text lines of the page in extraction order — the stand-in for Docling's textline cells."""
    cells: list[TextCell] = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT).get("blocks", ()):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", ()):
            text = "".join(span.get("text", "") for span in line.get("spans", ()))
            rect = pymupdf.Rect(line["bbox"])
            if text.strip() and not rect.is_empty:
                cells.append(TextCell(len(cells), rect, text))
    return cells


# ---- geometry (top-left origin, pymupdf.Rect) ----


def _area(r: pymupdf.Rect) -> float:
    return max(0.0, r.width) * max(0.0, r.height)


def _inter(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    return max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))


def ios(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    """`a.intersection_over_self(b)`: share of `a` lying inside `b`."""
    return _inter(a, b) / _area(a) if _area(a) > 1.0e-6 else 0.0


def _iou(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    inter = _inter(a, b)
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def _check_overlap(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    if _area(a) <= 0 or _area(b) <= 0:
        return False
    return _iou(a, b) > OVERLAP_IOU or ios(a, b) > OVERLAP_CONTAINMENT or ios(b, a) > OVERLAP_CONTAINMENT


# ---- LayoutPostprocessor ----


@dataclass
class PageLayout:
    clusters: list[Cluster]  # final clusters in Docling's assembly order (`_sort_clusters(mode="id")`)

    def of(self, labels: set[str] | str) -> list[Cluster]:
        labels = {labels} if isinstance(labels, str) else labels
        return [c for c in self.clusters if c.label in labels]


def _dedupe_sort(cells: list[TextCell]) -> list[TextCell]:
    seen: set[int] = set()
    out = []
    for c in cells:
        if c.index not in seen:
            seen.add(c.index)
            out.append(c)
    return sorted(out, key=lambda c: c.index)


def _sort_by_id(clusters: list[Cluster]) -> list[Cluster]:
    return sorted(
        clusters,
        key=lambda c: (min(cell.index for cell in c.cells) if c.cells else sys.maxsize, c.rect.y0, c.rect.x0),
    )


def _should_prefer(cand: Cluster, other: Cluster, params: dict) -> bool:
    other_area = _area(other.rect)
    if cand.label == "List-item" and other.label == "Text" and other_area > 0:
        if abs(1 - _area(cand.rect) / other_area) < 0.2:
            return True
    if cand.label == "Code" and ios(other.rect, cand.rect) > 0.8:
        return True
    area_ratio = _area(cand.rect) / other_area if other_area > 0 else math.inf
    conf_diff = other.score - cand.score
    return not (area_ratio <= params["area_threshold"] and conf_diff > params["conf_threshold"])


def _select_best(group: list[Cluster], params: dict) -> Cluster:
    best = None
    for cand in group:
        if all(other is cand or _should_prefer(cand, other, params) for other in group):
            if best is None or (
                _area(cand.rect) > _area(best.rect) and best.score - cand.score <= params["conf_threshold"]
            ):
                best = cand
    return best if best is not None else group[0]


def _rtree_hit(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    """Inclusive rectangle intersection, as an R-tree `intersection` query."""
    return a.x0 <= b.x1 and b.x0 <= a.x1 and a.y0 <= b.y1 and b.y0 <= a.y1


def _remove_overlapping(clusters: list[Cluster], kind: str, index: dict[int, pymupdf.Rect]) -> list[Cluster]:
    """Union-find groups of overlapping boxes; each group keeps its best box, which takes the others' cells.

    `index` plays Docling's `SpatialClusterIndex`: built once from the raw boxes, so candidates are found by
    their original box (and orphan text clusters, never indexed, are only found from their own side).
    """
    if not clusters:
        return []
    params = OVERLAP_PARAMS[kind]
    parent = list(range(len(clusters)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, c in enumerate(clusters):
        for j, o in enumerate(clusters):
            if i == j or o.id not in index or not _rtree_hit(index[o.id], c.rect):
                continue
            if _check_overlap(c.rect, o.rect):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list[Cluster]] = {}
    for i, c in enumerate(clusters):
        groups.setdefault(find(i), []).append(c)
    result = []
    for group in groups.values():
        if len(group) == 1:
            result.append(group[0])
            continue
        best = _select_best(group, params)
        for c in group:
            if c is not best:
                best.cells.extend(c.cells)
        best.cells = _dedupe_sort(best.cells)
        result.append(best)
    return result


def _assign_cells(clusters: list[Cluster], cells: list[TextCell]) -> None:
    for c in clusters:
        c.cells = []
    for cell in cells:
        if not cell.text.strip() or _area(cell.rect) <= 0:
            continue
        best_overlap = CELL_MIN_OVERLAP
        best = None
        for c in clusters:
            overlap = ios(cell.rect, c.rect)
            if overlap > best_overlap:
                best_overlap = overlap
                best = c
        if best is not None:
            best.cells.append(cell)
    for c in clusters:
        c.cells = _dedupe_sort(c.cells)


def _adjust_bboxes(clusters: list[Cluster]) -> None:
    for c in clusters:
        if not c.cells:
            continue
        cells_box = pymupdf.Rect(
            min(cell.rect.x0 for cell in c.cells), min(cell.rect.y0 for cell in c.cells),
            max(cell.rect.x1 for cell in c.cells), max(cell.rect.y1 for cell in c.cells),
        )
        if c.label in ("Table", "Checkbox-Selected", "Checkbox-Unselected"):
            c.rect = c.rect | cells_box
        else:
            c.rect = cells_box


def _process_regular(regular: list[Cluster], cells: list[TextCell], next_id: int) -> list[Cluster]:
    index = {c.id: pymupdf.Rect(c.rect) for c in regular}
    clusters = [c for c in regular if c.score >= CONFIDENCE_THRESHOLDS[c.label]]
    for c in clusters:
        c.label = LABEL_REMAPPING.get(c.label, c.label)
    _assign_cells(clusters, cells)
    clusters = [c for c in clusters if c.cells or c.label == "Formula"]
    assigned = {cell.index for c in clusters for cell in c.cells}
    unassigned = [cell for cell in cells if cell.index not in assigned and cell.text.strip()]
    clusters.extend(
        Cluster(next_id + i, "Text", pymupdf.Rect(cell.rect), 1.0, [cell]) for i, cell in enumerate(unassigned)
    )
    prev_count = len(clusters) + 1
    for _ in range(3):
        if prev_count == len(clusters):
            break
        prev_count = len(clusters)
        _adjust_bboxes(clusters)
        clusters = _remove_overlapping(clusters, "regular", index)
    return clusters


def _coincident_losers(losers: list[Cluster], winners: list[Cluster]) -> set[int]:
    drop: set[int] = set()
    for loser in losers:
        for winner in winners:
            if _iou(loser.rect, winner.rect) <= COINCIDENT_IOU:
                continue
            if loser.score - winner.score < COINCIDENT_CONF_TOLERANCE:
                drop.add(loser.id)
                break
    return drop


def _handle_cross_type_overlaps(special: list[Cluster]) -> list[Cluster]:
    """Table loses to Document Index, Picture to Table/Document Index, containers to all of them,
    when the boxes are near-identical and the loser is not clearly (>= 0.1) more confident."""
    tables = [c for c in special if c.label == "Table"]
    indexes = [c for c in special if c.label == "Document Index"]
    pictures = [c for c in special if c.label == "Picture"]
    containers = [c for c in special if c.label in CONTAINER_TYPES]
    drop = _coincident_losers(tables, indexes)
    drop |= _coincident_losers(pictures, tables + indexes)
    surviving = [c for c in tables + indexes + pictures if c.id not in drop]
    drop |= _coincident_losers(containers, surviving)
    return [c for c in special if c.id not in drop]


def _set_children(cluster: Cluster, children: list[Cluster]) -> None:
    if not children:
        return
    cluster.children = _sort_by_id(children)
    if cluster.label in CONTAINER_TYPES:
        cluster.rect = pymupdf.Rect(
            min(c.rect.x0 for c in children), min(c.rect.y0 for c in children),
            max(c.rect.x1 for c in children), max(c.rect.y1 for c in children),
        )
    cluster.cells = _dedupe_sort([cell for child in cluster.children for cell in child.cells])


def _smallest_container(child: Cluster, containers: list[Cluster]) -> Cluster | None:
    parents = [c for c in containers if ios(child.rect, c.rect) > CHILD_CONTAINMENT]
    return min(parents, key=lambda c: (_area(c.rect), -c.score, c.id)) if parents else None


def _process_special(special: list[Cluster], regular: list[Cluster], page_rect: pymupdf.Rect) -> list[Cluster]:
    picture_index = {c.id: pymupdf.Rect(c.rect) for c in special if c.label == "Picture"}
    wrapper_index = {c.id: pymupdf.Rect(c.rect) for c in special if c.label != "Picture"}
    special = [c for c in special if c.score >= CONFIDENCE_THRESHOLDS[c.label]]
    page_area = _area(page_rect)
    if page_area > 0:
        special = [
            c for c in special if not (c.label == "Picture" and _area(c.rect) / page_area > FULL_PAGE_PICTURE_RATIO)
        ]
    pictures = _remove_overlapping([c for c in special if c.label == "Picture"], "picture", picture_index)
    tables = _remove_overlapping([c for c in special if c.label in TABLE_TYPES], "wrapper", wrapper_index)
    containers = _remove_overlapping([c for c in special if c.label in CONTAINER_TYPES], "wrapper", wrapper_index)
    special = _handle_cross_type_overlaps(pictures + tables + containers)
    pictures = [c for c in special if c.label == "Picture"]
    tables = [c for c in special if c.label in TABLE_TYPES]
    containers = [c for c in special if c.label in CONTAINER_TYPES]

    nested = tables + pictures
    for c in nested:
        _set_children(c, [r for r in regular if ios(r.rect, c.rect) > CHILD_CONTAINMENT])
    parent_of_nested = {c.id: p.id for c in nested if (p := _smallest_container(c, containers))}
    nested_regular = {r.id for c in nested for r in c.children}
    parent_of_regular = {
        r.id: p.id for r in regular if r.id not in nested_regular and (p := _smallest_container(r, containers))
    }
    for cont in containers:
        direct = [r for r in regular if parent_of_regular.get(r.id) == cont.id]
        inner = [c for c in nested if parent_of_nested.get(c.id) == cont.id]
        _set_children(cont, direct + inner)
    return pictures + tables + containers


def postprocess_layout(dets, cells: list[TextCell], page_rect: pymupdf.Rect) -> PageLayout:
    """`LayoutPostprocessor.postprocess` on Egret detections (`egret.Detection`, page coordinates)."""
    clusters = []
    for i, d in enumerate(dets):
        x0, y0, x1, y1 = d.box
        rect = pymupdf.Rect(
            min(max(x0, page_rect.x0), page_rect.x1), min(max(y0, page_rect.y0), page_rect.y1),
            min(max(x1, page_rect.x0), page_rect.x1), min(max(y1, page_rect.y0), page_rect.y1),
        )
        clusters.append(Cluster(i, d.name, rect, float(d.score)))
    regular = _process_regular([c for c in clusters if c.label not in SPECIAL_TYPES], cells, max((c.id for c in clusters), default=0) + 1)
    special = _process_special([c for c in clusters if c.label in SPECIAL_TYPES], regular, page_rect)
    contained = {ch.id for w in special if w.label in TABLE_TYPES or w.label == "Picture" for ch in w.children}
    regular = [c for c in regular if c.id not in contained]
    return PageLayout(_sort_by_id(regular + special))


# ---- ReadingOrderPredictor (bottom-left origin, as upstream) ----


@dataclass(eq=False)
class _Node:
    cid: int
    label: str
    l: float  # noqa: E741 - names follow docling_core.BoundingBox
    b: float
    r: float
    t: float
    pw: float
    ph: float

    def overlaps_horizontally(self, o) -> bool:
        return not (self.r <= o.l or o.r <= self.l)

    def overlaps_vertically(self, o) -> bool:
        return not (self.t <= o.b or o.t <= self.b)

    def overlaps(self, o) -> bool:
        return self.overlaps_horizontally(o) and self.overlaps_vertically(o)

    def overlaps_vertically_with_iou(self, o, iou: float) -> bool:
        if not self.overlaps_vertically(o):
            return False
        u0, u1 = min(self.b, o.b), max(self.t, o.t)
        i0, i1 = max(self.b, o.b), min(self.t, o.t)
        return (i1 - i0) / (u1 - u0) > iou

    def is_strictly_left_of(self, o, eps: float = 0.001) -> bool:
        return (self.r + eps) < o.l

    def is_strictly_above(self, o, eps: float = 1.0e-3) -> bool:
        return (self.b + eps) > o.t

    def follows_maintext_order(self, o) -> bool:
        return self.cid + 1 == o.cid

    def __lt__(self, o) -> bool:
        if self.overlaps_horizontally(o):
            return self.b > o.b
        return self.l < o.l

    @property
    def width(self) -> float:
        return self.r - self.l

    @property
    def height(self) -> float:
        return self.t - self.b


def _hits(n: _Node, q: tuple[float, float, float, float]) -> bool:
    """R-tree `intersection(q)` test (inclusive) for a node inserted as (l, b, r, t)."""
    return n.l <= q[2] and n.r >= q[0] and n.b <= q[3] and n.t >= q[1]


@dataclass
class _State:
    h2i: dict[int, int] = field(default_factory=dict)
    l2r: dict[int, int] = field(default_factory=dict)
    r2l: dict[int, int] = field(default_factory=dict)
    up: dict[int, list[int]] = field(default_factory=dict)
    dn: dict[int, list[int]] = field(default_factory=dict)
    heads: list[int] = field(default_factory=list)


def _has_node_between(nodes: list[_Node], li: int, ri: int) -> bool:
    left, right = nodes[li], nodes[ri]
    bottom, top = max(left.b, right.b), min(left.t, right.t)
    return any(
        k not in (li, ri) and left.r < e.r and e.l < right.l and bottom < e.t and e.b < top
        for k, e in enumerate(nodes)
    )


def _init_l2r(nodes: list[_Node], st: _State) -> None:
    st.l2r, st.r2l = {}, {}
    for i, a in enumerate(nodes):
        for j, b in enumerate(nodes):
            if (
                a.follows_maintext_order(b)
                and a.is_strictly_left_of(b)
                and a.overlaps_vertically_with_iou(b, VERTICAL_OVERLAP_IOU_THRESHOLD)
                and not _has_node_between(nodes, i, j)
            ):
                st.l2r[i] = j
                st.r2l[j] = i


def _has_sequence_interruption(nodes: list[_Node], i: int, j: int) -> bool:
    a, b = nodes[i], nodes[j]
    x0 = min(a.l, b.l) - INTERRUPTION_QUERY_PADDING
    x1 = max(a.r, b.r) + INTERRUPTION_QUERY_PADDING
    y0, y1 = sorted((b.t, a.b))
    for w, e in enumerate(nodes):
        if w in (i, j) or not _hits(e, (x0, y0, x1, y1)):
            continue
        if (a.overlaps_horizontally(e) or b.overlaps_horizontally(e)) and a.is_strictly_above(e) and e.is_strictly_above(b):
            return True
    return False


def _init_ud(nodes: list[_Node], st: _State) -> None:
    st.up = {i: [] for i in range(len(nodes))}
    st.dn = {i: [] for i in range(len(nodes))}
    for j, b in enumerate(nodes):
        if j in st.r2l:
            left = st.r2l[j]
            if j not in st.dn[left]:
                st.dn[left].append(j)
            if left not in st.up[j]:
                st.up[j].append(left)
        query = (b.l - RTREE_QUERY_PADDING, b.t, b.r + RTREE_QUERY_PADDING, math.inf)
        for i, a in enumerate(nodes):
            if i == j or not _hits(a, query):
                continue
            if not (a.is_strictly_above(b) and a.overlaps_horizontally(b)):
                continue
            if not _has_sequence_interruption(nodes, i, j):
                while i in st.l2r:
                    i = st.l2r[i]
                st.dn[i].append(j)
                st.up[j].append(i)
    # Consecutive text boxes in a column can overlap slightly at their edges: keep their source sequence.
    by_cid = {n.cid: k for k, n in enumerate(nodes)}
    for i, upper in enumerate(nodes):
        if upper.label in GRAPHIC_LABELS:
            continue
        j = by_cid.get(upper.cid + 1)
        if j is None:
            continue
        lower = nodes[j]
        if lower.label in GRAPHIC_LABELS:
            continue
        tol = upper.ph * NEAR_VERTICAL_OVERLAP_THRESHOLD_NORM
        if (
            abs(upper.l - lower.l) < upper.pw * LEFT_EDGE_ALIGNMENT_THRESHOLD_NORM
            and upper.b < lower.t <= upper.b + tol
            and upper.t > lower.t
            and upper.b > lower.b
            and j not in st.dn[i]
        ):
            st.dn[i].append(j)
            st.up[j].append(i)


def _one_to_one(st: _State, upper: int, lower: int) -> bool:
    return st.dn.get(upper) == [lower] and st.up.get(lower) == [upper]


def _dilate(nodes: list[_Node], st: _State) -> list[_Node]:
    th = HORIZONTAL_DILATION_THRESHOLD_NORM * nodes[0].pw if nodes else 0.0
    dilated = [replace(n) for n in nodes]
    for i, d in enumerate(dilated):
        x0, y0, x1, y1 = d.l, d.b, d.r, d.t
        if st.up.get(i):
            k = st.up[i][0]
            if _one_to_one(st, k, i):
                x0d, x1d = min(x0, nodes[k].l), max(x1, nodes[k].r)
                if (x0 - x0d) > th or (x1d - x1) > th:
                    continue
                x0, x1 = x0d, x1d
        if st.dn.get(i):
            k = st.dn[i][0]
            if _one_to_one(st, i, k):
                x0d, x1d = min(x0, nodes[k].l), max(x1, nodes[k].r)
                if (x0 - x0d) > th or (x1d - x1) > th:
                    continue
                x0, x1 = x0d, x1d
        box = replace(d, l=x0, b=y0, r=x1, t=y1)
        if not any(j != i and n.overlaps(box) for j, n in enumerate(nodes)):
            d.l, d.b, d.r, d.t = x0, y0, x1, y1
    return dilated


def _is_separated_above(nodes: list[_Node], upper: _Node, lower: _Node) -> bool:
    if upper.overlaps_horizontally(lower) or not upper.is_strictly_above(lower):
        return False
    y0, y1 = sorted((lower.t, upper.b))
    q = (min(upper.l, lower.l), y0, max(upper.r, lower.r), y1)
    return any(
        w.cid not in (upper.cid, lower.cid)
        and _hits(w, q)
        and upper.is_strictly_above(w)
        and w.is_strictly_above(lower)
        and w.overlaps_horizontally(upper)
        and w.overlaps_horizontally(lower)
        for w in nodes
    )


def _find_heads(nodes: list[_Node], st: _State) -> None:
    heads = [nodes[k] for k, ups in st.up.items() if not ups]

    def compare(a: _Node, b: _Node) -> int:
        if _is_separated_above(nodes, a, b):
            return -1
        if _is_separated_above(nodes, b, a):
            return 1
        return -1 if a < b else 1

    st.heads = [st.h2i[n.cid] for n in sorted(heads, key=cmp_to_key(compare))]


def _sort_ud(nodes: list[_Node], st: _State) -> None:
    for m in (st.up, st.dn):
        for k, idxs in m.items():
            m[k] = [st.h2i[n.cid] for n in sorted(nodes[i] for i in idxs)]


def _dfs_up(j: int, visited: list[bool], st: _State) -> int:
    k = j
    walked = {j}
    while True:
        for i in st.up[k]:
            if not visited[i] and i not in walked:
                k = i
                walked.add(i)
                break
        else:
            return k


def _dfs_down(j: int, order: list[int], visited: list[bool], st: _State) -> None:
    stack: list[tuple[list[int], int]] = [(st.dn[j], 0)]
    while stack:
        idxs, offset = stack[-1]
        found = False
        for new_offset, i in enumerate(idxs[offset:]):
            k = _dfs_up(i, visited, st)
            if not visited[k]:
                order.append(k)
                visited[k] = True
                stack[-1] = (idxs, new_offset + 1)  # sic: upstream resumes relative to the slice
                stack.append((st.dn[k], 0))
                found = True
                break
        if not found:
            stack.pop()


def _predict_page(nodes: list[_Node]) -> list[_Node]:
    st = _State()
    st.h2i = {n.cid: i for i, n in enumerate(nodes)}
    _init_l2r(nodes, st)
    _init_ud(nodes, st)
    _init_ud(_dilate(nodes, st), st)
    _find_heads(nodes, st)
    _sort_ud(nodes, st)
    order: list[int] = []
    visited = [False] * len(nodes)
    for j in st.heads:
        if not visited[j]:
            order.append(j)
            visited[j] = True
            _dfs_down(j, order, visited, st)
    return [nodes[i] for i in order]


def _predict_reading_order(nodes: list[_Node]) -> list[_Node]:
    """`predict_reading_order` for one page: page headers, then the body, then page footers."""
    headers = [n for n in nodes if n.label == "Page-header"]
    footers = [n for n in nodes if n.label == "Page-footer"]
    body = [n for n in nodes if n.label not in ("Page-header", "Page-footer")]
    return _predict_page(headers) + _predict_page(body) + _predict_page(footers)


def _to_node(cid: int, c: Cluster, page_rect: pymupdf.Rect) -> _Node:
    pw, ph = page_rect.width, page_rect.height
    x0, y0 = c.rect.x0 - page_rect.x0, c.rect.y0 - page_rect.y0
    x1, y1 = c.rect.x1 - page_rect.x0, c.rect.y1 - page_rect.y0
    return _Node(cid, c.label, x0, ph - y1, x1, ph - y0, pw, ph)


def reading_order(layout: PageLayout, page_rect: pymupdf.Rect) -> list[_Node]:
    """Leaves of the page in Docling's reading order; node `cid` is the index in `layout.clusters`.

    Children of a Form / Key-Value container are ordered among themselves and read where the container sits.
    """
    clusters = layout.clusters
    index_of = {c.id: i for i, c in enumerate(clusters)}
    parent: dict[int, int] = {}
    for ci, c in enumerate(clusters):
        if c.label in CONTAINER_TYPES:
            for child in c.children:
                if child.id in index_of:
                    parent.setdefault(index_of[child.id], ci)
    nodes = [_to_node(i, c, page_rect) for i, c in enumerate(clusters)]
    siblings: dict[int | None, list[_Node]] = {None: []}
    for ci, c in enumerate(clusters):
        if c.label in CONTAINER_TYPES:
            siblings.setdefault(ci, [])
    for n in nodes:
        siblings.setdefault(parent.get(n.cid), []).append(n)
    ordered = {k: (_predict_reading_order(v) if len(v) > 1 else v) for k, v in siblings.items()}

    out: list[_Node] = []

    def leaves(key: int | None) -> None:
        for n in ordered[key]:
            if clusters[n.cid].label in CONTAINER_TYPES:
                leaves(n.cid)
            else:
                out.append(n)

    leaves(None)
    return out


# ---- caption / footnote relations ----


def _shortest_gap(a: _Node, b: _Node) -> float:
    dx = max(0.0, (max(a.r, b.r) - min(a.l, b.l)) - a.width - b.width)
    dy = max(0.0, (max(a.t, b.t) - min(a.b, b.b)) - a.height - b.height)
    return math.hypot(dx, dy)


def _graphic_run(nodes) -> list[_Node]:
    return list(takewhile(lambda n: n.label in GRAPHIC_LABELS, nodes))


def _rank_caption_candidates(ordered: list[_Node]) -> dict[int, list[int]]:
    backwards = ordered[::-1]
    size = len(ordered)
    preferred: dict[int, list[int]] = {}
    for ind, cap in enumerate(ordered):
        if cap.label != "Caption":
            continue
        preceding = _graphic_run(islice(backwards, size - ind, None))
        following = _graphic_run(islice(ordered, ind + 1, None))
        ranked = {g.cid: (_shortest_gap(cap, g), side) for side, run in ((0, preceding), (1, following)) for g in run}
        preferred[cap.cid] = sorted(ranked, key=lambda cid: ranked[cid])
    return preferred


def _match_one(cap_cid: int, preferred: dict[int, list[int]], matched: dict[int, int], seen: set[int]) -> dict[int, int]:
    stack = [(cap_cid, iter(preferred[cap_cid]))]
    chain: list[tuple[int, int]] = []
    while stack:
        claimant, cands = stack[-1]
        g = next((cid for cid in cands if cid not in seen), None)
        if g is None:
            stack.pop()
            if chain:
                chain.pop()
            continue
        seen.add(g)
        chain.append((g, claimant))
        held_by = matched.get(g)
        if held_by is None:
            return matched | dict(chain)
        stack.append((held_by, iter(preferred[held_by])))
    return {}


def match_captions(ordered: list[_Node]) -> dict[int, int]:
    """Graphic cid -> caption cid. A caption reaches only the unbroken run of tables/pictures/code next to it in
    reading order, nearest first; augmenting paths let a caption with no other choice displace one that has."""
    preferred = _rank_caption_candidates(ordered)
    matched: dict[int, int] = {}
    for cid in preferred:
        matched = _match_one(cid, preferred, matched, set()) or matched
    return matched


def match_footnotes(ordered: list[_Node]) -> dict[int, list[int]]:
    """Table/picture cid -> the footnotes that directly follow it in reading order."""
    out: dict[int, list[int]] = {}
    for ind, n in enumerate(ordered):
        if n.label in ("Table", "Picture"):
            k = ind + 1
            while k < len(ordered) and ordered[k].label == "Footnote":
                out.setdefault(n.cid, []).append(ordered[k].cid)
                k += 1
    return out


def inside_table(picture: Cluster, layout: PageLayout) -> Cluster | None:
    """The table holding `picture` (>= 80% of the picture inside it), most covering first, else None."""
    covering = [(ios(picture.rect, t.rect), t) for t in layout.of(TABLE_TYPES)]
    covering = [(cov, t) for cov, t in covering if cov >= RICH_CELL_PICTURE_COVERAGE_THRESHOLD]
    return max(covering, key=lambda ct: ct[0])[1] if covering else None
