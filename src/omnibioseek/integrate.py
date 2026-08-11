"""Pool compatible prepared objects while guarding against confounded batch correction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    modality: str
    output_path: str | None
    studies: list[str]
    batch_corrected: bool
    reason: str


def design_is_identifiable(rows: list[dict[str, str]], batch: str, condition: str) -> bool:
    if not rows or any(batch not in row or condition not in row for row in rows):
        return False
    batches: dict[str, set[str]] = {}
    for row in rows:
        batches.setdefault(row[batch], set()).add(row[condition])
    all_conditions = {row[condition] for row in rows}
    return len(all_conditions) > 1 and any(len(values) > 1 for values in batches.values())


class IntegrationEngine:
    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def integrate(self, manifest_paths: list[str | Path]) -> list[IntegrationResult]:
        artifacts: list[dict[str, Any]] = []
        for path in manifest_paths:
            artifacts.extend(json.loads(Path(path).read_text(encoding="utf-8")))
        grouped: dict[str, list[dict[str, Any]]] = {}
        for artifact in artifacts:
            grouped.setdefault(str(artifact["modality"]), []).append(artifact)
        return [self._integrate_group(modality, group) for modality, group in grouped.items()]

    def _integrate_group(
        self, modality: str, artifacts: list[dict[str, Any]]
    ) -> IntegrationResult:
        studies = sorted({str(item["dataset_accession"]) for item in artifacts})
        if len(studies) < 2:
            return IntegrationResult(
                modality=modality,
                output_path=None,
                studies=studies,
                batch_corrected=False,
                reason="at least two compatible studies are required for pooled integration",
            )
        if modality == "single_cell":
            return IntegrationResult(
                modality=modality,
                output_path=None,
                studies=studies,
                batch_corrected=False,
                reason="single-cell objects remain per-study unless donor/condition metadata are compatible",
            )
        try:
            import pandas as pd
        except ImportError:
            return IntegrationResult(
                modality=modality,
                output_path=None,
                studies=studies,
                batch_corrected=False,
                reason="pandas is required for tabular pooling",
            )
        frames = []
        for item in artifacts:
            path = Path(item["output_path"])
            frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
            frame.insert(0, "omnibioseek_study", item["dataset_accession"])
            frames.append(frame)
        common = set(frames[0].columns)
        for frame in frames[1:]:
            common &= set(frame.columns)
        if len(common) <= 1:
            return IntegrationResult(
                modality=modality,
                output_path=None,
                studies=studies,
                batch_corrected=False,
                reason="no compatible shared columns/features",
            )
        ordered = ["omnibioseek_study", *sorted(common - {"omnibioseek_study"})]
        pooled = pd.concat([frame[ordered] for frame in frames], ignore_index=True)
        output = self.output_root / f"{modality}.pooled.parquet"
        try:
            pooled.to_parquet(output, index=False)
        except (ImportError, ValueError):
            output = output.with_suffix(".csv.gz")
            pooled.to_csv(output, index=False, compression="gzip")
        return IntegrationResult(
            modality=modality,
            output_path=str(output),
            studies=studies,
            batch_corrected=False,
            reason="pooled compatible values retained; batch correction requires an identifiable condition design",
        )

