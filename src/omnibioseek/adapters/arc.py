"""Arc Virtual Cell Atlas scBaseCount adapter."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, cast

from omnibioseek.adapters.base import AdapterUnavailable, RepositoryAdapter
from omnibioseek.models import (
    DatasetRecord,
    DownloadStatus,
    FileKind,
    FileRecord,
    Modality,
    QuerySpec,
    SampleRecord,
)

MetadataLoader = Callable[[], list[dict[str, Any]]]


class ArcAdapter(RepositoryAdapter):
    name = "arc"
    bucket = "arc-institute-virtual-cell-atlas"

    def __init__(
        self,
        *,
        release: str = "2026-01-12",
        feature_type: str = "Gene",
        project: str | None = None,
        metadata_loader: MetadataLoader | None = None,
    ) -> None:
        self.release = release
        self.feature_type = feature_type
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.metadata_loader = metadata_loader
        self._records: dict[str, dict[str, Any]] = {}

    @property
    def metadata_path(self) -> str:
        return (
            f"{self.bucket}/scbasecount/{self.release}/metadata/{self.feature_type}/"
            "Homo_sapiens/sample_metadata.parquet"
        )

    def _load_metadata(self) -> list[dict[str, Any]]:
        if self.metadata_loader:
            return self.metadata_loader()
        if not self.project:
            raise AdapterUnavailable(
                "Arc metadata cataloged as pending: GOOGLE_CLOUD_PROJECT is not configured for "
                "the requester-pays bucket"
            )
        try:
            import gcsfs
            import pandas as pd
        except ImportError as exc:
            raise AdapterUnavailable(
                "Arc support requires the 'analysis' extra (gcsfs, pandas, and pyarrow)"
            ) from exc
        filesystem = gcsfs.GCSFileSystem(
            project=self.project,
            token="google_default",
            requester_pays=True,
        )
        with filesystem.open(self.metadata_path, "rb") as handle:
            frame = pd.read_parquet(handle)
        return cast(list[dict[str, Any]], frame.to_dict(orient="records"))

    @staticmethod
    def _terms(query: QuerySpec) -> tuple[list[str], list[str]]:
        tissues = [term.casefold() for group in query.tissues for term in group.terms]
        diseases = [term.casefold() for group in query.diseases for term in group.terms]
        return tissues, diseases

    def search(self, query: QuerySpec) -> Iterable[DatasetRecord]:
        tissues, diseases = self._terms(query)
        for row in self._load_metadata():
            tissue = str(row.get("tissue") or "")
            disease = str(row.get("disease") or "")
            if tissues and not any(term in tissue.casefold() for term in tissues):
                continue
            if diseases and not any(term in disease.casefold() for term in diseases):
                continue
            accession = str(row.get("srx_accession") or row.get("entrez_id") or "")
            if not accession:
                continue
            self._records[accession] = row
            yield DatasetRecord(
                source="arc",
                accession=accession,
                title=f"scBaseCount {accession}: {tissue}",
                description=f"Disease: {disease}; tissue: {tissue}",
                organisms=[str(row.get("organism") or "Homo sapiens")],
                taxonomy_ids=["9606"],
                modalities=[Modality.SINGLE_CELL, Modality.TRANSCRIPTOMICS],
                repository="Arc scBaseCount",
                source_url="https://github.com/ArcInstitute/arc-virtual-cell-atlas/tree/main/scBaseCount",
                provenance={
                    "arc_release": self.release,
                    "arc_feature_type": self.feature_type,
                    "arc_metadata": row,
                    "cross_accessions": [accession],
                    "preferred_matrix_source": "arc",
                },
            )

    def fetch_study(self, accession: str) -> DatasetRecord | None:
        row = self._records.get(accession)
        if not row:
            return None
        tissue = str(row.get("tissue") or "")
        disease = str(row.get("disease") or "")
        return DatasetRecord(
            source="arc",
            accession=accession,
            title=f"scBaseCount {accession}: {tissue}",
            description=f"Disease: {disease}; tissue: {tissue}",
            organisms=[str(row.get("organism") or "Homo sapiens")],
            taxonomy_ids=["9606"],
            modalities=[Modality.SINGLE_CELL, Modality.TRANSCRIPTOMICS],
            repository="Arc scBaseCount",
            source_url="https://github.com/ArcInstitute/arc-virtual-cell-atlas/tree/main/scBaseCount",
            provenance={
                "arc_release": self.release,
                "arc_feature_type": self.feature_type,
                "arc_metadata": row,
                "cross_accessions": [accession],
                "preferred_matrix_source": "arc",
            },
        )

    def fetch_samples(self, accession: str) -> Iterable[SampleRecord]:
        row = self._records.get(accession)
        if not row:
            return []
        return [
            SampleRecord(
                source="arc",
                accession=accession,
                dataset_accession=accession,
                organism=str(row.get("organism") or "Homo sapiens"),
                tissue_raw=str(row.get("tissue") or "") or None,
                tissue_ontology_id=str(row.get("tissue_ontology_term_id") or "") or None,
                disease_raw=str(row.get("disease") or "") or None,
                disease_ontology_id=str(row.get("disease_ontology_term_id") or "") or None,
                assay=str(row.get("cell_prep") or "single_cell"),
                library_strategy=str(row.get("tech_10x") or row.get("lib_prep") or "") or None,
                file_paths=[str(row.get("file_path") or "")],
                provenance={
                    "single_disease_confidence": row.get("single_disease_confidence"),
                    "single_disease_confidence_reasoning": row.get(
                        "single_disease_confidence_reasoning"
                    ),
                    "arc_metadata": row,
                },
            )
        ]

    def list_files(self, accession: str) -> Iterable[FileRecord]:
        row = self._records.get(accession)
        path = str(row.get("file_path") or "") if row else ""
        if not path:
            return []
        return [
            FileRecord(
                source="arc",
                dataset_accession=accession,
                file_id=accession,
                url=path,
                name=Path(path).name,
                kind=FileKind.PROCESSED,
                format="h5ad",
                provenance={"arc_release": self.release, "requester_pays": True},
            )
        ]

    def download_processed(self, file_record: FileRecord, destination: str) -> FileRecord:
        if not self.project:
            raise AdapterUnavailable("GOOGLE_CLOUD_PROJECT is required to download Arc matrices")
        try:
            import gcsfs
        except ImportError as exc:
            raise AdapterUnavailable("Arc download requires gcsfs") from exc
        target = Path(destination) / file_record.name
        target.parent.mkdir(parents=True, exist_ok=True)
        filesystem = gcsfs.GCSFileSystem(
            project=self.project, token="google_default", requester_pays=True
        )
        filesystem.get(file_record.url.removeprefix("gs://"), str(target))
        file_record.local_path = str(target)
        file_record.download_status = DownloadStatus.DOWNLOADED
        return file_record
