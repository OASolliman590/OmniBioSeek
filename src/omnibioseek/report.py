"""Human-readable run reporting."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from omnibioseek.models import DatasetRecord, SampleRecord


def write_report(
    path: str | Path,
    *,
    profile_name: str,
    datasets: list[DatasetRecord],
    samples: list[SampleRecord],
    warnings: list[str],
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    eligibility = Counter(item.eligibility.value for item in datasets)
    treatments = Counter(item.treatment.category.value for item in samples)
    lines = [
        f"# OmniBioSeek run: {profile_name}",
        "",
        "## Discovery and curation",
        "",
        f"- Datasets: {len(datasets)}",
        f"- Samples: {len(samples)}",
        *[f"- {key}: {value}" for key, value in sorted(eligibility.items())],
        "",
        "## Treatments",
        "",
        *([f"- {key}: {value}" for key, value in sorted(treatments.items())] or ["- No sample treatment metadata"]),
        "",
        "## Warnings",
        "",
        *([f"- {warning}" for warning in warnings] or ["- None"]),
        "",
        "## Scientific safeguards",
        "",
        "- Raw sequencing and raw mass-spectrometry files are manifest-only.",
        "- Cells are never treated as biological replicates.",
        "- Exact profile criteria are not broadened when no matches are found.",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output

