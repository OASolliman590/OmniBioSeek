"""Stateful end-to-end orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from omnibioseek.adapters.base import AdapterUnavailable, RepositoryAdapter
from omnibioseek.adapters.registry import AdapterRegistry, default_registry
from omnibioseek.config import load_profile
from omnibioseek.curation import curate_dataset
from omnibioseek.dedup import deduplicate
from omnibioseek.integrate import IntegrationEngine
from omnibioseek.models import (
    DatasetRecord,
    DownloadStatus,
    EligibilityStatus,
    FileKind,
    QuerySpec,
    RunRecord,
    SampleRecord,
)
from omnibioseek.paths import DataLayout
from omnibioseek.prepare import PreparationEngine, PreparedArtifact
from omnibioseek.report import write_report
from omnibioseek.storage import Catalog


class Pipeline:
    def __init__(
        self,
        data_root: str | Path,
        *,
        registry: AdapterRegistry | None = None,
    ) -> None:
        self.layout = DataLayout.create(data_root)
        self.catalog = Catalog(self.layout.catalog / "omnibioseek.sqlite")
        self.registry = registry or default_registry()
        self.adapters: dict[str, RepositoryAdapter] = {}
        self.warnings: list[str] = []

    def _adapter(self, name: str) -> RepositoryAdapter:
        if name not in self.adapters:
            self.adapters[name] = self.registry.create(name)
        return self.adapters[name]

    def _warn(self, run_id: str, source: str, message: str) -> None:
        rendered = f"{source}: {message}"
        self.warnings.append(rendered)
        self.catalog.add_warning(run_id, source, message)

    def _start_run(self, command: str, query: QuerySpec) -> RunRecord:
        run = RunRecord(
            run_id=f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}",
            command=command,
            profile_name=query.name,
            started_at=datetime.now(UTC),
        )
        self.catalog.upsert_run(run)
        return run

    def _finish_run(self, run: RunRecord, *, status: str, counts: dict[str, int]) -> None:
        run.completed_at = datetime.now(UTC)
        run.status = status
        run.warnings = list(self.warnings)
        run.counts = counts
        self.catalog.upsert_run(run)

    @staticmethod
    def _merge_detail(summary: DatasetRecord, detail: DatasetRecord | None) -> DatasetRecord:
        if detail is None:
            return summary
        merged = summary.model_copy(deep=True)
        for field in ("title", "description", "organisms", "taxonomy_ids", "modalities", "pmids", "dois"):
            value = getattr(detail, field)
            if value:
                setattr(merged, field, value)
        merged.provenance = {**summary.provenance, **detail.provenance}
        return merged

    def search(self, query: QuerySpec) -> list[DatasetRecord]:
        run = self._start_run("search", query)
        discovered: list[DatasetRecord] = []
        samples: list[SampleRecord] = []
        for source in query.repositories:
            try:
                adapter = self._adapter(source)
                for record in adapter.search(query):
                    try:
                        record = self._merge_detail(record, adapter.fetch_study(record.accession))
                    except Exception as exc:
                        self._warn(run.run_id, source, f"study enrichment failed for {record.accession}: {exc}")
                    discovered.append(record)
                    try:
                        samples.extend(adapter.fetch_samples(record.accession))
                    except Exception as exc:
                        self._warn(run.run_id, source, f"sample enrichment failed for {record.accession}: {exc}")
            except AdapterUnavailable as exc:
                self._warn(run.run_id, source, str(exc))
            except Exception as exc:
                self._warn(run.run_id, source, f"search failed: {exc}")

        records = deduplicate(discovered)
        for record in records:
            self.catalog.upsert_dataset(record)
        for sample in samples:
            self.catalog.upsert_sample(sample)
        self.catalog.export(self.layout.catalog / "exports")
        self._finish_run(
            run,
            status="completed_with_warnings" if self.warnings else "completed",
            counts={"discovered": len(discovered), "deduplicated": len(records), "samples": len(samples)},
        )
        return records

    def curate(self, query: QuerySpec) -> list[DatasetRecord]:
        run = self._start_run("curate", query)
        curated: list[DatasetRecord] = []
        for dataset in self.catalog.datasets():
            related = self.catalog.samples(dataset.accession)
            alternate_accessions = {
                str(item.get("accession"))
                for item in dataset.provenance.get("alternate_sources", [])
                if item.get("accession")
            }
            for alternate in alternate_accessions:
                related.extend(self.catalog.samples(alternate))
            result = curate_dataset(dataset, related, query)
            self.catalog.upsert_dataset(result.dataset)
            for sample in result.samples:
                self.catalog.upsert_sample(sample)
            self.catalog.replace_evidence(dataset.accession, result.evidence)
            curated.append(result.dataset)
        self.catalog.export(self.layout.catalog / "exports")
        counts = {
            "approved": sum(item.eligibility is EligibilityStatus.APPROVED for item in curated),
            "needs_review": sum(item.eligibility is EligibilityStatus.NEEDS_REVIEW for item in curated),
            "rejected": sum(item.eligibility is EligibilityStatus.REJECTED for item in curated),
        }
        self._finish_run(run, status="completed", counts=counts)
        return curated

    def download(self, query: QuerySpec, *, approved_only: bool = True) -> list[str]:
        run = self._start_run("download", query)
        downloaded: list[str] = []
        for dataset in self.catalog.datasets():
            if approved_only and dataset.eligibility is not EligibilityStatus.APPROVED:
                continue
            source_records = [
                {"source": dataset.source, "accession": dataset.accession},
                *dataset.provenance.get("alternate_sources", []),
            ]
            for source_record in source_records:
                source = str(source_record.get("source", "")).lower()
                accession = str(source_record.get("accession", ""))
                if source not in query.repositories or not accession:
                    continue
                try:
                    adapter = self._adapter(source)
                    records = list(adapter.list_files(accession))
                    for file_record in records:
                        if file_record.kind is FileKind.RAW:
                            file_record.download_status = DownloadStatus.SKIPPED_RAW
                            self.catalog.upsert_file(file_record)
                            continue
                        if file_record.kind not in {FileKind.PROCESSED, FileKind.METADATA}:
                            self.catalog.upsert_file(file_record)
                            continue
                        destination = self.layout.downloads / source / accession
                        file_record = adapter.download_processed(file_record, str(destination))
                        self.catalog.upsert_file(file_record)
                        if file_record.local_path:
                            downloaded.append(file_record.local_path)
                except AdapterUnavailable as exc:
                    self._warn(run.run_id, source, f"{accession}: {exc}")
                except Exception as exc:
                    self._warn(run.run_id, source, f"file handling failed for {accession}: {exc}")
        self.catalog.export(self.layout.catalog / "exports")
        self._finish_run(
            run,
            status="completed_with_warnings" if self.warnings else "completed",
            counts={"downloaded": len(downloaded)},
        )
        return downloaded

    def prepare(self, query: QuerySpec) -> list[PreparedArtifact]:
        run = self._start_run("prepare", query)
        engine = PreparationEngine(self.layout.prepared)
        artifacts: list[PreparedArtifact] = []
        for dataset in self.catalog.datasets():
            if dataset.eligibility is not EligibilityStatus.APPROVED:
                continue
            try:
                artifacts.extend(
                    engine.prepare_dataset(
                        dataset,
                        self.catalog.samples(dataset.accession),
                        self.catalog.files(dataset.accession),
                    )
                )
            except Exception as exc:
                self._warn(run.run_id, dataset.source, f"preparation failed for {dataset.accession}: {exc}")
        manifest = self.layout.prepared / "artifacts.json"
        manifest.write_text(
            json.dumps([asdict(artifact) for artifact in artifacts], indent=2), encoding="utf-8"
        )
        self._finish_run(
            run,
            status="completed_with_warnings" if self.warnings else "completed",
            counts={"prepared": len(artifacts)},
        )
        return artifacts

    def integrate(self, query: QuerySpec) -> list[dict[str, object]]:
        run = self._start_run("integrate", query)
        manifest = self.layout.prepared / "artifacts.json"
        if not manifest.exists():
            self._warn(run.run_id, "integration", "no prepared artifact manifest exists")
            results = []
        else:
            results = [
                asdict(result) for result in IntegrationEngine(self.layout.integrated).integrate([manifest])
            ]
        output = self.layout.integrated / "integration_manifest.json"
        output.write_text(json.dumps(results, indent=2), encoding="utf-8")
        self._finish_run(
            run,
            status="completed_with_warnings" if self.warnings else "completed",
            counts={"integration_groups": len(results)},
        )
        return results

    def run(self, query: QuerySpec) -> None:
        self.search(query)
        self.curate(query)
        self.download(query, approved_only=True)
        self.prepare(query)
        self.integrate(query)
        write_report(
            self.layout.reports / f"{query.name}.md",
            profile_name=query.name,
            datasets=self.catalog.datasets(),
            samples=self.catalog.samples(),
            warnings=self.warnings,
        )


def pipeline_from_profile(profile: str | Path, data_root: str | Path) -> tuple[Pipeline, QuerySpec]:
    query = load_profile(profile)
    return Pipeline(data_root), query
