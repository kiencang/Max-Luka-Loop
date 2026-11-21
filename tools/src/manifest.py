"""Manifest stdout helpers shared by figure extraction (Step 1 of the translation workflow).

Kept dependency-free (stdlib only, no other tools/src module) so the figure detector does not have to
import the HTML packager just to print its manifest.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

_MANIFEST_MARKER_RX = re.compile(r"===\s*MANIFEST\s+JSON\s+(?:START|END)\s*===", re.IGNORECASE)


def _sanitize_manifest_text(text: str) -> str:
    """Strip control characters and neutralize stdout manifest delimiter spoofing."""
    cleaned = re.sub(r"[\x00-\x1F\x7F]+", " ", str(text)).strip()
    return _MANIFEST_MARKER_RX.sub("[manifest-marker]", cleaned)


def limit_manifest_words(text: str | None, max_words: int = 20) -> str:
    """Truncate caption/context text cleanly to `max_words` words for compact stdout output."""
    if text is None:
        return ""
    normalized = _sanitize_manifest_text(str(text))
    if not normalized or max_words <= 0:
        return normalized
    words = normalized.split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "..."


def emit_compacted_manifest_stdout(
    manifest_dict: dict,
    manifest_path: Path,
    max_words: int = 20,
    max_bytes: int = 16384,
) -> None:
    """Print compacted manifest JSON to stdout when within `max_bytes`, otherwise print disk path."""
    compacted = copy.deepcopy(manifest_dict)
    if compacted.get("pdf") is not None:
        compacted["pdf"] = _sanitize_manifest_text(str(compacted["pdf"]))
    for fig in compacted.get("figures", []):
        if isinstance(fig, dict):
            if fig.get("caption") is not None:
                fig["caption"] = limit_manifest_words(str(fig["caption"]), max_words=max_words)
            if fig.get("context") is not None:
                fig["context"] = limit_manifest_words(str(fig["context"]), max_words=max_words)

    stdout_json = json.dumps(compacted, ensure_ascii=False, indent=2)
    stdout_bytes = len(stdout_json.encode("utf-8"))
    if stdout_bytes <= max_bytes:
        print("=== MANIFEST JSON START ===")
        print(stdout_json)
        print("=== MANIFEST JSON END ===")
    else:
        print(
            f"Manifest too large for stdout ({stdout_bytes:,} bytes > {max_bytes:,} limit); "
            f"read the file in parts -> {os.path.abspath(str(manifest_path))}"
        )
