"""Evaluate figure extraction against DocLayNet v1.2 ground truth (scientific_articles only). Dev-only tool.

DocLayNet v1.2 (Hugging Face parquet) embeds a one-page PDF per annotated page, so the real detector
(`figure_detector`, the same code that ships in extract_assets.exe) runs on the original vector/text content
and its figure boxes are compared with the human-annotated layout boxes.

Two families of metrics:
  severity   what hurts a translated document, independent of how panels are grouped:
             - figure CLIPPED: text inside the annotated Picture (axis labels, legends) or > 10% of its area
               falls outside every extracted image; MISSED: less than half of it is covered
             - TEXT INTRUSION: annotated content outside any Picture (captions, body text, formulas, tables...)
               ends up inside an extracted image (as rendered, i.e. including the 4 pt padding)
             - BAD MERGE: one image covers several Pictures AND swallows text in between
  matching   DocLayNet-convention box matching (precision/recall/F1, split/merge counts); kept for reference.
             DocLayNet draws one Picture per caption in ~99% of cases, so split/merge mostly measure grouping.

Splits used here:
  tune     DocLayNet train, documents NOT in the hold-out  -> look at errors, tune rules here
  holdout  ~20% of train documents, chosen by a fixed hash -> measure only; never inspect pages
  val/test DocLayNet val/test                              -> the detector was historically tuned on these

Examples (system Python with pyarrow + PyMuPDF; the dataset never enters the repository):
  python dev\\eval_doclaynet.py --data D:\\PdfSamples --subset tune
  python dev\\eval_doclaynet.py --data D:\\PdfSamples --subset tune --gallery 8
  python dev\\eval_doclaynet.py --data D:\\PdfSamples --subset tune --limit 500 --overlays 20
  python dev\\eval_doclaynet.py --data D:\\PdfSamples --subset tune --disable-rule _reject_too_small

Caching (default under %TEMP%\\max_luka_doclaynet_eval): detector output per page is keyed by a fingerprint of
tools\\src\\figure_detector\\*.py, image_ops.py and the disabled rules; ground truth is cached separately and
scoring is always recomputed, so changing a metric never re-runs the detector.
"""

from __future__ import annotations

import argparse
import base64
import collections
import concurrent.futures as cf
import hashlib
import html
import json
import os
import random
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "tools" / "src"

SPLIT_DIRS = {"train": "DocLayNet-train", "val": "DocLayNet-val", "test": "DocLayNet-test"}
SUBSETS = ("tune", "holdout", "val", "test")
CLASS_NAMES = {
    1: "Caption", 2: "Footnote", 3: "Formula", 4: "List-item", 5: "Page-footer", 6: "Page-header",
    7: "Picture", 8: "Section-header", 9: "Table", 10: "Text", 11: "Title",
}
PICTURE = 7
SCIENTIFIC = "scientific_articles"

HOLDOUT_SALT = "luka-loop/doclaynet-holdout/v1"
HOLDOUT_PERCENT = 20

# Matching thresholds (DocLayNet convention). Our boxes are deliberately larger than the annotation (axis-label
# expansion), hence the lenient criterion next to plain IoU >= 0.5.
STRICT_IOU = 0.5
LENIENT_GT_COVER = 0.9       # prediction covers >= 90% of the ground-truth box ...
LENIENT_MAX_GROWTH = 2.0     # ... and is at most 2x its area
PART_COVER = 0.5             # "mostly inside" for merge/split/fragment attribution

# Severity thresholds.
RENDER_PAD = 4.0             # extract_images renders each box with 4 pt padding on every side
MISS_BELOW = 0.5             # Picture area covered by extracted images below this -> missed
AREA_OK = 0.9                # ... below this (but not missed) -> graphic area clipped
MAJOR_CUT_CELLS = 3          # >= this many visibly cut text cells (or area clipped) -> major clip, else minor
INK_WINDOW = 3.0             # half-size (pt) of the window checked for visible ink around a cut text cell
INK_MIN_PIXELS = 4           # dark pixels (at 3x zoom) outside every image needed to call a cell visible

Box = tuple[float, float, float, float]
Point = tuple[float, float]
GtBox = tuple[str, Box, list[Point]]  # (class name, box, centres of the PDF text cells inside it)


# ==============================================================================
# Pure helpers (no pyarrow / PyMuPDF; unit-tested in tests\test_eval_doclaynet.py)
# ==============================================================================


def is_holdout(doc_name: str) -> bool:
    """Deterministic document-level hold-out membership (~HOLDOUT_PERCENT % of documents)."""
    digest = hashlib.sha256(f"{HOLDOUT_SALT}:{doc_name}".encode("utf-8")).hexdigest()
    return int(digest, 16) % 100 < HOLDOUT_PERCENT


def subset_of(split: str, doc_name: str) -> str:
    if split != "train":
        return split
    return "holdout" if is_holdout(doc_name) else "tune"


def coco_to_pdf(bbox: list[float], coco_w: float, coco_h: float, page_w: float, page_h: float) -> Box:
    """DocLayNet `[x, y, w, h]` in the stretched coco_w x coco_h image -> PDF points (scaled per axis)."""
    x, y, w, h = bbox
    sx, sy = page_w / coco_w, page_h / coco_h
    return (x * sx, y * sy, (x + w) * sx, (y + h) * sy)


def area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: Box, b: Box) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a: Box, b: Box) -> float:
    inter = intersection(a, b)
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def coverage(inner: Box, outer: Box) -> float:
    """Fraction of `inner`'s area that lies inside `outer`."""
    a = area(inner)
    return intersection(inner, outer) / a if a > 0 else 0.0


def expand(b: Box, pad: float, page: Box) -> Box:
    return (max(page[0], b[0] - pad), max(page[1], b[1] - pad), min(page[2], b[2] + pad), min(page[3], b[3] + pad))


