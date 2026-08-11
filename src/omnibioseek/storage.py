"""SQLite catalog with portable CSV and optional Parquet exports."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from omnibioseek.models import (
    DatasetRecord,
    EvidenceRecord,
    FileRecord,
    RunRecord,
    SampleRecord,
)

RecordT = TypeVar("RecordT", bound=BaseModel)

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS studies (
    record_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    accession TEXT NOT NULL,
    canonical_id TEXT,
    modality TEXT,
    eligibility TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(source, accession)
);
CREATE INDEX IF NOT EXISTS idx_studies_accession ON studies(accession);
CREATE INDEX IF NOT EXISTS idx_studies_eligibility ON studies(eligibility);

CREATE TABLE IF NOT EXISTS samples (
    record_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    accession TEXT NOT NULL,
    dataset_accession TEXT NOT NULL,
    case_control TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_dataset ON samples(dataset_accession);

CREATE TABLE IF NOT EXISTS files (
    record_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    dataset_accession TEXT NOT NULL,
    kind TEXT NOT NULL,
    download_status TEXT NOT NULL,
    checksum TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_dataset ON files(dataset_accession);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_accession TEXT NOT NULL,
    sample_accession TEXT,
    category TEXT NOT NULL,
    decision TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_dataset ON evidence(dataset_accession);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    command TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS warnings (
    warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    source TEXT,
    message TEXT NOT NULL
);
"""


def _json(record: BaseModel) -> str:
    return record.model_dump_json(exclude_none=True)


class Catalog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def upsert_dataset(self, record: DatasetRecord) -> None:
        modality = ",".join(item.value for item in record.modalities)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO studies
                (record_id, source, accession, canonical_id, modality, eligibility, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                canonical_id=excluded.canonical_id, modality=excluded.modality,
                eligibility=excluded.eligibility, payload=excluded.payload""",
                (
                    record.record_id,
                    record.source,
                    record.accession,
                    record.canonical_id,
                    modality,
                    record.eligibility.value,
                    _json(record),
                ),
            )

    def upsert_sample(self, record: SampleRecord) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO samples
                (record_id, source, accession, dataset_accession, case_control, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                case_control=excluded.case_control, payload=excluded.payload""",
                (
                    record.record_id,
                    record.source,
                    record.accession,
                    record.dataset_accession,
                    record.case_control,
                    _json(record),
                ),
            )

    def upsert_file(self, record: FileRecord) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO files
                (record_id, source, dataset_accession, kind, download_status, checksum, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET kind=excluded.kind,
                download_status=excluded.download_status, checksum=excluded.checksum,
                payload=excluded.payload""",
                (
                    record.record_id,
                    record.source,
                    record.dataset_accession,
                    record.kind.value,
                    record.download_status.value,
                    record.checksum,
                    _json(record),
                ),
            )

    def replace_evidence(self, accession: str, records: Iterable[EvidenceRecord]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM evidence WHERE dataset_accession = ?", (accession,))
            connection.executemany(
                """INSERT INTO evidence
                (dataset_accession, sample_accession, category, decision, payload)
                VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        item.dataset_accession,
                        item.sample_accession,
                        item.category,
                        item.decision.value,
                        _json(item),
                    )
                    for item in records
                ],
            )

    def upsert_run(self, run: RunRecord) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO runs (run_id, command, status, payload) VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, payload=excluded.payload""",
                (run.run_id, run.command, run.status, _json(run)),
            )

    def add_warning(self, run_id: str, source: str, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO warnings (run_id, source, message) VALUES (?, ?, ?)",
                (run_id, source, message),
            )

    def datasets(self) -> list[DatasetRecord]:
        return self._records("studies", DatasetRecord)

    def samples(self, dataset_accession: str | None = None) -> list[SampleRecord]:
        return self._records("samples", SampleRecord, "dataset_accession", dataset_accession)

    def files(self, dataset_accession: str | None = None) -> list[FileRecord]:
        return self._records("files", FileRecord, "dataset_accession", dataset_accession)

    def evidence(self, dataset_accession: str | None = None) -> list[EvidenceRecord]:
        return self._records("evidence", EvidenceRecord, "dataset_accession", dataset_accession)

    def _records(
        self,
        table: str,
        model: type[RecordT],
        field: str | None = None,
        value: str | None = None,
    ) -> list[RecordT]:
        allowed = {"studies", "samples", "files", "evidence"}
        if table not in allowed:
            raise ValueError(f"unsupported table: {table}")
        query = f"SELECT payload FROM {table}"  # noqa: S608 - table is allow-listed
        params: tuple[str, ...] = ()
        if field and value is not None:
            if field not in {"dataset_accession"}:
                raise ValueError(f"unsupported field: {field}")
            query += f" WHERE {field} = ?"
            params = (value,)
        with self.connect() as connection:
            return [model.model_validate_json(row["payload"]) for row in connection.execute(query, params)]

    def export(self, directory: str | Path) -> list[Path]:
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        outputs: list[Path] = []
        with self.connect() as connection:
            for table in ("studies", "samples", "files", "evidence", "runs", "warnings"):
                rows = list(connection.execute(f"SELECT * FROM {table}"))  # noqa: S608
                output = destination / f"{table}.csv"
                with output.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    if rows:
                        writer.writerow(rows[0].keys())
                        writer.writerows([tuple(row) for row in rows])
                outputs.append(output)
                self._optional_parquet(output)
        manifest = destination / "catalog_manifest.json"
        manifest.write_text(
            json.dumps({"database": str(self.path), "exports": [str(path) for path in outputs]}, indent=2),
            encoding="utf-8",
        )
        outputs.append(manifest)
        return outputs

    @staticmethod
    def _optional_parquet(csv_path: Path) -> None:
        try:
            import pandas as pd
            import pyarrow  # noqa: F401
        except ImportError:
            return
        pd.read_csv(csv_path).to_parquet(csv_path.with_suffix(".parquet"), index=False)

