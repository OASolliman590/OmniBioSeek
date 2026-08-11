"""Shared repository parsing helpers."""

from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
from pathlib import PurePosixPath
from typing import Any

from omnibioseek.models import FileKind, Modality

RAW_SUFFIXES = (
    ".fastq",
    ".fastq.gz",
    ".fq",
    ".fq.gz",
    ".sra",
    ".bam",
    ".cram",
    ".raw",
    ".wiff",
    ".mzml",
)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for pattern in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def infer_modality(*texts: str) -> list[Modality]:
    text = " ".join(texts).casefold()
    modalities: list[Modality] = []
    if any(term in text for term in ("single cell", "single-cell", "single nucleus", "snrna", "scrna")):
        modalities.append(Modality.SINGLE_CELL)
    if any(term in text for term in ("proteom", "mass spectrom", "lc-ms", "lc/ms")):
        modalities.append(Modality.PROTEOMICS)
    if any(term in text for term in ("transcript", "rna-seq", "rna seq", "expression profil", "microarray")):
        modalities.append(Modality.TRANSCRIPTOMICS)
    if "metabolom" in text:
        modalities.append(Modality.METABOLOMICS)
    if "genom" in text and not modalities:
        modalities.append(Modality.GENOMICS)
    return list(dict.fromkeys(modalities or [Modality.OTHER]))


def classify_file(name: str, category: str = "") -> FileKind:
    lowered = name.casefold()
    category_lower = category.casefold()
    if lowered.endswith(RAW_SUFFIXES) or "raw" in category_lower:
        return FileKind.RAW
    if any(term in category_lower for term in ("result", "search", "processed", "quantification")):
        return FileKind.PROCESSED
    if any(term in lowered for term in ("matrix", "count", "expression", "protein", "peptide")):
        return FileKind.PROCESSED
    if any(term in lowered for term in ("metadata", "sample", "design", "sdrf")):
        return FileKind.METADATA
    return FileKind.UNKNOWN


def file_format(name: str) -> str | None:
    suffixes = PurePosixPath(name).suffixes
    return "".join(suffixes).lstrip(".") or None


def strip_html(text: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", text)).strip()