def contains_point(b: Box, p: Point) -> bool:
    return b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]


def union_coverage(target: Box, covers: list[Box]) -> float:
    """Exact fraction of `target`'s area covered by the union of `covers` (coordinate compression)."""
    a = area(target)
    if a <= 0:
        return 0.0
    clipped = []
    for c in covers:
        x0, y0, x1, y1 = max(c[0], target[0]), max(c[1], target[1]), min(c[2], target[2]), min(c[3], target[3])
        if x1 > x0 and y1 > y0:
            clipped.append((x0, y0, x1, y1))
    if not clipped:
        return 0.0
    xs = sorted({v for c in clipped for v in (c[0], c[2])})
    ys = sorted({v for c in clipped for v in (c[1], c[3])})
    covered = 0.0
    for xa, xb in zip(xs, xs[1:]):
        for ya, yb in zip(ys, ys[1:]):
            cx, cy = (xa + xb) / 2, (ya + yb) / 2
            if any(c[0] <= cx <= c[2] and c[1] <= cy <= c[3] for c in clipped):
                covered += (xb - xa) * (yb - ya)
    return covered / a


def is_strict_match(pred: Box, gt: Box) -> bool:
    return iou(pred, gt) >= STRICT_IOU


def is_lenient_match(pred: Box, gt: Box) -> bool:
    return is_strict_match(pred, gt) or (
        coverage(gt, pred) >= LENIENT_GT_COVER and area(pred) <= LENIENT_MAX_GROWTH * area(gt)
    )


def greedy_match(preds: list[Box], gts: list[Box], accept) -> list[tuple[int, int]]:
    """One-to-one matching, highest IoU first, among pairs accepted by `accept(pred, gt)`."""
    pairs = sorted(
        ((iou(p, g), i, j) for i, p in enumerate(preds) for j, g in enumerate(gts) if accept(p, g)),
        reverse=True,
    )
    used_p, used_g, out = set(), set(), []
    for _, i, j in pairs:
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            out.append((i, j))
    return out


def evaluate_page(preds: list[Box], gts: list[Box], others: list[tuple[str, Box]]) -> dict:
    """DocLayNet-convention matching for one page. `others` are the non-Picture boxes as (class name, box).

    Unmatched GT: 'merged' / 'split' / 'partial' / 'missed'; unmatched prediction: 'merge' / 'fragment' /
    'fp_<class>' (mostly inside an annotated Table/Formula/Text... box) / 'fp_unlabeled'.
    """
    strict = greedy_match(preds, gts, is_strict_match)
    lenient = greedy_match(preds, gts, is_lenient_match)
    matched_p = {i for i, _ in lenient}
    matched_g = {j for _, j in lenient}

    pred_outcomes: dict[int, str] = {}
    gt_outcomes: dict[int, str] = {}
    for i, p in enumerate(preds):
        if i in matched_p:
            continue
        swallowed = [j for j, g in enumerate(gts) if coverage(g, p) >= PART_COVER]
        if len(swallowed) >= 2:
            pred_outcomes[i] = "merge"
            for j in swallowed:
                if j not in matched_g:
                    gt_outcomes[j] = "merged"
            continue
        if any(coverage(p, g) >= PART_COVER for g in gts):
            pred_outcomes[i] = "fragment"
            continue
        best_cls, best_cov = "unlabeled", 0.0
        for cls, b in others:
            c = coverage(p, b)
            if c > best_cov:
                best_cls, best_cov = cls, c
        pred_outcomes[i] = f"fp_{best_cls if best_cov >= PART_COVER else 'unlabeled'}"

    for j, g in enumerate(gts):
        if j in matched_g or j in gt_outcomes:
            continue
        inside = [i for i, p in enumerate(preds) if coverage(p, g) >= PART_COVER]
        if len(inside) >= 2:
            gt_outcomes[j] = "split"
        elif inside or any(intersection(p, g) > 0 for p in preds):
            gt_outcomes[j] = "partial"
        else:
            gt_outcomes[j] = "missed"

    return {
        "n_pred": len(preds),
        "n_gt": len(gts),
        "tp_strict": len(strict),
        "tp_lenient": len(lenient),
        "matched": sorted(lenient),
        "gt_outcomes": {str(k): v for k, v in sorted(gt_outcomes.items())},
        "pred_outcomes": {str(k): v for k, v in sorted(pred_outcomes.items())},
    }


