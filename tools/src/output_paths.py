"""Output file naming: unsafe-name sanitizing, `_2`/`_3` collision numbering, post-output cleanup."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from path_guards import (
    assert_local_no_unc_path,
    assert_safe_output_path,
    safe_clean_dir,
    sanitize_output_filename,
)


def prepare_sanitized_output_path(raw_path_str: str, label: str) -> Path:
    """Reject path-level attacks (UNC, non-FS, NTFS ADS, symlinks) while auto-sanitizing unsafe filenames."""
    raw = raw_path_str.strip()
    if re.match(r"^[A-Za-z0-9_.-]+::", raw) and not raw.lower().startswith("filesystem::"):
        raise ValueError(f"Refusing non-filesystem path for {label}: {raw}")
    if not raw.lower().startswith(("file://", "http://", "https://")) and re.match(r"^[A-Za-z]{2,}:", raw):
        raise ValueError(f"Refusing non-filesystem path for {label}: {raw}")
    assert_local_no_unc_path(raw, label)

    parent_str, leaf_str = os.path.split(raw)
    abs_parent = Path(os.path.abspath(parent_str)) if parent_str else Path(os.path.abspath("."))
    cand = abs_parent / leaf_str
    sanitized, changed = sanitize_output_filename(cand)
    if changed:
        print(f"Sanitized unsafe output filename -> {sanitized}")
    dest = assert_safe_output_path(sanitized, label=label, is_directory=False)
    assert dest is not None
    return dest


def get_indexed_file_path(base_path: Path, index: int) -> Path:
    """Return `base_path` for index<=1, otherwise `<stem>_<index><ext>` in same directory."""
    if index <= 1:
        return base_path
    return base_path.with_name(f"{base_path.stem}_{index}{base_path.suffix}")


def find_next_available_index(candidate_paths: list[Path]) -> int:
    """Find lowest >=1 suffix index where none of `candidate_paths` exist on disk."""
    idx = 1
    while True:
        if not any(os.path.lexists(get_indexed_file_path(base, idx)) for base in candidate_paths):
            return idx
        idx += 1


def clean_dir_after_outputs(clean_dir: str, protected_paths: list[Path]) -> None:
    """Clean `clean_dir` once outputs exist, warning instead of failing so agents never re-run packaging.

    `clean_dir` was already validated before any output was written; a failure here (e.g. a junction
    planted mid-run) must not turn a finished run into a reported failure that creates `_2` duplicates.
    """
    try:
        safe_clean_dir(clean_dir, protected_paths=protected_paths)
    except (ValueError, OSError) as exc:
        reason = " ".join(str(exc).split())
        print(f"WARNING: Skipped cleaning temp directory; outputs are complete | Reason: {reason}", file=sys.stderr)
