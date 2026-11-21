"""Layout-aware PDF figure, diagram, and chart detector (6-phase linear pipeline on PyMuPDF).

Architecture (strictly top-to-bottom, zero circular calls):
  Phase 1 — analyze_page()          : Build PageContext once (text blocks, captions, words, rules).
  Phase 2 — detect_raster_regions() : Extract foreground bitmaps, detect scanned pages, drop banners/watermarks.
  Phase 3 — detect_vector_regions() : Filter background drawings, cluster vectors, classify via RegionFeatures.
  Phase 4 — link_captions()         : Match captions (vertical > side), arbitrate conflicts, propagate & recover.
  Phase 5 — merge_candidates()      : Merge multi-panel figures under strict anti-swallow geometric invariants.
  Phase 6 — finalize & render       : Annotate origin/table_cell placement, sort reading order, emit PNG + manifest.

Submodules, in layering order (each imports only from the ones listed before it):
  model          lazy `pymupdf` handle, DetectorConfig, caption regexes, data models
  geometry       rectangle primitives and drawing-shape predicates
  text           Phase 1 (text analysis, caption classification)
  caption_match  caption matching primitives shared by Phases 2–6
  raster         Phase 2
  vector         Phase 3
  captions       Phase 4
  merge          Phase 5
  pipeline       Phases 1–5 per page (+ origin annotation, axis-label expansion)
  egret          optional Phases 2–5 replacement: Egret Medium ONNX layout model (onnxruntime, loaded lazily)
  extract        Phase 6 (PNG rendering + manifest entries); `detector=` picks pipeline or egret

This package keeps the public names of the former single-file `figure_detector.py`.
"""

from __future__ import annotations

from .captions import link_captions
from .extract import extract_images
from .merge import merge_candidates
from .model import (
    DEFAULT_CONFIG,
    CandidateBox,
    DetectorConfig,
    FilterDecision,
    PageContext,
    PageTableInfo,
    TextBlock,
    _ensure_pymupdf,
)
from .pipeline import collect_page_figures, detect_page_figures_debug
from .raster import detect_raster_regions
from .text import _classify_text_block, _clean_text, _split_dict_block, analyze_page
from .vector import detect_vector_regions

__all__ = [
    "DEFAULT_CONFIG",
    "CandidateBox",
    "DetectorConfig",
    "FilterDecision",
    "PageContext",
    "PageTableInfo",
    "TextBlock",
    "_classify_text_block",
    "_clean_text",
    "_ensure_pymupdf",
    "_split_dict_block",
    "analyze_page",
    "collect_page_figures",
    "detect_page_figures_debug",
    "detect_raster_regions",
    "detect_vector_regions",
    "extract_images",
    "link_captions",
    "merge_candidates",
]