def severity_page(preds: list[Box], pictures: list[GtBox], others: list[GtBox], page: Box) -> dict:
    """Translation-oriented errors on one page, independent of how panels are grouped into images.

    Every prediction is taken as rendered (padded by RENDER_PAD, clipped to the page). Per Picture:
    'missed' (< MISS_BELOW of its area covered by the union of images), 'clipped' (some of its text cells
    -- axis labels, legends -- or more than 1 - AREA_OK of its area outside every image) or 'ok'.
    Per prediction: 'bad_merge' (covers >= 2 Pictures and swallows outside text), 'intrusion' (swallows text
    cells of annotated non-Picture content), 'merge_ok', 'orphan' (touches no Picture) or 'ok'.
    """
    imgs = [expand(p, RENDER_PAD, page) for p in preds]
    pic_boxes = [b for _, b, _ in pictures]

    figures = []
    for _, g, cells in pictures:
        cov = union_coverage(g, imgs)
        cut = [c for c in cells if not any(contains_point(im, c) for im in imgs)] if cov >= MISS_BELOW else []
        status = "missed" if cov < MISS_BELOW else ("clipped" if cut or cov < AREA_OK else "ok")
        figures.append({"status": status, "coverage": round(cov, 3), "cut_cells": len(cut), "cells": len(cells),
                        "cut_points": [[round(v, 1) for v in c] for c in cut]})

    intruded_cells = [0] * len(preds)
    intruded_classes: list[collections.Counter] = [collections.Counter() for _ in preds]
    intrusions = []
    for cls, b, cells in others:
        hits = collections.Counter()
        points = []
        for c in cells:
            if any(contains_point(g, c) for g in pic_boxes):
                continue  # text that belongs to a figure is not an intrusion
            for i, im in enumerate(imgs):
                if contains_point(im, c):
                    hits[i] += 1
                    points.append(c)
                    break
        if hits:
            for i, n in hits.items():
                intruded_cells[i] += n
                intruded_classes[i][cls] += 1
            intrusions.append({"class": cls, "cells": sum(hits.values()), "of": len(cells),
                               "points": [[round(v, 1) for v in c] for c in points]})

    pred_status = []
    for i, im in enumerate(imgs):
        covered = [k for k, g in enumerate(pic_boxes) if coverage(g, im) >= PART_COVER]
        touches = any(intersection(im, g) > 0 for g in pic_boxes)
        if len(covered) >= 2 and intruded_cells[i]:
            status = "bad_merge"
        elif intruded_cells[i]:
            status = "intrusion"
        elif len(covered) >= 2:
            status = "merge_ok"
        elif not touches:
            status = "orphan"
        else:
            status = "ok"
        pred_status.append({"status": status, "intruded_cells": intruded_cells[i],
                            "intruded_classes": dict(intruded_classes[i])})

    severe = any(f["status"] != "ok" for f in figures) or any(
        p["status"] in ("intrusion", "bad_merge") for p in pred_status
    )
    return {"figures": figures, "preds": pred_status, "intrusions": intrusions, "severe": severe}


def apply_visibility(sev: dict, visible: list[list[bool]]) -> dict:
    """Keep only cut cells that show real ink outside the images; grade clipped figures major/minor.

    `visible[k][n]` says whether cut point n of figure k has visible ink outside every extracted image
    (DocLayNet text cells can sit on invisible or overlapping text). A figure stays 'clipped' only with
    >= 1 visible cut cell or an area clip; 'clip' is 'major' with >= MAJOR_CUT_CELLS visible cells or an area
    clip, otherwise 'minor' (typically one sub-panel label or a stray tick value).
    """
    out = dict(sev)
    figures = []
    for f, flags in zip(sev["figures"], visible):
        g = dict(f)
        if f["status"] in ("clipped", "ok"):
            pts = [p for p, v in zip(f["cut_points"], flags) if v]
            area_clip = f["coverage"] < AREA_OK
            g["cut_points"] = pts
            g["cut_cells"] = len(pts)
            g["status"] = "clipped" if pts or area_clip else "ok"
            g["clip"] = ("major" if area_clip or len(pts) >= MAJOR_CUT_CELLS else "minor") if g["status"] == "clipped" else ""
        figures.append(g)
    out["figures"] = figures
    out["severe"] = any(f["status"] == "missed" or f.get("clip") == "major" for f in figures) or any(
        p["status"] in ("intrusion", "bad_merge") for p in sev["preds"]
    )
    return out


def prf(tp: int, n_pred: int, n_gt: int) -> dict:
    precision = tp / n_pred if n_pred else 1.0
    recall = tp / n_gt if n_gt else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if "error" not in r and "eval" in r]
    tot = collections.Counter()
    gt_out, pred_out = collections.Counter(), collections.Counter()
    by_source = collections.defaultdict(collections.Counter)
    matched_ious: list[float] = []
    fig_status, pred_status, intr_cls = collections.Counter(), collections.Counter(), collections.Counter()
    clip_grade = collections.Counter()
    cut_cells = intr_cells = severe_pages = clipped_by_labels = 0
    for r in ok:
        ev = r["eval"]
        tot.update({k: ev[k] for k in ("n_pred", "n_gt", "tp_strict", "tp_lenient")})
        matched_ious += [iou(tuple(r["preds"][i]), tuple(r["gts"][j])) for i, j in ev["matched"]]
        gt_out.update(ev["gt_outcomes"].values())
        pred_out.update(ev["pred_outcomes"].values())
        matched_p = {i for i, _ in ev["matched"]}
        for i, meta in enumerate(r["pred_meta"]):
            key = meta["source"] + ("+caption" if meta["captioned"] else "")
            by_source[key]["pred"] += 1
            by_source[key]["tp"] += i in matched_p
        sev = r.get("sev")
        if sev:
            severe_pages += sev["severe"]
            for f in sev["figures"]:
                fig_status[f["status"]] += 1
                cut_cells += f["cut_cells"]
                clipped_by_labels += f["status"] == "clipped" and f["cut_cells"] > 0
                if f["status"] == "clipped":
                    clip_grade[f.get("clip") or "major"] += 1
            for p in sev["preds"]:
                pred_status[p["status"]] += 1
            for it in sev["intrusions"]:
                intr_cls[it["class"]] += 1
                intr_cells += it["cells"]
    n_fig, n_pred = sum(fig_status.values()), sum(pred_status.values())
    return {
        "pages": len(results),
        "page_errors": len(results) - len(ok),
        "pages_with_pictures": sum(1 for r in ok if r["eval"]["n_gt"]),
        "severity": {
            "pages_with_severe_error": severe_pages,
            "figures": n_fig,
            "figures_ok": fig_status["ok"],
            "figures_ok_rate": _rate(fig_status["ok"], n_fig),
            "figures_acceptable_rate": _rate(fig_status["ok"] + clip_grade["minor"], n_fig),
            "figures_clipped": fig_status["clipped"],
            "figures_clipped_major": clip_grade["major"],
            "figures_clipped_minor": clip_grade["minor"],
            "figures_clipped_labels_cut": clipped_by_labels,
            "figure_text_cells_cut": cut_cells,
            "figures_missed": fig_status["missed"],
            "images": n_pred,
            "images_clean_rate": _rate(pred_status["ok"] + pred_status["merge_ok"], n_pred),
            "images_with_text_intrusion": pred_status["intrusion"] + pred_status["bad_merge"],
            "images_bad_merge": pred_status["bad_merge"],
            "images_merge_ok": pred_status["merge_ok"],
            "images_orphan": pred_status["orphan"],
            "intruded_boxes_by_class": dict(intr_cls.most_common()),
            "intruded_text_cells": intr_cells,
        },
        "matching": {
            "gt_pictures": tot["n_gt"],
            "predictions": tot["n_pred"],
            "strict_iou50": prf(tot["tp_strict"], tot["n_pred"], tot["n_gt"]),
            "lenient": prf(tot["tp_lenient"], tot["n_pred"], tot["n_gt"]),
            "matched_iou_mean": round(sum(matched_ious) / len(matched_ious), 4) if matched_ious else None,
            "matched_iou_below_0_8": sum(1 for v in matched_ious if v < 0.8),
            "unmatched_gt": dict(gt_out.most_common()),
            "unmatched_pred": dict(pred_out.most_common()),
            "precision_by_source": {
                k: {"pred": v["pred"], "tp": v["tp"], "precision": round(v["tp"] / v["pred"], 4)}
                for k, v in sorted(by_source.items())
            },
        },
        "seconds_per_page": round(sum(r.get("seconds", 0.0) for r in results) / max(1, len(results)), 3),
    }


