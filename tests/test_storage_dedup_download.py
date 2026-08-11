from __future__ import annotations

from pathlib import Path

from omnibioseek.dedup import deduplicate
from omnibioseek.download import Downloader
from omnibioseek.models import (
    DatasetRecord,
    DownloadStatus,
    FileKind,
    FileRecord,
    Modality,
    SampleRecord,
)
from omnibioseek.storage import Catalog


def test_dedup_links_ncbi_arc_and_omicsdi():
    records = [
        DatasetRecord(
            source="ncbi",
            accession="GSE1",
            title="Study",
            modalities=[Modality.SINGLE_CELL],
            provenance={"cross_accessions": ["GSE1", "SRX1"]},
        ),
        DatasetRecord(
            source="arc",
            accession="SRX1",
            title="Study",
            modalities=[Modality.SINGLE_CELL],
            provenance={"cross_accessions": ["SRX1"]},
        ),
        DatasetRecord(
            source="omicsdi",
            accession="GSE1",
            title="Study",
            modalities=[Modality.TRANSCRIPTOMICS],
            provenance={"cross_accessions": ["GSE1"]},
        ),
    ]
    result = deduplicate(records)
    assert len(result) == 1
    assert result[0].source == "ncbi"
    assert result[0].provenance["preferred_matrix_source"] == "arc"
    assert len(result[0].provenance["alternate_sources"]) == 2


def test_catalog_roundtrip_and_exports(tmp_path: Path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    study = DatasetRecord(source="test", accession="STUDY1", title="Title")
    sample = SampleRecord(source="test", accession="S1", dataset_accession="STUDY1")
    catalog.upsert_dataset(study)
    catalog.upsert_sample(sample)
    assert catalog.datasets()[0].title == "Title"
    assert catalog.samples("STUDY1")[0].accession == "S1"
    outputs = catalog.export(tmp_path / "exports")
    assert (tmp_path / "exports" / "studies.csv") in outputs


def test_raw_files_are_never_downloaded(tmp_path: Path):
    record = FileRecord(
        source="test",
        dataset_accession="STUDY1",
        file_id="1",
        url="https://example.invalid/sample.fastq.gz",
        name="sample.fastq.gz",
        kind=FileKind.RAW,
    )
    result = Downloader().download(record, tmp_path)
    assert result.download_status is DownloadStatus.SKIPPED_RAW
    assert list(tmp_path.iterdir()) == []

