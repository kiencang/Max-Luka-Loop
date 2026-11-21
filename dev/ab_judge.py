"""Blind left/right A/B judging of two figure-detector versions on DocLayNet tune pages (dev-only).

The metrics in eval_doclaynet.py can mislead (pdf_cells false positives, overlays that hide cut text), so every
detector change is also judged by eye: this tool picks figures whose output crops differ between two cached
eval_doclaynet.py runs, renders exactly the images extract_assets.exe would write (+4 pt padding), shuffles the
sides and writes a self-contained local HTML page. The judge pastes back a code such as "AB5:LREX..."; `score`
decodes it with the hidden key and reports wins with a sign test.

    python -X utf8 dev\\ab_judge.py build --old <fp> --new <fp> --n 50 --seed 5 --code AB5
    python -X utf8 dev\\ab_judge.py score AB5:LREX...

Both fingerprints must already have a cached tune run (eval_doclaynet.py --subset tune writes
<cache-dir>/pages/<fp>.jsonl). Only tune pages are ever shown: the holdout set must never be looked at. Pages contain
crops of third-party papers, so keep them local; do not publish them. Finished rounds (key + answers, no images) are
archived in dev/ab_history/ so later rounds skip documents already judged.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import math
import random
import sys
import tempfile
from pathlib import Path

DEV_DIR = Path(__file__).resolve().parent
HISTORY_DIR = DEV_DIR / "ab_history"
sys.path.insert(0, str(DEV_DIR))

import eval_doclaynet as ev  # noqa: E402

VERDICTS = {"L": "left", "R": "right", "E": "equal", "X": "both_bad"}


# --------------------------------------------------------------------------- scoring (standard library only)

def decode(answers: str, key_items: list[dict]) -> dict[str, list[int]]:
    """Map L/R/E/X answers to new_better / old_better / equal / both_bad item ids using the hidden side key."""
    if len(answers) != len(key_items):
        raise ValueError(f"{len(answers)} answers for {len(key_items)} items")
    out: dict[str, list[int]] = {"new_better": [], "old_better": [], "equal": [], "both_bad": []}
    for a, item in zip(answers, key_items):
        if a not in VERDICTS:
            raise ValueError(f"unknown answer {a!r} (expected one of {''.join(VERDICTS)})")
        if a == "E":
            out["equal"].append(item["id"])
        elif a == "X":
            out["both_bad"].append(item["id"])
        else:
            new_won = (a == "L") == item["new_on_left"]
            out["new_better" if new_won else "old_better"].append(item["id"])
    return out


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact binomial sign test on the decisive pairs."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n
    return min(1.0, 2 * tail)


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


# --------------------------------------------------------------------------- build

def _load_pages(cache: Path, fp: str) -> dict[str, dict]:
    path = cache / "pages" / f"{fp}.jsonl"
    if not path.exists():
        sys.exit(f"no cached run for fingerprint {fp}: run eval_doclaynet.py --subset tune with that detector first")
    return {r["page_hash"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def _judged_docs(out_dir: Path) -> set[str]:
    docs = set()
    for folder in (HISTORY_DIR, out_dir):
        for kf in folder.glob("ab_key_*.json") if folder.exists() else []:
            docs.update(i["doc"] for i in json.loads(kf.read_text(encoding="utf-8"))["items"])
    return docs


def build(args: argparse.Namespace) -> None:
    import pymupdf
    import pyarrow.parquet as pq

    cache, out_dir = args.cache_dir, args.out_dir or args.cache_dir / "ab"
    out_dir.mkdir(parents=True, exist_ok=True)
    if (out_dir / f"ab_key_{args.code}.json").exists() or (HISTORY_DIR / f"ab_key_{args.code}.json").exists():
        sys.exit(f"round {args.code} already exists; pick a new code")
    gt = {h: v for h, v in map(json.loads, (cache / "ground_truth_v1.jsonl").read_text(encoding="utf-8").splitlines())}
    old, new = _load_pages(cache, args.old), _load_pages(cache, args.new)

    def images_for(r: dict, g) -> list:
        page = (0.0, 0.0, gt[r["page_hash"]]["w"], gt[r["page_hash"]]["h"])
        return [ev.expand(tuple(p), ev.RENDER_PAD, page) for p in r.get("preds", []) if ev.intersection(tuple(p), tuple(g)) > 0]

    cands = []
    for h, rn in new.items():
        ro = old.get(h)
        # tune only: the holdout set must never be inspected visually
        if rn.get("subset") != "tune" or ro is None or "error" in rn or "error" in ro or h not in gt:
            continue
        for k, g in enumerate(b for c, b, _ in gt[h]["boxes"] if c == "Picture"):
            a, b = images_for(ro, g), images_for(rn, g)
            if (a or b) and sorted(tuple(round(v) for v in x) for x in a) != sorted(tuple(round(v) for v in x) for x in b):
                cands.append((rn, k, a, b))

    rng = random.Random(args.seed)
    rng.shuffle(cands)
    seen = set() if args.allow_repeat_docs else _judged_docs(out_dir)
    print(f"figures with a changed crop: {len(cands)}; documents excluded as already judged: {len(seen)}")
    picked = []
    for c in cands:
        if c[0]["doc"] not in seen:
            seen.add(c[0]["doc"])
            picked.append(c)
            if len(picked) == args.n:
                break
    print(f"picked {len(picked)} figures")

    def render(page, rects, scale=1.6) -> list[str]:
        out = []
        for r in rects:
            pix = page.get_pixmap(clip=pymupdf.Rect(r) & page.rect, matrix=pymupdf.Matrix(scale, scale))
            out.append(base64.b64encode(pix.tobytes("jpeg", jpg_quality=80)).decode())
        return out

    cards, key = [], []
    for i, (r, k, a, b) in enumerate(picked, 1):
        rec = pq.ParquetFile(r["file"]).read_row_group(r["rg"], columns=["pdf"]).to_pylist()[r["row"]]
        with pymupdf.open(stream=rec["pdf"], filetype="pdf") as doc:
            old_imgs, new_imgs = render(doc[0], a), render(doc[0], b)
        new_on_left = rng.random() < 0.5
        left, right = (new_imgs, old_imgs) if new_on_left else (old_imgs, new_imgs)
        cards.append(f'<section class="item" hidden><div class="pair">{_side("Trái", left)}{_side("Phải", right)}</div></section>')
        key.append({"id": i, "doc": r["doc"], "page_no": r["page_no"], "figure": k, "new_on_left": new_on_left,
                    "old_boxes": a, "new_boxes": b})
    (out_dir / f"ab_key_{args.code}.json").write_text(
        json.dumps({"code": args.code, "old_fp": args.old, "new_fp": args.new, "items": key}, indent=1), encoding="utf-8", newline="\n")
    page_path = out_dir / f"ab_judge_{args.code}.html"
    page_path.write_text(PAGE.replace("{CARDS}", "".join(cards)).replace("{CODE}", html.escape(args.code)), encoding="utf-8", newline="\n")
    print(f"wrote {page_path} ({page_path.stat().st_size / 1e6:.1f} MB); key {out_dir / f'ab_key_{args.code}.json'}")


def _side(label: str, imgs: list[str]) -> str:
    body = "".join(f'<img src="data:image/jpeg;base64,{s}" alt="ảnh xuất ra">' for s in imgs) if imgs \
        else '<div class="none">Không có ảnh nào<br>(hình bị bỏ sót)</div>'
    return f'<div class="side"><div class="lab">{label}</div><div class="imgs">{body}</div></div>'


# --------------------------------------------------------------------------- score

def score(args: argparse.Namespace) -> None:
    code, _, answers = args.result.partition(":")
    out_dir = args.out_dir or args.cache_dir / "ab"
    key_path = next((p for p in (out_dir / f"ab_key_{code}.json", HISTORY_DIR / f"ab_key_{code}.json") if p.exists()), None)
    if key_path is None:
        sys.exit(f"no key for round {code}")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    res = decode(answers.strip(), key["items"])
    w, l = len(res["new_better"]), len(res["old_better"])
    lo, hi = wilson(w, w + l)
    print(f"{code}: new better {w}, old better {l}, equal {len(res['equal'])}, both bad {len(res['both_bad'])}")
    print(f"new wins {w}/{w + l} decisive pairs (95% CI {lo:.0%}-{hi:.0%}), sign test p={sign_test(w, l):.3g}")
    for name in ("old_better", "both_bad"):
        for i in res[name]:
            it = key["items"][i - 1]
            print(f"  {name:10} #{i:<3} {it['doc']} p{it['page_no']} fig{it['figure']}")
    key["answers"], key["result"] = answers.strip(), res
    HISTORY_DIR.mkdir(exist_ok=True)
    (HISTORY_DIR / f"ab_key_{code}.json").write_text(json.dumps(key, indent=1), encoding="utf-8", newline="\n")
    print(f"archived to {HISTORY_DIR / f'ab_key_{code}.json'}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", type=Path, default=Path(tempfile.gettempdir()) / "max_luka_doclaynet_eval")
    ap.add_argument("--out-dir", type=Path, default=None, help="Where pages and keys go (default: <cache-dir>/ab)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write a blind judging page")
    b.add_argument("--old", required=True, help="detector fingerprint of the baseline run")
    b.add_argument("--new", required=True, help="detector fingerprint of the candidate run")
    b.add_argument("--n", type=int, default=50)
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--code", required=True, help="round name, e.g. AB5")
    b.add_argument("--allow-repeat-docs", action="store_true", help="do not skip documents judged in earlier rounds")
    s = sub.add_parser("score", help="decode a pasted result code and archive the round")
    s.add_argument("result", help='e.g. "AB5:LREX..."')
    args = ap.parse_args(argv)
    (build if args.cmd == "build" else score)(args)


PAGE = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>So sánh cách cắt hình</title>
<style>
:root { --bg:#f6f7f9; --fg:#1d2330; --muted:#5b6475; --card:#fff; --line:#dfe3ea; --acc:#2f6fdb; }
@media (prefers-color-scheme: dark) { :root { --bg:#14171d; --fg:#e7eaf0; --muted:#a3abba; --card:#1d2129; --line:#2d333e; --acc:#7aa7ff; } }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.55 system-ui, "Segoe UI", sans-serif; }
main { max-width:1200px; margin:auto; padding:18px 16px 40px; }
h1 { font-size:20px; margin:0 0 4px; font-weight:600; }
.note { color:var(--muted); margin:0 0 14px; }
.bar { display:flex; align-items:center; gap:12px; margin:0 0 12px; flex-wrap:wrap; }
.progress { font-weight:600; }
.pair { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:14px; }
@media (max-width:700px) { .pair { grid-template-columns:1fr; } }
.side { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px; }
.lab { font-weight:600; margin-bottom:8px; }
.imgs { display:flex; flex-direction:column; gap:10px; align-items:center; background:#8a8f99; padding:10px; border-radius:6px; }
.imgs img { max-width:100%; height:auto; background:#fff; display:block; }
.none { color:#fff; padding:40px 10px; text-align:center; }
.choices { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:10px; margin:14px 0 6px; }
@media (max-width:700px) { .choices { grid-template-columns:repeat(2, minmax(0, 1fr)); } }
button { font:inherit; padding:12px 10px; border-radius:8px; border:1px solid var(--line); background:var(--card); color:var(--fg); cursor:pointer; }
button:hover { border-color:var(--acc); }
button.primary { border-color:var(--acc); color:var(--acc); font-weight:600; }
.done { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
textarea { width:100%; box-sizing:border-box; font:14px ui-monospace, Consolas, monospace; padding:10px; border-radius:8px; border:1px solid var(--line); background:var(--bg); color:var(--fg); }
kbd { border:1px solid var(--line); border-radius:4px; padding:0 5px; font-size:12px; }
</style></head><body><main>
<h1>Cách cắt nào tốt hơn cho bản dịch?</h1>
<p class="note">Mỗi lượt là cùng một hình, hai cách cắt (đúng ảnh sẽ xuất ra; nền xám chỉ để thấy rõ biên ảnh). Bên nào là bản cũ hay mới được xáo ngẫu nhiên. Phím tắt: <kbd>1</kbd> trái · <kbd>2</kbd> phải · <kbd>3</kbd> như nhau · <kbd>4</kbd> cả hai đều tệ · <kbd>Backspace</kbd> quay lại.</p>
<div class="bar"><span class="progress" id="prog"></span><button id="back" type="button">← Quay lại</button></div>
{CARDS}
<div class="choices" id="choices">
<button type="button" data-v="L">1 · Trái tốt hơn</button>
<button type="button" data-v="R">2 · Phải tốt hơn</button>
<button type="button" data-v="E">3 · Như nhau</button>
<button type="button" data-v="X">4 · Cả hai đều tệ</button>
</div>
<section class="done" id="done" hidden>
<p><b>Xong.</b> Hãy sao chép mã dưới đây và dán vào khung chat:</p>
<textarea id="code" rows="3" readonly></textarea>
<p class="note" id="copied"></p>
<button type="button" class="primary" id="copy">Sao chép mã</button>
</section>
<script>
const items = [...document.querySelectorAll('.item')];
const total = items.length, store = 'max-luka-ab-{CODE}';
let answers = [];
try { answers = JSON.parse(localStorage.getItem(store) || '[]'); } catch (e) { answers = []; }
function save() { try { localStorage.setItem(store, JSON.stringify(answers)); } catch (e) {} }
function show() {
  const i = answers.length;
  items.forEach((el, k) => el.hidden = k !== i);
  const finished = i >= total;
  document.getElementById('choices').hidden = finished;
  document.getElementById('done').hidden = !finished;
  document.getElementById('prog').textContent = finished ? 'Đã chấm ' + total + '/' + total : 'Hình ' + (i + 1) + '/' + total;
  document.getElementById('back').hidden = i === 0;
  if (finished) document.getElementById('code').value = '{CODE}:' + answers.join('');
  window.scrollTo(0, 0);
}
function pick(v) { if (answers.length < total) { answers.push(v); save(); show(); } }
document.querySelectorAll('#choices button').forEach(b => b.addEventListener('click', () => pick(b.dataset.v)));
document.getElementById('back').addEventListener('click', () => { answers.pop(); save(); show(); });
document.addEventListener('keydown', e => {
  const m = {'1':'L','2':'R','3':'E','4':'X'}[e.key];
  if (m) pick(m); else if (e.key === 'Backspace' && answers.length) { answers.pop(); save(); show(); e.preventDefault(); }
});
document.getElementById('copy').addEventListener('click', async () => {
  const t = document.getElementById('code');
  t.select();
  let ok = false;
  try { await navigator.clipboard.writeText(t.value); ok = true; } catch (e) { try { ok = document.execCommand('copy'); } catch (e2) {} }
  document.getElementById('copied').textContent = ok ? 'Đã sao chép.' : 'Hãy bôi đen mã trong ô trên rồi sao chép thủ công (Ctrl+C).';
});
show();
</script></main></body></html>"""


if __name__ == "__main__":
    main()
