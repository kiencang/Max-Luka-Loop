"""Locate the latest PDF attachment in an agent transcript.jsonl (Antigravity `-TranscriptPath`)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from path_guards import (
    assert_local_no_unc_path,
    file_uri_to_local_path,
)


def _resolve_pdf_from_line(line: str) -> str | None:
    if '"type"' not in line or "USER_INPUT" not in line or "pdf" not in line.lower():
        return None
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(entry, dict) or entry.get("type") != "USER_INPUT":
        return None
    media = entry.get("media")
    if not isinstance(media, list):
        return None
    for item in media:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "")
        mime = str(item.get("mime_type") or "")
        if uri and (mime == "application/pdf" or uri.lower().endswith(".pdf")):
            assert_local_no_unc_path(uri, "TranscriptMediaUri")
            return file_uri_to_local_path(uri)
    return None


def find_latest_pdf_in_transcript(transcript_path: str | Path) -> Path:
    """Locate the most recent USER_INPUT PDF attachment inside transcript.jsonl."""
    assert_local_no_unc_path(transcript_path, "-TranscriptPath")
    raw = str(transcript_path or "").strip()
    if not raw or not os.path.isfile(raw):
        raise FileNotFoundError(f"Transcript file not found: {transcript_path}")
    abs_transcript = Path(os.path.abspath(raw))
    assert_local_no_unc_path(abs_transcript, "-TranscriptPath")

    lines = abs_transcript.read_text(encoding="utf-8-sig").splitlines()
    for line in reversed(lines):
        found = _resolve_pdf_from_line(line)
        if found:
            assert_local_no_unc_path(found, "ResolvedPdf")
            if not os.path.isfile(found):
                raise FileNotFoundError(f"Resolved PDF file does not exist: {found}")
            return Path(os.path.abspath(found))
    raise RuntimeError(f"No PDF attachment found in USER_INPUT entries of transcript: {abs_transcript}")
