"""Check that figure_detector/docling_layout.py still behaves exactly like Docling (dev only).

Two steps, because Egret and Docling live in different venvs:

1. `dump` (venv with onnxruntime + tools\\models\\egret_medium.onnx): run Egret on every page and write its raw
   detections and the PyMuPDF text lines to a JSONL file.

       python -X utf8 dev\\egret\\verify_docling_port.py dump --pdf tests\\layout_samples --out %TEMP%\\ro_inputs.jsonl
       python -X utf8 dev\\egret\\verify_docling_port.py dump --doclaynet-test --out %TEMP%\\ro_inputs.jsonl

   `--doclaynet-test` reads the scientific test pages listed by dev\\eval_doclaynet.py (run that once first).

2. `compare` (venv with `pip install docling-slim==2.151.1 rtree pymupdf`, no torch needed): feed the same
   inputs to Docling's own `LayoutPostprocessor`, `ReadingOrderPredictor` and `PageAssembleModel.sanitize_text`
   and to the port, then report per page whether the clusters, reading order, caption/footnote links and texts
   are identical.

       python -X utf8 dev\\egret\\verify_docling_port.py compare %TEMP%\\ro_inputs.jsonl

When Docling is upgraded, update the port until `compare` reports no differences again.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "src"))


def _page_record(page, session, meta: dict) -> dict:
    from figure_detector import docling_layout, egret

    dets = egret.detect_layout(page, session=session)
    cells = docling_layout.page_cells(page)
    r = page.rect
    return {
        **meta,
        "page_rect": [r.x0, r.y0, r.x1, r.y1],
        "dets": [[d.name, d.score, list(d.box)] for d in dets],
        "cells": [[c.index, [c.rect.x0, c.rect.y0, c.rect.x1, c.rect.y1], c.text] for c in cells],
    }


def dump(args: argparse.Namespace) -> None:
    import pymupdf
    from figure_detector import egret

    session = egret.load_session()
    t0, n = time.time(), 0
    with args.out.open("w", encoding="utf-8") as fh:
        if args.doclaynet_test:
            import pyarrow.parquet as pq

            cache = Path(os.environ.get("TEMP", "/tmp")) / "max_luka_doclaynet_eval"
            index = [e for e in json.loads((cache / "scientific_index.json").read_text(encoding="utf-8"))
                     if e["subset"] == "test"]
            groups: dict = collections.defaultdict(list)
            for e in index:
                groups[(e["file"], e["rg"])].append(e)
            for (f, rg), es in groups.items():
                rows = pq.ParquetFile(f).read_row_group(rg, columns=["pdf"]).to_pylist()
                for e in es:
                    with pymupdf.open(stream=rows[e["row"]]["pdf"], filetype="pdf") as doc:
                        fh.write(json.dumps(_page_record(doc[0], session, {"doc": e["doc"], "page_no": e["page_no"]})) + "\n")
                    n += 1
        for target in args.pdf or []:
            pdfs = sorted(target.glob("*.pdf")) if target.is_dir() else [target]
            for pdf in pdfs:
                with pymupdf.open(pdf) as doc:
                    for pno, page in enumerate(doc, 1):
                        fh.write(json.dumps(_page_record(page, session, {"doc": pdf.name, "page_no": pno})) + "\n")
                        n += 1
    print(f"{n} pages -> {args.out} ({time.time() - t0:.0f}s)")


def _label(name: str):
    from docling_core.types.doc import DocItemLabel

    return DocItemLabel[name.upper().replace("-", "_").replace(" ", "_")]


def _upstream(rec: dict):
    from docling.datamodel.base_models import Cluster
    from docling.datamodel.pipeline_options import LayoutPostprocessorOptions
    from docling.models.postprocessing.reading_order_rb import PageElement, ReadingOrderPredictor
    from docling.models.stages.page_assemble.page_assemble_model import PageAssembleModel
    from docling.utils.layout_postprocessor import LayoutPostprocessor
    from docling.utils.text_normalization import cell_text_lines
    from docling_core.types.doc import BoundingBox, CoordOrigin, DocItemLabel, Size
    from docling_core.types.doc.document import RefItem
    from docling_core.types.doc.page import BoundingRectangle, TextCell

    x0, y0, x1, y1 = rec["page_rect"]
    w, h = x1 - x0, y1 - y0
    cells = [
        TextCell(index=i, text=t, orig=t, from_ocr=False, rect=BoundingRectangle.from_bounding_box(
            BoundingBox(l=b[0] - x0, t=b[1] - y0, r=b[2] - x0, b=b[3] - y0, coord_origin=CoordOrigin.TOPLEFT)))
        for i, b, t in rec["cells"]
    ]
    clusters = [
        Cluster(id=idx, label=_label(name), confidence=score, bbox=BoundingBox(
            l=min(max(a - x0, 0.0), w), t=min(max(b - y0, 0.0), h),
            r=min(max(c - x0, 0.0), w), b=min(max(d - y0, 0.0), h), coord_origin=CoordOrigin.TOPLEFT), cells=[])
        for idx, (name, score, (a, b, c, d)) in enumerate(rec["dets"])
    ]
    page = SimpleNamespace(cells=cells, size=Size(width=w, height=h), parsed_page=None)
    final = LayoutPostprocessor(page, clusters, LayoutPostprocessorOptions()).postprocess()

    # ReadingOrderModel glue: assembled order, Form/Key-Value children ordered on their own.
    containers = {DocItemLabel.FORM, DocItemLabel.KEY_VALUE_REGION}
    elems = []
    for i, c in enumerate(final):
        bb = c.bbox.to_bottom_left_origin(h)
        elems.append(PageElement(cid=i, ref=RefItem(cref=f"#/1/{c.id}"), text="", page_no=1,
                                 page_size=Size(width=w, height=h), label=c.label,
                                 l=bb.l, r=bb.r, b=bb.b, t=bb.t, coord_origin=bb.coord_origin))
    parent: dict = {}
    siblings: dict = {None: []}
    for i, c in enumerate(final):
        if c.label in containers:
            siblings[elems[i].ref.cref] = []
            for ch in c.children:
                parent.setdefault(f"#/1/{ch.id}", elems[i].ref.cref)
    for e in elems:
        siblings.setdefault(parent.get(e.ref.cref), []).append(e)
    ro = ReadingOrderPredictor()
    ordered = {k: (ro.predict_reading_order(page_elements=v) if len(v) > 1 else v) for k, v in siblings.items()}
    flat: list = []

    def leaves(key):
        for e in ordered[key]:
            if final[e.cid].label in containers:
                leaves(e.ref.cref)
            else:
                flat.append(e)

    leaves(None)
    caps = {g: cs[0] for g, cs in ro.predict_to_captions(sorted_elements=flat).items()}
    foots = ro.predict_to_footnotes(sorted_elements=flat)
    assembler = PageAssembleModel.__new__(PageAssembleModel)
    texts = [assembler.sanitize_text(cell_text_lines(c.cells)) for c in final]
    sig = [(c.label.value, tuple(round(v, 2) for v in c.bbox.as_tuple()), tuple(x.index for x in c.cells)) for c in final]
    return sig, [e.cid for e in flat], caps, foots, texts


def _port(rec: dict):
    import pymupdf
    from figure_detector import docling_layout as dl
    from figure_detector import egret

    pr = pymupdf.Rect(rec["page_rect"])
    dets = [egret.Detection(egret.LABELS.index(n), s, tuple(b)) for n, s, b in rec["dets"]]
    cells = [dl.TextCell(i, pymupdf.Rect(b), t) for i, b, t in rec["cells"]]
    layout = dl.postprocess_layout(dets, cells, pr)
    flat = dl.reading_order(layout, pr)
    sig = [(_label(c.label).value,
            tuple(round(v, 2) for v in (c.rect.x0 - pr.x0, c.rect.y0 - pr.y0, c.rect.x1 - pr.x0, c.rect.y1 - pr.y0)),
            tuple(x.index for x in c.cells)) for c in layout.clusters]
    return sig, [n.cid for n in flat], dl.match_captions(flat), dl.match_footnotes(flat), [c.text for c in layout.clusters]


def compare(args: argparse.Namespace) -> int:
    stats: collections.Counter = collections.Counter()
    diffs: dict = collections.defaultdict(list)
    port_seconds = 0.0
    for line in args.inputs.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        stats["pages"] += 1
        want = _upstream(rec)
        t0 = time.perf_counter()
        got = _port(rec)
        port_seconds += time.perf_counter() - t0
        stats["clusters"] += len(got[0])
        stats["caption_links"] += len(got[2])
        stats["footnote_links"] += len(got[3])
        for name, a, b in zip(("layout", "reading_order", "captions", "footnotes", "texts"), want, got):
            if a != b:
                stats[f"{name}_different"] += 1
                diffs[name].append(f"{rec['doc']} p{rec['page_no']}")
    print(json.dumps(stats, indent=1))
    print(f"port: {1000 * port_seconds / max(1, stats['pages']):.1f} ms/page")
    for name, pages in diffs.items():
        print(f"DIFFERENT {name}: {len(pages)} page(s), e.g. {pages[:5]}")
    print("IDENTICAL to Docling on every page" if not diffs else "Port differs from Docling: see above")
    return 1 if diffs else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump", help="Egret detections + text lines -> JSONL (Egret venv)")
    d.add_argument("--pdf", type=Path, action="append", help="PDF file or folder (repeatable)")
    d.add_argument("--doclaynet-test", action="store_true", help="DocLayNet scientific test pages (eval cache)")
    d.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare", help="port vs Docling on a dump (docling-slim venv)")
    c.add_argument("inputs", type=Path)
    args = ap.parse_args()
    if args.cmd == "dump":
        if not args.pdf and not args.doclaynet_test:
            ap.error("dump needs --pdf and/or --doclaynet-test")
        dump(args)
        return 0
    return compare(args)


if __name__ == "__main__":
    sys.exit(main())
