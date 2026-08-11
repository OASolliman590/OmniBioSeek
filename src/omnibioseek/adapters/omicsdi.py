"""Omics Discovery Index adapter for transcriptomics and proteomics."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

from omnibioseek.adapters.base import RepositoryAdapter
from omnibioseek.adapters.pride import PrideFileResolver
from omnibioseek.adapters.utils import as_list, infer_modality, parse_date
from omnibioseek.download import Downloader
from omnibioseek.http import HttpClient
from omnibioseek.models import DatasetRecord, FileRecord, Modality, QuerySpec, SampleRecord


class OmicsDIAdapter(RepositoryAdapter):
    name = "omicsdi"
    base_url = "https://www.omicsdi.org/ws/dataset"

    def __init__(self, client: HttpClient | None = None, page_size: int = 100) -> None:
        self.client = client or HttpClient()
        self.page_size = min(max(page_size, 1), 100)
        self.pride = PrideFileResolver(self.client)
        self._databases: dict[str, str] = {}

    def build_queries(self, query: QuerySpec) -> list[str]:
        tissues = [term for group in query.tissues for term in group.terms]
        diseases = [term for group in query.diseases for term in group.terms]
        organism = f'TAXONOMY:"{query.taxonomy_ids[0]}"' if query.taxonomy_ids else ""
        modalities = query.modalities or [Modality.TRANSCRIPTOMICS, Modality.PROTEOMICS]
        omics_names = {
            Modality.TRANSCRIPTOMICS: "Transcriptomics",
            Modality.SINGLE_CELL: "Transcriptomics",
            Modality.PROTEOMICS: "Proteomics",
            Modality.GENOMICS: "Genomics",
            Modality.METABOLOMICS: "Metabolomics",
        }
        queries: list[str] = []
        for modality in dict.fromkeys(modalities):
            omics_type = omics_names.get(modality)
            if not omics_type:
                continue
            tissue_clause = " OR ".join(f'"{item}"' for item in tissues)
            disease_clause = " OR ".join(f'"{item}"' for item in diseases)
            parts = []
            if tissue_clause:
                parts.append(f"({tissue_clause})")
            if disease_clause:
                parts.append(f"({disease_clause})")
            if organism:
                parts.append(organism)
            parts.append(f'omics_type:"{omics_type}"')
            queries.append(" AND ".join(parts))
            for priority in query.priority_terms:
                queries.append(" AND ".join([*parts, f'"{priority}"']))
        return list(dict.fromkeys(queries))

    def search(self, query: QuerySpec) -> Iterable[DatasetRecord]:
        seen: set[str] = set()
        for search_query in self.build_queries(query):
            start = 0
            while True:
                payload = self.client.get_json(
                    f"{self.base_url}/search",
                    params={"query": search_query, "start": start, "size": self.page_size},
                )
                datasets = payload.get("datasets", payload.get("dataset", [])) or []
                for item in datasets:
                    accession = str(item.get("id") or item.get("accession") or "").strip()
                    source = str(item.get("source") or item.get("repository") or "omicsdi").lower()
                    key = f"{source}:{accession}"
                    if not accession or key in seen:
                        continue
                    seen.add(key)
                    self._databases[accession] = source
                    yield self._record(item, search_query)
                start += len(datasets)
                count = int(payload.get("count", start) or 0)
                if not datasets or start >= count:
                    break

    def _record(self, item: dict[str, Any], search_query: str = "") -> DatasetRecord:
        accession = str(item.get("id") or item.get("accession") or "")
        repository = str(item.get("source") or item.get("repository") or item.get("database") or "omicsdi")
        title = str(item.get("title") or item.get("name") or "")
        description = str(item.get("description") or "")
        organisms = [
            str(value.get("name") if isinstance(value, dict) else value)
            for value in as_list(item.get("organisms"))
        ]
        taxonomy_ids = [
            str(value.get("acc"))
            for value in as_list(item.get("organisms"))
            if isinstance(value, dict) and value.get("acc")
        ]
        publications = as_list(item.get("publications"))
        pmids = [str(value.get("id")) for value in publications if isinstance(value, dict) and value.get("id")]
        cross_references = item.get("cross_references") or {}
        if isinstance(cross_references, dict):
            pmids.extend(str(value) for value in as_list(cross_references.get("pubmed")))
        dates = item.get("dates") or {}
        publication_date = item.get("publicationDate")
        if not publication_date and isinstance(dates, dict):
            publication_date = dates.get("publication") or dates.get("submission")
        return DatasetRecord(
            source="omicsdi",
            accession=accession,
            title=title,
            description=description,
            organisms=organisms,
            taxonomy_ids=taxonomy_ids,
            modalities=infer_modality(
                str(item.get("omics_type") or ""), title, description, " ".join(as_list(item.get("keywords")))
            ),
            keywords=[str(value) for value in as_list(item.get("keywords"))],
            publication_date=parse_date(publication_date),
            pmids=list(dict.fromkeys(pmids)),
            repository=repository,
            source_url=f"https://www.omicsdi.org/dataset/{repository}/{accession}",
            provenance={"search_query": search_query, "omicsdi": item, "cross_accessions": [accession]},
        )

    def fetch_study(self, accession: str) -> DatasetRecord | None:
        database, _, actual_accession = accession.partition(":")
        if not actual_accession:
            actual_accession = database
            database = self._databases.get(actual_accession, "")
        if not database:
            return None
        payload = self.client.get_json(
            f"{self.base_url}/{quote(database, safe='')}/{quote(actual_accession, safe='')}",
        )
        return self._record(payload) if payload else None

    def fetch_samples(self, accession: str) -> Iterable[SampleRecord]:
        return []

    def list_files(self, accession: str) -> Iterable[FileRecord]:
        bare = accession.split(":")[-1]
        if bare.upper().startswith("PXD"):
            return self.pride.list_files(bare)
        return []

    def download_processed(self, file_record: FileRecord, destination: str) -> FileRecord:
        return Downloader().download(file_record, Path(destination))
