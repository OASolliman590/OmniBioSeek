"""NCBI GEO/SRA discovery, metadata, and processed-file adapter."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from omnibioseek.adapters.base import RepositoryAdapter
from omnibioseek.adapters.utils import classify_file, file_format, infer_modality, parse_date
from omnibioseek.download import Downloader
from omnibioseek.http import HttpClient
from omnibioseek.models import DatasetRecord, FileKind, FileRecord, QuerySpec, SampleRecord


class NcbiAdapter(RepositoryAdapter):
    name = "ncbi"
    eutils = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    geo = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
    geo_ftp = "https://ftp.ncbi.nlm.nih.gov/geo"

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        email: str | None = None,
        api_key: str | None = None,
        page_size: int = 500,
    ) -> None:
        self.email = email or os.getenv("NCBI_EMAIL")
        self.api_key = api_key or os.getenv("NCBI_API_KEY")
        user_agent = f"OmniBioSeek/0.1 ({self.email or 'email-not-configured'})"
        self.client = client or HttpClient(user_agent=user_agent)
        self.page_size = page_size
        self._last_request = 0.0

    def _params(self, values: dict[str, str | int | None]) -> dict[str, str | int | None]:
        return {**values, "email": self.email, "api_key": self.api_key, "tool": "omnibioseek"}

    def _throttle(self) -> None:
        requests_per_second = 10 if self.api_key else 3
        interval = 1 / requests_per_second
        elapsed = time.monotonic() - self._last_request
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request = time.monotonic()

    @staticmethod
    def build_term(query: QuerySpec, database: str = "gds") -> str:
        tissues = [term for group in query.tissues for term in group.terms]
        diseases = [term for group in query.diseases for term in group.terms]
        tissue_clause = " OR ".join(f'"{term}"[All Fields]' for term in tissues)
        disease_clause = " OR ".join(f'"{term}"[All Fields]' for term in diseases)
        parts: list[str] = []
        if tissue_clause:
            parts.append(f"({tissue_clause})")
        if disease_clause:
            parts.append(f"({disease_clause})")
        if query.taxonomy_ids:
            parts.append(f'"{query.taxonomy_ids[0]}"[Taxonomy ID]')
        elif query.organisms:
            parts.append(f'"{query.organisms[0]}"[Organism]')
        if database == "gds":
            parts.append("GSE[ETYP]")
        if query.date_from or query.date_to:
            start = query.date_from.isoformat().replace("-", "/") if query.date_from else "1900/01/01"
            end = query.date_to.isoformat().replace("-", "/") if query.date_to else "3000/12/31"
            parts.append(f"{start}:{end}[PDAT]")
        return " AND ".join(parts) or "all[filter]"

    def search(self, query: QuerySpec) -> Iterable[DatasetRecord]:
        yield from self._search_database("gds", self.build_term(query, "gds"))
        yield from self._search_database("sra", self.build_term(query, "sra"))

    def _search_database(self, database: str, term: str) -> Iterable[DatasetRecord]:
        retstart = 0
        while True:
            self._throttle()
            result = self.client.get_json(
                f"{self.eutils}/esearch.fcgi",
                params=self._params(
                    {
                        "db": database,
                        "term": term,
                        "retmode": "json",
                        "retstart": retstart,
                        "retmax": self.page_size,
                    }
                ),
            ).get("esearchresult", {})
            ids = result.get("idlist", [])
            if not ids:
                break
            self._throttle()
            summary = self.client.get_json(
                f"{self.eutils}/esummary.fcgi",
                params=self._params({"db": database, "id": ",".join(ids), "retmode": "json"}),
            ).get("result", {})
            for uid in ids:
                item = summary.get(str(uid), {})
                record = self._summary_record(database, str(uid), item, term)
                if record:
                    yield record
            retstart += len(ids)
            if retstart >= int(result.get("count", 0) or 0):
                break

    def _summary_record(
        self, database: str, uid: str, item: dict[str, Any], term: str
    ) -> DatasetRecord | None:
        title = str(item.get("title") or item.get("study_title") or "")
        description = str(item.get("summary") or item.get("study_abstract") or "")
        if database == "gds":
            accession = str(item.get("accession") or "")
            if not accession.startswith("GSE"):
                return None
            organisms = [str(value) for value in item.get("taxon", [])]
            source_url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession}"
        else:
            expxml = str(item.get("expxml") or "")
            match = re.search(r'(?:acc|accession)="([SED]RX\d+)"', expxml, re.IGNORECASE)
            accession = match.group(1) if match else f"SRA-UID-{uid}"
            organism_match = re.search(r"<Organism[^>]*>([^<]+)", expxml)
            organisms = [organism_match.group(1)] if organism_match else []
            source_url = f"https://www.ncbi.nlm.nih.gov/sra/?term={accession}"
            description = description or expxml
        return DatasetRecord(
            source="ncbi",
            accession=accession,
            title=title,
            description=description,
            organisms=organisms,
            modalities=infer_modality(title, description, str(item.get("gdstype") or "")),
            publication_date=parse_date(item.get("pdat") or item.get("publication_date")),
            pmids=[str(value) for value in item.get("pubmedids", [])],
            repository="GEO" if database == "gds" else "SRA",
            source_url=source_url,
            provenance={
                "entrez_database": database,
                "entrez_uid": uid,
                "search_query": term,
                "summary": item,
                "cross_accessions": [accession],
            },
        )

    def fetch_study(self, accession: str) -> DatasetRecord | None:
        if not accession.upper().startswith("GSE"):
            return None
        text = self.client.get_text(
            self.geo,
            params={"acc": accession, "targ": "self", "view": "full", "form": "text"},
        )
        values = self._parse_soft_entity(text)
        title = " ".join(values.get("!Series_title", []))
        description = " ".join(values.get("!Series_summary", []))
        return DatasetRecord(
            source="ncbi",
            accession=accession,
            title=title,
            description=description,
            organisms=values.get("!Series_sample_organism", []),
            modalities=infer_modality(*values.get("!Series_type", []), title, description),
            pmids=values.get("!Series_pubmed_id", []),
            repository="GEO",
            source_url=f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={accession}",
            provenance={"soft": values, "cross_accessions": [accession]},
        )

    @staticmethod
    def _parse_soft_entity(text: str) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for line in text.splitlines():
            if line.startswith("!") and " = " in line:
                key, value = line.split(" = ", 1)
                result.setdefault(key.strip(), []).append(value.strip())
        return result

    def fetch_samples(self, accession: str) -> Iterable[SampleRecord]:
        if not accession.upper().startswith("GSE"):
            return []
        text = self.client.get_text(
            self.geo,
            params={"acc": accession, "targ": "family", "view": "full", "form": "text"},
        )
        blocks = re.split(r"(?=\^SAMPLE\s*=)", text)
        samples: list[SampleRecord] = []
        for block in blocks:
            header = re.search(r"\^SAMPLE\s*=\s*(GSM\d+)", block)
            if not header:
                continue
            values = self._parse_soft_entity(block)
            characteristics: dict[str, str] = {}
            for raw in values.get("!Sample_characteristics_ch1", []):
                key, separator, value = raw.partition(":")
                characteristics[key.strip() if separator else f"characteristic_{len(characteristics)}"] = (
                    value.strip() if separator else raw
                )
            tissue = next(
                (
                    value
                    for key, value in characteristics.items()
                    if any(term in key.casefold() for term in ("tissue", "source", "organ"))
                ),
                " ".join(values.get("!Sample_source_name_ch1", [])),
            )
            disease = next(
                (
                    value
                    for key, value in characteristics.items()
                    if any(term in key.casefold() for term in ("disease", "diagnosis", "status", "phenotype"))
                ),
                None,
            )
            treatment = " ".join(values.get("!Sample_treatment_protocol_ch1", [])) or characteristics.get(
                "treatment"
            )
            samples.append(
                SampleRecord(
                    source="ncbi",
                    accession=header.group(1),
                    dataset_accession=accession,
                    donor_id=characteristics.get("donor") or characteristics.get("subject"),
                    title=" ".join(values.get("!Sample_title", [])),
                    organism=" ".join(values.get("!Sample_organism_ch1", [])) or None,
                    tissue_raw=tissue or None,
                    disease_raw=disease,
                    case_control=characteristics.get("group") or characteristics.get("condition"),
                    sex=characteristics.get("sex") or characteristics.get("gender"),
                    age=characteristics.get("age"),
                    assay=" ".join(values.get("!Sample_type", [])) or None,
                    library_strategy=" ".join(values.get("!Sample_library_strategy", [])) or None,
                    characteristics=characteristics,
                    provenance={"treatment_text": treatment, "soft": values},
                )
            )
        return samples

    @staticmethod
    def _geo_range(accession: str) -> str:
        return re.sub(r"\d{3}$", "nnn", accession)

    def list_files(self, accession: str) -> Iterable[FileRecord]:
        if not accession.upper().startswith("GSE"):
            return []
        series_range = self._geo_range(accession)
        locations = [
            (f"{self.geo_ftp}/series/{series_range}/{accession}/suppl/", "supplementary"),
            (f"{self.geo_ftp}/series/{series_range}/{accession}/matrix/", "matrix"),
        ]
        records: list[FileRecord] = []
        index = 0
        for directory_url, category in locations:
            try:
                html = self.client.get_text(directory_url)
            except Exception:  # a missing optional directory is normal
                continue
            for href in re.findall(r'href="([^"]+)"', html, re.IGNORECASE):
                if href.startswith(("?", "/")) or href in {"../", "./"} or href.endswith("/"):
                    continue
                name = href.split("/")[-1]
                kind = classify_file(name, category)
                if category == "matrix" and kind is FileKind.UNKNOWN:
                    kind = FileKind.PROCESSED
                records.append(
                    FileRecord(
                        source="ncbi",
                        dataset_accession=accession,
                        file_id=str(index),
                        url=urljoin(directory_url, href),
                        name=name,
                        kind=kind,
                        format=file_format(name),
                        provenance={"geo_directory": category},
                    )
                )
                index += 1
        return records

    def download_processed(self, file_record: FileRecord, destination: str) -> FileRecord:
        return Downloader().download(file_record, Path(destination))

