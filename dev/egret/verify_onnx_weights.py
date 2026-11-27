"""Check that the Egret ONNX model holds exactly the official weights of the pinned Hugging Face revision (dev only).

Needs numpy and onnx only (no torch). Every tensor of model.safetensors must be found in the ONNX file:

  * as stored, or transposed (Linear weights stored for MatMul): bytes must be identical;
  * Conv + BatchNorm2d (encoder/decoder): torch.onnx folds the norm into the conv, so the folded
    W * g / sqrt(var + eps) and beta + (b - mean) * g / sqrt(var + eps) are recomputed and compared;
  * frozen BatchNorm of the backbone (DFineFrozenBatchNorm2d): exported as `scale` / `shift` constants,
    recomputed exactly as its forward does.

Tensors only used in training are listed and skipped: `num_batches_tracked`, `denoising_class_embed`, and the
heads of the intermediate decoder layers (`class_embed.0-2`, `lqe_layers.0-2`), which feed auxiliary losses only.
A few scalars (`num_points_scale`, `decoder.up`) are folded into other constants and are reported as such.

Usage:
    python -X utf8 dev\\egret\\verify_onnx_weights.py                       # downloads the pinned weights (~78 MB)
    python -X utf8 dev\\egret\\verify_onnx_weights.py --safetensors <path>  # or uses a local copy (hash checked)
Exit code 1 when anything does not match.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = "docling-project/docling-layout-egret-medium"
MODEL_REVISION = "77ede7cc7bed96d853c58f319734803d6ea2ea5c"
MODEL_SAFETENSORS_SHA256 = "e7fc5b9a353826c123c5d03efc230909ac02b93e26293ec7cb4db8978fe9e3af"
ONNX_SHA256 = "06da7202c1fcfc9eb984830857c51c1e3993e8ba36a21f76c74d4c0756d1fbcc"
BN_EPS = 1e-5  # config.batch_norm_eps and the constant in DFineFrozenBatchNorm2d
FOLD_RTOL = 1e-5

TRAINING_ONLY = ("num_batches_tracked", "denoising_class_embed.", "decoder.class_embed.", "decoder.lqe_layers.")
FOLDED_SCALARS = ("num_points_scale", "decoder.up")
_DTYPES = {"F32": np.float32, "F16": np.float16, "I64": np.int64, "I32": np.int32, "BOOL": np.bool_}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_safetensors(dest_dir: Path) -> Path:
    url = f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/model.safetensors"
    dest = dest_dir / "model.safetensors"
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url, timeout=120) as resp, open(dest, "wb") as out:  # noqa: S310 - fixed https URL
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    return dest


def read_safetensors(path: Path) -> dict[str, np.ndarray]:
    """Minimal safetensors reader: 8-byte little-endian header size, JSON header, raw little-endian data."""
    data = path.read_bytes()
    (n,) = struct.unpack("<Q", data[:8])
    header = json.loads(data[8 : 8 + n])
    header.pop("__metadata__", None)
    blob = memoryview(data)[8 + n :]
    out = {}
    for name, info in header.items():
        start, end = info["data_offsets"]
        out[name] = np.frombuffer(blob[start:end], dtype=_DTYPES[info["dtype"]]).reshape(info["shape"])
    return out


def _onnx_tensors(onnx_path: Path) -> list[np.ndarray]:
    import onnx
    from onnx import numpy_helper

    model = onnx.load(str(onnx_path))
    arrays = [numpy_helper.to_array(t) for t in model.graph.initializer]
    for node in model.graph.node:
        if node.op_type == "Constant":
            arrays += [numpy_helper.to_array(a.t) for a in node.attribute if a.name == "value" and a.t.dims]
    return arrays


def _key(a: np.ndarray) -> str:
    a = np.ascontiguousarray(a)
    return hashlib.sha256(a.tobytes() + str(a.shape).encode() + a.dtype.str.encode()).hexdigest()


def _rel_err(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.float64) - b.astype(np.float64)).max() / (np.abs(b).max() + 1e-12))


def verify(weights: dict[str, np.ndarray], onnx_arrays: list[np.ndarray]) -> bool:
    exact = {_key(a) for a in onnx_arrays}
    by_size: dict[int, list[np.ndarray]] = {}
    for a in onnx_arrays:
        if a.dtype == np.float32:
            by_size.setdefault(a.size, []).append(a.ravel())

    def closest(x: np.ndarray) -> float:
        return min((_rel_err(c, x.ravel()) for c in by_size.get(x.size, [])), default=float("inf"))

    done: set[str] = set()
    n_exact = n_t = 0
    for name, a in weights.items():
        if _key(a) in exact:
            n_exact += 1
            done.add(name)
        elif a.ndim == 2 and _key(np.ascontiguousarray(a.T)) in exact:
            n_t += 1
            done.add(name)

    n_fold = n_frozen = 0
    worst = 0.0
    failures: list[str] = []
    for name in list(weights):
        # (conv, norm) naming: DFineConvNormLayer, HGNetV2ConvLayer, and nn.Sequential(conv, batchnorm) input projections.
        for conv_sfx, norm_sfx in ((".conv.weight", ".norm"), (".convolution.weight", ".normalization"), (".0.weight", ".1")):
            if not name.endswith(conv_sfx):
                continue
            base = name[: -len(conv_sfx)]
            norm = base + norm_sfx
            if norm + ".running_var" not in weights:
                continue
            g, beta, mean, var = (weights[norm + s].astype(np.float32) for s in (".weight", ".bias", ".running_mean", ".running_var"))
            bn_keys = {norm + s for s in (".weight", ".bias", ".running_mean", ".running_var", ".num_batches_tracked")}
            if name in done:  # conv kept as is: the backbone's frozen norm became scale/shift constants
                scale = g * (1.0 / np.sqrt(var + np.float32(BN_EPS)))
                shift = beta - mean * scale
                errs = (closest(scale), closest(shift))
                n_frozen += 1
            else:  # conv and norm folded into one Conv by torch.onnx
                s = g.astype(np.float64) / np.sqrt(var.astype(np.float64) + BN_EPS)
                w = weights[name].astype(np.float64)
                bias_name = base + conv_sfx.replace("weight", "bias")
                b = weights[bias_name].astype(np.float64) if bias_name in weights else np.zeros_like(s)
                errs = (closest(w * s.reshape(-1, *([1] * (w.ndim - 1)))), closest(beta + (b - mean) * s))
                bn_keys.add(name)
                bn_keys.add(bias_name)
                n_fold += 1
            if max(errs) > FOLD_RTOL:
                failures.append(f"{base}: folded weights not found (rel err {max(errs):.2e})")
            worst = max(worst, *errs)
            done |= bn_keys & weights.keys()

    skipped = [n for n in weights if n not in done and any(t in n for t in TRAINING_ONLY)]
    # The heads of the last decoder layer are used at inference and must have matched above.
    last = max(int(n.split(".")[3]) for n in weights if n.startswith("model.decoder.class_embed."))
    skipped = [n for n in skipped if f".class_embed.{last}." not in n and f".lqe_layers.{last}." not in n]
    folded_scalars = [n for n in weights if n not in done and any(t in n for t in FOLDED_SCALARS)]
    missing = [n for n in weights if n not in done and n not in skipped and n not in folded_scalars]
    failures += [f"{n} {list(weights[n].shape)}: not found in the ONNX model" for n in missing]

    total = sum(a.size for a in weights.values())
    print(f"safetensors tensors: {len(weights)} ({total:,} values)")
    print(f"  identical bytes: {n_exact} as stored, {n_t} transposed")
    print(f"  Conv+BatchNorm folded: {n_fold}, backbone frozen BatchNorm (scale/shift): {n_frozen}, worst rel diff {worst:.2e}")
    print(f"  training-only, not exported: {len(skipped)} ({sum(weights[n].size for n in skipped):,} values)")
    print(f"  scalars folded into other constants: {len(folded_scalars)} ({sum(weights[n].size for n in folded_scalars)} values)")
    for f in failures:
        print(f"  FAIL {f}")
    print("RESULT:", "OK - the ONNX model holds the pinned weights" if not failures else f"{len(failures)} mismatch(es)")
    return not failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx", type=Path, default=REPO_ROOT / "tools" / "models" / "egret_medium.onnx")
    ap.add_argument("--safetensors", type=Path, default=None, help="Local model.safetensors (default: download)")
    args = ap.parse_args()

    onnx_hash = _sha256(args.onnx)
    print(f"ONNX {args.onnx} sha256 {onnx_hash}" + ("" if onnx_hash == ONNX_SHA256 else "  (differs from the released model)"))
    with tempfile.TemporaryDirectory(prefix="max_luka_egret_weights_") as tmp:
        st_path = args.safetensors or fetch_safetensors(Path(tmp))
        st_hash = _sha256(st_path)
        if st_hash != MODEL_SAFETENSORS_SHA256:
            print(f"FAIL: {st_path} has sha256 {st_hash}, expected {MODEL_SAFETENSORS_SHA256} ({MODEL_ID}@{MODEL_REVISION[:12]})")
            return 1
        print(f"Weights {MODEL_ID}@{MODEL_REVISION[:12]} sha256 verified")
        ok = verify(read_safetensors(st_path), _onnx_tensors(args.onnx))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
