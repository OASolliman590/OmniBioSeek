"""Conservative modality-specific preparation of downloaded processed data."""

from __future__ import annotations

import gzip
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from omnibioseek.models import DatasetRecord, FileRecord, Modality, SampleRecord


class PreparationError(RuntimeError):
    """A processed file cannot be converted safely."""


@dataclass(slots=True)
class PreparedArtifact:
    dataset_accession: str
    modality: str
    input_path: str
    output_path: str
    rows: int | None = None
    columns: int | None = None
    qc: dict[str, Any] = field(default_factory=dict)


def _read_table(path: Path) -> Any:
    try:
        import pandas as pd
    except ImportError as exc:
        raise PreparationError("tabular preparation requires pandas") from exc
    compression = "gzip" if path.suffix.casefold() == ".gz" else "infer"
    name_without_gz = path.with_suffix("").name if compression == "gzip" else path.name
    separator = "\t" if any(token in name_without_gz.casefold() for token in (".tsv", ".txt")) else ","
    return pd.read_csv(path, sep=separator, compression=compression, comment="#", low_memory=False)


class PreparationEngine:
    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)

    def prepare_dataset(
        self,
        dataset: DatasetRecord,
        samples: list[SampleRecord],
        files: list[FileRecord],
    ) -> list[PreparedArtifact]:
        artifacts: list[PreparedArtifact] = []
        modalities = dataset.modalities or [Modality.OTHER]
        for record in files:
            if not record.local_path:
                continue
            path = Path(record.local_path)
            if path.name.casefold().endswith((".h5ad", ".h5ad.gz")):
                artifacts.append(self._prepare_anndata(dataset, samples, path))
            elif path.name.casefold().endswith((".csv", ".csv.gz", ".tsv", ".tsv.gz", ".txt", ".txt.gz")):
                artifacts.append(self._prepare_table(dataset, modalities[0], samples, path))
        return artifacts

    def _prepare_table(
        self,
        dataset: DatasetRecord,
        modality: Modality,
        samples: list[SampleRecord],
        path: Path,
    ) -> PreparedArtifact:
        frame = _read_table(path)
        frame.columns = [str(column).strip() for column in frame.columns]
        output_dir = self.output_root / dataset.accession
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{path.stem}.prepared.parquet"
        try:
            frame.to_parquet(output, index=False)
        except (ImportError, ValueError):
            output = output.with_suffix(".csv.gz")
            frame.to_csv(output, index=False, compression="gzip")
        sample_metadata = output_dir / "samples.json"
        sample_metadata.write_text(
            json.dumps([sample.model_dump(mode="json", exclude_none=True) for sample in samples], indent=2),
            encoding="utf-8",
        )
        qc = {
            "missing_fraction": float(frame.isna().sum().sum() / max(frame.size, 1)),
            "duplicate_rows": int(frame.duplicated().sum()),
            "normalization": "source-processed values preserved",
            "identifier_harmonization": "original identifiers retained; mappings require explicit source columns",
        }
        return PreparedArtifact(
            dataset_accession=dataset.accession,
            modality=modality.value,
            input_path=str(path),
            output_path=str(output),
            rows=int(frame.shape[0]),
            columns=int(frame.shape[1]),
            qc=qc,
        )

    def _prepare_anndata(
        self, dataset: DatasetRecord, samples: list[SampleRecord], path: Path
    ) -> PreparedArtifact:
        try:
            import anndata as ad
            import numpy as np
        except ImportError as exc:
            raise PreparationError("single-cell preparation requires the 'analysis' extra") from exc
        if path.name.casefold().endswith(".gz"):
            expanded = self.output_root / dataset.accession / path.stem
            expanded.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(path, "rb") as source, expanded.open("wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
            path = expanded
        adata = ad.read_h5ad(path)
        if "counts" not in adata.layers:
            adata.layers["counts"] = adata.X.copy()
        counts = adata.layers["counts"]
        if "total_counts" not in adata.obs:
            adata.obs["total_counts"] = np.asarray(counts.sum(axis=1)).ravel()
        if "n_genes_by_counts" not in adata.obs:
            adata.obs["n_genes_by_counts"] = np.asarray((counts > 0).sum(axis=1)).ravel()
        output_dir = self.output_root / dataset.accession
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "single_cell.prepared.h5ad"
        adata.uns["omnibioseek"] = {
            "source_accession": dataset.accession,
            "raw_counts_layer": "counts",
            "qc_policy": "source-filtered cells retained; QC metrics added without hidden filtering",
        }
        adata.write_h5ad(output, compression="gzip")
        pseudobulk = self._pseudobulk(adata, output_dir)
        return PreparedArtifact(
            dataset_accession=dataset.accession,
            modality=Modality.SINGLE_CELL.value,
            input_path=str(path),
            output_path=str(output),
            rows=int(adata.n_obs),
            columns=int(adata.n_vars),
            qc={"pseudobulk": pseudobulk, "cells_are_not_replicates": True},
        )

    @staticmethod
    def _pseudobulk(adata: Any, output_dir: Path) -> str | None:
        replicate = next(
            (field for field in ("donor_id", "sample_id", "sample", "batch") if field in adata.obs),
            None,
        )
        if not replicate:
            return None
        try:
            import pandas as pd
            from scipy import sparse
        except ImportError:
            return None
        matrix = adata.layers["counts"]
        rows = []
        identifiers = []
        for identifier, indices in adata.obs.groupby(replicate, observed=True).indices.items():
            subset = matrix[indices]
            summed = subset.sum(axis=0)
            rows.append(summed.A1 if sparse.issparse(summed) else summed.asarray().ravel())
            identifiers.append(str(identifier))
        frame = pd.DataFrame(rows, index=identifiers, columns=adata.var_names)
        frame.index.name = replicate
        output = output_dir / "pseudobulk.csv.gz"
        frame.to_csv(output, compression="gzip")
        return str(output)


def write_artifact_manifest(artifacts: list[PreparedArtifact], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([asdict(artifact) for artifact in artifacts], indent=2), encoding="utf-8"
    )
    return output