def score(result: dict, gt: dict) -> dict:
    """Attach ground truth plus matching and severity scores to one cached detector result."""
    if "error" in result:
        return result
    pictures = [(c, tuple(b), [tuple(p) for p in cells]) for c, b, cells in gt["boxes"] if c == "Picture"]
    others = [(c, tuple(b), [tuple(p) for p in cells]) for c, b, cells in gt["boxes"] if c != "Picture"]
    preds = [tuple(p) for p in result["preds"]]
    out = dict(result)
    out["gts"] = [list(b) for _, b, _ in pictures]
    out["eval"] = evaluate_page(preds, [b for _, b, _ in pictures], [(c, b) for c, b, _ in others])
    out["sev"] = severity_page(preds, pictures, others, (0.0, 0.0, gt["w"], gt["h"]))
    return out


# ==============================================================================
# Dataset access (pyarrow) and detector runs (PyMuPDF), imported lazily
# ==============================================================================


DETECTORS = ("heuristic", "egret")
EGRET_MODEL = SRC_DIR.parent / "models" / "egret_medium.onnx"


def detector_fingerprint(disabled_rules: list[str], detector: str = "heuristic") -> str:
    h = hashlib.sha256()
    for p in sorted((SRC_DIR / "figure_detector").glob("*.py")) + [SRC_DIR / "image_ops.py"]:
        h.update(p.name.encode())
        h.update(p.read_bytes())
    h.update(json.dumps(sorted(disabled_rules)).encode())
    if detector != "heuristic":  # keeps the fingerprints of earlier heuristic runs (and their caches) valid
        h.update(detector.encode())
        h.update(hashlib.sha256(EGRET_MODEL.read_bytes()).digest())
    return h.hexdigest()[:16]


def build_index(data_root: Path, cache_dir: Path) -> list[dict]:
    """Scientific pages of all splits as (split, subset, file, row group, row, doc, page_no, page_hash)."""
    cache = cache_dir / "scientific_index.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    import pyarrow.parquet as pq

    index = []
    for split, folder in SPLIT_DIRS.items():
        files = sorted((data_root / folder / "_parquet" / "data").glob("*.parquet"))
        if not files:
            raise SystemExit(f"No parquet files for split '{split}' under {data_root / folder}")
        for f in files:
            pf = pq.ParquetFile(f)
            for g in range(pf.num_row_groups):
                for row, rec in enumerate(pf.read_row_group(g, columns=["metadata", "category_id"]).to_pylist()):
                    m = rec["metadata"]
                    if m["doc_category"] != SCIENTIFIC:
                        continue
                    index.append({
                        "split": split, "subset": subset_of(split, m["original_filename"]),
                        "file": str(f), "rg": g, "row": row, "doc": m["original_filename"],
                        "page_no": m["page_no"], "page_hash": m["page_hash"],
                        "n_picture": (rec["category_id"] or []).count(PICTURE),
                    })
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(index), encoding="utf-8")
    return index


def _read_gt_group(file: str, rg: int, entries: list[dict]) -> list[tuple[str, dict]]:
    """Ground-truth boxes (PDF points) with text-cell centres for the requested rows of one row group."""
    import pyarrow.parquet as pq

    rows = pq.ParquetFile(file).read_row_group(rg, columns=["metadata", "bboxes", "category_id", "pdf_cells"]).to_pylist()
    out = []
    for e in entries:
        rec = rows[e["row"]]
        m = rec["metadata"]
        cw, ch, pw, ph = m["coco_width"], m["coco_height"], m["original_width"], m["original_height"]
        boxes = []
        cells_per_box = rec["pdf_cells"] or [[] for _ in rec["bboxes"]]
        for b, c, cells in zip(rec["bboxes"], rec["category_id"], cells_per_box):
            centres = []
            for cell in cells or []:
                x0, y0, x1, y1 = coco_to_pdf(cell["bbox"], cw, ch, pw, ph)
                centres.append([round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1)])
            boxes.append([CLASS_NAMES.get(c, str(c)), [round(v, 2) for v in coco_to_pdf(b, cw, ch, pw, ph)], centres])
        out.append((e["page_hash"], {"w": pw, "h": ph, "boxes": boxes}))
    return out


