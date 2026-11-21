"""Compare the heuristic figure detector with the Egret ONNX detector on sample PDFs (dev only).

Runs `extract_images` with both detectors on every PDF given (default: tests/layout_samples + tests/fixtures),
prints per-document figure counts and seconds/page, and writes a local side-by-side gallery
(`gallery.html`, heuristic crops left, Egret crops right) for visual review.

    python -X utf8 dev\\egret\\compare_detectors.py
    python -X utf8 dev\\egret\\compare_detectors.py --pdf D:\\docs\\paper.pdf --out %TEMP%\\max_luka_egret_compare

Needs PyMuPDF, numpy and onnxruntime, plus tools\\models\\egret_medium.onnx (dev\\egret\\export_onnx.py).
"""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "src"))

import figure_detector as fd  # noqa: E402
from figure_detector.extract import DETECTORS  # noqa: E402


def _run(pdf: Path, out_dir: Path, detector: str) -> tuple[dict, float]:
    buf = io.StringIO()
    t0 = time.perf_counter()
    with redirect_stdout(buf):
        fd.extract_images(pdf, out_dir, 180, write_meta=True, detector=detector)
    elapsed = time.perf_counter() - t0
    return json.loads((out_dir / "manifest.json").read_text(encoding="utf-8")), elapsed


def _cell(base: Path, fig: dict | None) -> str:
    if fig is None:
        return "<td class=empty>—</td>"
    rel = os.path.relpath(base / fig["file"], start=base.parent.parent).replace("\\", "/")
    cap = html.escape((fig.get("caption") or fig.get("context") or "")[:120])
    meta = f'{fig["source"]} · {fig["placement"]} · {fig["width_px"]}×{fig["height_px"]}px'
    return f'<td><img src="{html.escape(rel)}" alt=""><div class=meta>{meta}</div><div class=cap>{cap}</div></td>'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, action="append", default=None, help="PDF to compare (repeatable)")
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "max_luka_egret_compare")
    args = ap.parse_args()

    pdfs = args.pdf or sorted(
        [*(REPO_ROOT / "tests" / "layout_samples").glob("*.pdf"), *(REPO_ROOT / "tests" / "fixtures").glob("*.pdf")]
    )
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    totals = {d: [0, 0.0] for d in DETECTORS}
    total_pages = 0
    print(f"{'document':38s} {'pages':>5s} " + " ".join(f"{d + ' figs':>15s} {'s/page':>7s}" for d in DETECTORS))
    for pdf in pdfs:
        results = {}
        for det in DETECTORS:
            out_dir = args.out / pdf.stem / det
            for old in out_dir.glob("*.png") if out_dir.exists() else ():
                old.unlink()
            results[det] = _run(pdf, out_dir, det)
        pages = results[DETECTORS[0]][0]["total_pages"]
        total_pages += pages
        line = f"{pdf.name[:38]:38s} {pages:5d} "
        for det in DETECTORS:
            man, secs = results[det]
            totals[det][0] += len(man["figures"])
            totals[det][1] += secs
            line += f"{len(man['figures']):15d} {secs / max(1, pages):7.2f} "
        print(line)

        rows.append(f'<tr><th colspan=3 class=doc>{html.escape(pdf.name)}</th></tr>')
        for pno in range(1, pages + 1):
            per = {d: [f for f in results[d][0]["figures"] if f["page"] == pno] for d in DETECTORS}
            for i in range(max(len(v) for v in per.values())):
                cells = "".join(
                    _cell(args.out / pdf.stem / d, per[d][i] if i < len(per[d]) else None) for d in DETECTORS
                )
                rows.append(f"<tr><td class=pg>p{pno}</td>{cells}</tr>")

    print(f"{'TOTAL':38s} {total_pages:5d} " + " ".join(
        f"{totals[d][0]:15d} {totals[d][1] / max(1, total_pages):7.2f}" for d in DETECTORS
    ))
    head = "".join(f"<th>{html.escape(d)}</th>" for d in DETECTORS)
    page = (
        "<!doctype html><meta charset=utf-8><title>Detector comparison</title><style>"
        "body{font:14px system-ui;margin:16px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:6px;vertical-align:top}td img{max-width:100%;max-height:420px}"
        ".doc{background:#eef;text-align:left}.pg{width:40px}.meta{color:#555;font-size:12px}"
        ".cap{font-size:12px}.empty{color:#aaa;text-align:center}</style>"
        f"<table><tr><th></th>{head}</tr>{''.join(rows)}</table>"
    )
    gallery = args.out / "gallery.html"
    gallery.write_text(page, encoding="utf-8")
    print(f"Gallery -> {gallery}")


if __name__ == "__main__":
    main()