def load_ground_truth(entries: list[dict], workers: int, cache_dir: Path) -> dict[str, dict]:
    path = cache_dir / "ground_truth_v1.jsonl"
    gt: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                h, v = json.loads(line)
                gt[h] = v
    todo = collections.defaultdict(list)
    for e in entries:
        if e["page_hash"] not in gt:
            todo[(e["file"], e["rg"])].append(e)
    if todo:
        print(f"Reading ground truth for {sum(len(v) for v in todo.values())} pages ...", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh, cf.ProcessPoolExecutor(max_workers=workers) as pool:
            for fut in cf.as_completed([pool.submit(_read_gt_group, f, g, es) for (f, g), es in todo.items()]):
                for h, v in fut.result():
                    gt[h] = v
                    fh.write(json.dumps([h, v]) + "\n")
    return gt


def _ink_group(file: str, rg: int, items: list[dict]) -> list[tuple[str, list[list[bool]]]]:
    """For each cut text cell, is there visible ink near it that lies outside every extracted image?"""
    import pyarrow.parquet as pq
    import pymupdf

    rows = pq.ParquetFile(file).read_row_group(rg, columns=["pdf"]).to_pylist()
    zoom = 3.0
    out = []
    for it in items:
        with pymupdf.open(stream=rows[it["row"]]["pdf"], filetype="pdf") as doc:
            page = doc[0]
            pr = (page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1)
            imgs = [expand(tuple(p), RENDER_PAD, pr) for p in it["preds"]]
            flags = []
            for pts in it["cut_points"]:
                fl = []
                for x, y in pts:
                    win = pymupdf.Rect(x - INK_WINDOW, y - INK_WINDOW, x + INK_WINDOW, y + INK_WINDOW) & page.rect
                    if win.is_empty:
                        fl.append(False)
                        continue
                    pix = page.get_pixmap(clip=win, matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
                    samples, stride, dark = pix.samples, pix.stride, 0
                    for row in range(pix.height):
                        py = win.y0 + (row + 0.5) / zoom
                        base = row * stride
                        for col in range(pix.width):
                            if samples[base + col] < 160:
                                px = win.x0 + (col + 0.5) / zoom
                                if not any(contains_point(im, (px, py)) for im in imgs):
                                    dark += 1
                    fl.append(dark >= INK_MIN_PIXELS)
                flags.append(fl)
        out.append((it["page_hash"], flags))
    return out


def load_visibility(results: list[dict], fp: str, workers: int, cache_dir: Path) -> dict[str, list[list[bool]]]:
    """Ink visibility of every cut text cell, cached per detector fingerprint."""
    path = cache_dir / "ink" / f"{fp}_pad{RENDER_PAD:g}_w{INK_WINDOW:g}_v1.jsonl"
    vis: dict[str, list[list[bool]]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                h, v = json.loads(line)
                vis[h] = v
    todo = collections.defaultdict(list)
    for r in results:
        sev = r.get("sev")
        if not sev or r["page_hash"] in vis:
            continue
        cut = [f["cut_points"] for f in sev["figures"]]
        if not any(cut):
            vis[r["page_hash"]] = [[] for _ in cut]
            continue
        todo[(r["file"], r["rg"])].append({"page_hash": r["page_hash"], "row": r["row"], "preds": r["preds"], "cut_points": cut})
    if todo:
        print(f"Checking ink for cut text cells on {sum(len(v) for v in todo.values())} pages ...", flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh, cf.ProcessPoolExecutor(max_workers=workers) as pool:
            for fut in cf.as_completed([pool.submit(_ink_group, f, g, items) for (f, g), items in todo.items()]):
                for h, v in fut.result():
                    vis[h] = v
                    fh.write(json.dumps([h, v]) + "\n")
    return vis


_DETECTOR = "heuristic"


def _worker_init(disabled_rules: list[str], detector: str = "heuristic") -> None:
    global _DETECTOR
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    os.environ.setdefault("PYMUPDF_SUGGEST_LAYOUT_ANALYZER", "0")
    if disabled_rules:
        import figure_detector.vector as vec

        vec._VECTOR_CLUSTER_RULES = tuple(r for r in vec._VECTOR_CLUSTER_RULES if r.__name__ not in disabled_rules)
    _DETECTOR = detector
    if detector == "egret":
        from figure_detector import egret

        egret.load_session(threads=1)  # cached per worker process; one thread per worker avoids oversubscription


def _run_detector(page):
    if _DETECTOR == "egret":
        from figure_detector.egret import run_page_egret

        return run_page_egret(page)
    from figure_detector.pipeline import _run_page_pipeline

    return _run_page_pipeline(page)


def _run_group(file: str, rg: int, entries: list[dict]) -> list[dict]:
    """Run the detector on the requested rows of one parquet row group (worker process)."""
    import pyarrow.parquet as pq
    import pymupdf
    from figure_detector.extract import _detect_table_placement

    rows = pq.ParquetFile(file).read_row_group(rg, columns=["pdf"]).to_pylist()
    out = []
    for e in entries:
        res = {k: e[k] for k in ("split", "subset", "file", "rg", "row", "doc", "page_no", "page_hash")}
        t0 = time.perf_counter()
        try:
            with pymupdf.open(stream=rows[e["row"]]["pdf"], filetype="pdf") as doc:
                page = doc[0]
                ctx, candidates, is_scanned = _run_detector(page)
                tables = [t.rect for t in ctx.get_page_tables()] if any(c.caption_idx is None for c in candidates) else []
                res["preds"] = [[round(v, 2) for v in c.rect] for c in candidates]
                res["pred_meta"] = [
                    {"source": c.source, "captioned": c.caption_idx is not None,
                     "placement": _detect_table_placement(candidates, k, ctx, tables)}
                    for k, c in enumerate(candidates)
                ]
                res["is_scanned"] = is_scanned
        except Exception as exc:  # noqa: BLE001 - one broken page must not stop a 12k-page run
            res["error"] = f"{type(exc).__name__}: {exc}"
            res["traceback"] = traceback.format_exc(limit=3)
        res["seconds"] = round(time.perf_counter() - t0, 3)
        out.append(res)
    return out


def run_pages(
    entries: list[dict], disabled: list[str], workers: int, cache_file: Path, detector: str = "heuristic"
) -> list[dict]:
    cached: dict[str, dict] = {}
    if cache_file.is_file():
        for line in cache_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cached[r["page_hash"]] = r
    todo = [e for e in entries if e["page_hash"] not in cached]
    groups: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    for e in todo:
        groups[(e["file"], e["rg"])].append(e)
    print(f"{len(entries)} pages selected, {len(entries) - len(todo)} cached, {len(todo)} to run "
          f"in {len(groups)} row groups with {workers} worker(s)", flush=True)
    if groups:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        t0, done = time.time(), 0
        with cache_file.open("a", encoding="utf-8") as fh, cf.ProcessPoolExecutor(
            max_workers=workers, initializer=_worker_init, initargs=(disabled, detector)
        ) as pool:
            futures = [pool.submit(_run_group, f, g, es) for (f, g), es in groups.items()]
            for fut in cf.as_completed(futures):
                for r in fut.result():
                    cached[r["page_hash"]] = r
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    done += 1
                fh.flush()
                print(f"  {done}/{len(todo)} pages ({done / max(1e-6, time.time() - t0):.1f} pages/s)", flush=True)
    return [cached[e["page_hash"]] for e in entries]


# ==============================================================================
# Visual review: overlays and the severity gallery
# ==============================================================================


def _error_weight(r: dict) -> int:
    if "error" in r:
        return 1000
    sev = r.get("sev") or {}
    weight = sum(1 for f in sev.get("figures", []) if f["status"] == "missed" or f.get("clip") == "major")
    weight += sum(2 for p in sev.get("preds", []) if p["status"] in ("intrusion", "bad_merge"))
    return weight


def _render_marked(r: dict, scale: float, crop: bool) -> tuple[bytes, int, int]:
    """Render the page (or a crop around its figures) with GT (green), images (red), intruded/cut text (dots)."""
    import pyarrow.parquet as pq
    import pymupdf

    rec = pq.ParquetFile(r["file"]).read_row_group(r["rg"], columns=["pdf"]).to_pylist()[r["row"]]
    with pymupdf.open(stream=rec["pdf"], filetype="pdf") as doc:
        page = doc[0]
        pr = (page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1)
        sev = r["sev"]
        for g, f in zip(r["gts"], sev["figures"]):
            page.draw_rect(pymupdf.Rect(g), color=(0, 0.62, 0), width=2.2)
            page.insert_text((g[0] + 3, g[1] + 10), f"Nhan: {f['status']}", fontsize=8, color=(0, 0.5, 0))
            for x, y in f["cut_points"]:
                page.draw_circle((x, y), 2.6, color=(0, 0.35, 1), fill=(0, 0.35, 1))
        for p, ps in zip(r["preds"], sev["preds"]):
            im = expand(tuple(p), RENDER_PAD, pr)
            page.draw_rect(pymupdf.Rect(im), color=(0.88, 0, 0), width=1.4, dashes="[4] 0")
            page.insert_text((im[0] + 3, im[3] - 4), f"Anh: {ps['status']}", fontsize=8, color=(0.85, 0, 0))
        for it in sev["intrusions"]:
            for x, y in it["points"]:
                page.draw_circle((x, y), 2.6, color=(1, 0.5, 0), fill=(1, 0.5, 0))
        clip = None
        if crop:
            boxes = [pymupdf.Rect(b) for b in r["gts"]] + [pymupdf.Rect(expand(tuple(p), RENDER_PAD, pr)) for p in r["preds"]]
            if boxes:
                region = boxes[0]
                for b in boxes[1:]:
                    region |= b
                clip = (region + (-36, -30, 36, 60)) & page.rect
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip)
        return pix.tobytes("jpeg" if crop else "png", **({"jpg_quality": 82} if crop else {})), pix.width, pix.height


def _render_outputs(r: dict, scale: float, limit: int = 3) -> list[tuple[bytes, int, int]]:
    """The images extract_images would write for the predictions touching a figure (box +/- 4 pt, unmarked)."""
    import pyarrow.parquet as pq
    import pymupdf

    rec = pq.ParquetFile(r["file"]).read_row_group(r["rg"], columns=["pdf"]).to_pylist()[r["row"]]
    gts = [tuple(g) for g in r["gts"]]
    picked = [p for p in r["preds"] if not gts or any(intersection(tuple(p), g) > 0 for g in gts)][:limit]
    out = []
    with pymupdf.open(stream=rec["pdf"], filetype="pdf") as doc:
        page = doc[0]
        for p in picked:
            clip = pymupdf.Rect(p[0] - RENDER_PAD, p[1] - RENDER_PAD, p[2] + RENDER_PAD, p[3] + RENDER_PAD) & page.rect
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip)
            out.append((pix.tobytes("jpeg", jpg_quality=85), pix.width, pix.height))
    return out


def write_overlays(results: list[dict], out_dir: Path, limit: int) -> list[Path]:
    worst = sorted((r for r in results if "sev" in r and _error_weight(r)), key=_error_weight, reverse=True)[:limit]
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for rank, r in enumerate(worst, 1):
        data, _, _ = _render_marked(r, 1.4, crop=False)
        path = out_dir / f"{rank:03d}_{Path(r['doc']).stem}_p{r['page_no']}.png"
        path.write_bytes(data)
        written.append(path)
    return written


GALLERY_CATEGORIES = [
    ("caption_in_image", "Ảnh chứa cả chú thích",
     "Dòng chú thích (Caption) nằm trong ảnh: chữ tiếng Anh không dịch được và lặp lại phần chú thích đã dịch bên ngoài.",
     lambda r: any(it["class"] == "Caption" for it in r["sev"]["intrusions"])),
    ("text_in_image", "Ảnh chứa văn bản, công thức hoặc bảng xung quanh",
     "Nội dung được gán nhãn ngoài hình (đoạn văn, công thức, bảng, tiêu đề...) lọt vào ảnh.",
     lambda r: any(it["class"] != "Caption" for it in r["sev"]["intrusions"])),
    ("bad_merge", "Gộp lệch",
     "Một ảnh bao nhiều hình và nuốt cả chữ nằm giữa / quanh chúng.",
     lambda r: any(p["status"] == "bad_merge" for p in r["sev"]["preds"])),
    ("area_cut", "Cắt thiếu một phần hình",
     "Hơn 10% diện tích hình nằm ngoài mọi ảnh đã tách.",
     lambda r: any(f.get("clip") == "major" and f["coverage"] < AREA_OK for f in r["sev"]["figures"])),
    ("labels_cut_major", "Cắt mất nhiều chữ của hình (≥ 3 ô chữ)",
     "Ít nhất 3 ô chữ thuộc hình (nhãn trục, số chia, chú giải — chấm xanh dương) có mực thật nằm ngoài ảnh. "
     "So với ảnh xuất ra thực tế bên dưới.",
     lambda r: any(f.get("clip") == "major" and f["coverage"] >= AREA_OK for f in r["sev"]["figures"])),
    ("labels_cut_minor", "Cắt mất ít chữ của hình (1–2 ô chữ)",
     "Thường chỉ là một nhãn panel như (c)/(d) hoặc một số chia ở mép — mức nhẹ.",
     lambda r: any(f.get("clip") == "minor" for f in r["sev"]["figures"])),
    ("missed", "Bỏ sót hình",
     "Chưa tới một nửa diện tích hình nằm trong ảnh nào.",
     lambda r: any(f["status"] == "missed" for f in r["sev"]["figures"])),
]


def write_gallery(results: list[dict], summary: dict, path: Path, per_category: int, seed: int) -> None:
    """Self-contained local HTML page: examples per severity category, one page per document."""
    rng = random.Random(seed)
    scored = [r for r in results if "sev" in r]
    sections, nav = [], []
    sev = summary["severity"]
    for key, title, note, pred in GALLERY_CATEGORIES:
        cands = [r for r in scored if pred(r)]
        n_pages, n_docs = len(cands), len({r["doc"] for r in cands})
        rng.shuffle(cands)
        picked, seen = [], set()
        for r in cands:
            if r["doc"] not in seen:
                seen.add(r["doc"])
                picked.append(r)
            if len(picked) == per_category:
                break
        cards = []
        for r in picked:
            data, w, h = _render_marked(r, 1.8, crop=True)
            states = collections.Counter(
                f["status"] + (f" ({f['clip']})" if f.get("clip") else "") for f in r["sev"]["figures"]
            )
            imgs = collections.Counter(p["status"] for p in r["sev"]["preds"])
            info = (f"hình: {', '.join(f'{v} {k}' for k, v in states.items()) or '0'} · "
                    f"ảnh: {', '.join(f'{v} {k}' for k, v in imgs.items()) or '0'}")
            outputs = "".join(
                f'<img class="out" loading="lazy" width="{ow}" height="{oh}" '
                f'src="data:image/jpeg;base64,{base64.b64encode(od).decode()}" alt="ảnh xuất ra">'
                for od, ow, oh in _render_outputs(r, 1.3)
            )
            out_block = f'<div class="outs"><span>Ảnh xuất ra thực tế:</span>{outputs}</div>' if outputs else ""
            cards.append(
                f'<figure class="card"><img loading="lazy" width="{w}" height="{h}" '
                f'src="data:image/jpeg;base64,{base64.b64encode(data).decode()}" alt="{html.escape(r["doc"])}">'
                f'{out_block}<figcaption><b>{html.escape(r["doc"])}</b>, trang {r["page_no"]}<br>{html.escape(info)}'
                f'</figcaption></figure>'
            )
        nav.append(f'<a href="#{key}">{html.escape(title)} ({n_pages})</a>')
        sections.append(
            f'<section id="{key}"><h2>{html.escape(title)} <span class="n">{n_pages} trang / {n_docs} tài liệu</span></h2>'
            f'<p class="note">{html.escape(note)}</p><div class="grid">{"".join(cards)}</div></section>'
        )
    stats = (f"{sev['figures']} hình: {sev['figures_ok']} ổn ({sev['figures_ok_rate']:.1%}), "
             f"{sev['figures_clipped_major']} cắt thiếu nhiều, {sev['figures_clipped_minor']} cắt thiếu ít, "
             f"{sev['figures_missed']} bỏ sót · {sev['images']} ảnh: "
             f"{sev['images_with_text_intrusion']} lấn chữ (trong đó {sev['images_bad_merge']} gộp lệch), "
             f"{sev['images_merge_ok']} gộp đúng")
    page = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Lỗi nặng của bộ tách hình</title>
<style>
:root {{ --bg:#f6f7f9; --fg:#1d2330; --muted:#5b6475; --card:#fff; --line:#dfe3ea; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171d; --fg:#e7eaf0; --muted:#a3abba; --card:#1d2129; --line:#2d333e; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.55 system-ui, "Segoe UI", sans-serif; }}
header, main {{ max-width:1300px; margin:auto; padding:0 20px; }} header {{ padding-top:22px; }}
h1 {{ font-size:22px; margin:0 0 6px; }} h2 {{ font-size:18px; margin:28px 0 4px; }}
.n {{ font-size:13px; color:var(--muted); font-weight:400; }} .note {{ color:var(--muted); margin:0 0 12px; max-width:920px; }}
.legend b {{ margin-right:4px; }} .g {{ color:#169c16; }} .r {{ color:#d81b1b; }} .o {{ color:#f08000; }} .b {{ color:#1f63ff; }}
nav {{ position:sticky; top:0; background:var(--bg); padding:8px 20px; border-bottom:1px solid var(--line); z-index:2; }}
nav a {{ margin-right:14px; color:inherit; font-size:14px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(420px, 1fr)); gap:14px; padding-bottom:10px; }}
.card {{ margin:0; background:var(--card); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
.card img {{ display:block; width:100%; height:auto; background:#fff; cursor:zoom-in; }}
.card figcaption {{ padding:8px 10px; font-size:13px; color:var(--muted); }} .card figcaption b {{ color:var(--fg); }}
.outs {{ display:flex; flex-wrap:wrap; gap:8px; align-items:flex-start; padding:8px 10px 0; border-top:1px dashed var(--line); }}
.outs span {{ width:100%; font-size:12px; color:var(--muted); }}
.outs img.out {{ max-width:100%; height:auto; width:auto; max-height:260px; background:#fff; outline:1px solid var(--line); cursor:zoom-in; }}
@media (max-width:480px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style></head><body>
<header><h1>Lỗi nặng của bộ tách hình — DocLayNet, {html.escape(' + '.join(summary['subsets']))}</h1>
<p class="note">{html.escape(stats)}</p>
<p class="legend"><b class="g">▭ xanh lá</b>hình do người gán nhãn &nbsp; <b class="r">▭ đỏ nét đứt</b>ảnh ta xuất ra (đã gồm lề 4 pt)
&nbsp; <b class="o">● cam</b>chữ ngoài hình bị lọt vào ảnh &nbsp; <b class="b">● xanh dương</b>chữ của hình bị cắt mất</p></header>
<nav>{''.join(nav)}</nav><main>{''.join(sections)}</main>
<script>document.querySelectorAll('.card img').forEach(i => i.addEventListener('click', () => window.open(i.src)));</script>
</body></html>"""
    path.write_text(page, encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, required=True, help="Folder holding DocLayNet-train/-val/-test")
    ap.add_argument("--subset", action="append", choices=SUBSETS, help="Repeatable; default: tune")
    ap.add_argument("--limit", type=int, default=0, help="Random sample of N pages (0 = all)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--disable-rule", action="append", default=[], help="Ablation: drop a _VECTOR_CLUSTER_RULES entry")
    ap.add_argument(
        "--detector", choices=DETECTORS, default="heuristic",
        help="heuristic (rule-based Phases 2-5) or egret (Egret ONNX model, needs tools/models/egret_medium.onnx)",
    )
    ap.add_argument("--overlays", type=int, default=0, help="Render the N worst pages (not allowed on holdout)")
    ap.add_argument("--gallery", type=int, default=0, help="HTML page with N examples per severity category")
    ap.add_argument("--cache-dir", type=Path, default=Path(tempfile.gettempdir()) / "max_luka_doclaynet_eval")
    ap.add_argument("--out", type=Path, default=None, help="Run folder (default: <cache-dir>/runs/<name>)")
    args = ap.parse_args(argv)

    subsets = args.subset or ["tune"]
    if (args.overlays or args.gallery) and "holdout" in subsets:
        ap.error("--overlays/--gallery are not allowed on the holdout subset: inspecting it would turn it into tuning data")
    if args.disable_rule:
        sys.path.insert(0, str(SRC_DIR))
        import figure_detector.vector as vec

        known = {r.__name__ for r in vec._VECTOR_CLUSTER_RULES}
        unknown = sorted(set(args.disable_rule) - known)
        if unknown:
            ap.error(f"unknown rule(s) {unknown}; known: {sorted(known)}")

    index = build_index(args.data, args.cache_dir)
    entries = [e for e in index if e["subset"] in subsets]
    if args.limit and args.limit < len(entries):
        entries = sorted(random.Random(args.seed).sample(entries, args.limit), key=lambda e: (e["file"], e["rg"], e["row"]))

    if args.detector == "egret" and args.disable_rule:
        ap.error("--disable-rule only applies to the heuristic detector")
    if args.detector == "egret" and not EGRET_MODEL.is_file():
        ap.error(f"Egret model missing: {EGRET_MODEL} (build it with dev\\egret\\export_onnx.py)")
    fp = detector_fingerprint(args.disable_rule, args.detector)
    raw = run_pages(entries, args.disable_rule, args.workers, args.cache_dir / "pages" / f"{fp}.jsonl", args.detector)
    gt = load_ground_truth(entries, args.workers, args.cache_dir)
    results = [score(r, gt[r["page_hash"]]) for r in raw]
    visibility = load_visibility(results, fp, args.workers, args.cache_dir)
    for r in results:
        if "sev" in r:
            r["sev"] = apply_visibility(r["sev"], visibility[r["page_hash"]])

    name = "+".join(subsets) + (f"-n{args.limit}s{args.seed}" if args.limit else "") + f"-{args.detector}-{fp}"
    out = args.out or args.cache_dir / "runs" / name
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "subsets": subsets, "limit": args.limit, "seed": args.seed, "detector": args.detector,
        "detector_fingerprint": fp,
        "disabled_rules": args.disable_rule, **summarize(results),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    worst = sorted(results, key=_error_weight, reverse=True)[:50]
    (out / "worst_pages.json").write_text(json.dumps([
        {k: r.get(k) for k in ("subset", "doc", "page_no", "page_hash", "error")}
        | ({"figures": [f["status"] for f in r["sev"]["figures"]], "images": [p["status"] for p in r["sev"]["preds"]]}
           if "sev" in r else {})
        for r in worst
    ], indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    if args.overlays:
        paths = write_overlays(results, out / "overlays", args.overlays)
        print(f"Wrote {len(paths)} overlay(s) -> {out / 'overlays'}")
    if args.gallery:
        write_gallery(results, summary, out / "gallery.html", args.gallery, args.seed)
        print(f"Wrote gallery -> {out / 'gallery.html'}")
    print(f"Run folder -> {out}")


if __name__ == "__main__":
    main()
