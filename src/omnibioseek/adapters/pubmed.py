"""PubMed/PMC literature mining for public omics accessions.

This adapter is intentionally discovery-only. It searches PubMed for tissue/omics
papers, follows PubMed Central links when available, and extracts public dataset
accessions from article text. The resulting records are merged with repository
records by the normal deduplication layer.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable

from omnibioseek.adapters.base import RepositoryAdapter
from omnibioseek.http import HttpClient
from omnibioseek.models import DatasetRecord, FileRecord, Modality, QuerySpec, SampleRecord

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Public omics accession families commonly encountered in publications.
ACCESSION_RE = re.compile(
    r"\b(?:"
    r"GSE\d+|GSM\d+|SRP\d+|SRX\d+|SRS\d+|SRR\d+|"
    r"ERP\d+|ERX\d+|ERS\d+|ERR\d+|PRJNA\d+|PRJEB\d+|"
    r"PXD\d+|E-MTAB-\d+|E-GEOD-\d+|S-BSST\d+|MTBLS\d+"
    r")\b",
    re.I,
)


def extract_accessions(text: str) -> list[str]:
    """Return unique normalized public omics accessions in first-seen order."""
    return list(dict.fromkeys(match.upper() for match in ACCESSION_RE.findall(text or "")))


def _node_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join(part.strip() for part in node.itertext() if part and part.strip())


def _article_fields(article: ET.Element) -> tuple[str, str, list[str], str | None]:
    pmid = _node_text(article.find(".//PMID"))
    title = _node_text(article.find(".//ArticleTitle"))
    abstract = " ".join(_node_text(node) for node in article.findall(".//Abstract/AbstractText"))
    dois: list[str] = []
    pmcid: str | None = None
    for node in article.findall(".//ArticleId"):
        value = _node_text(node)
        kind = (node.attrib.get("IdType") or "").casefold()
        if kind == "doi" and value:
            dois.append(value)
        elif kind == "pmc" and value:
            pmcid = value
    return pmid, title, abstract, list(dict.fromkeys(dois)), pmcid


class PubMedAdapter(RepositoryAdapter):
    """Discovery-only PubMed/PMC adapter that mines linked dataset accessions."""

    name = "pubmed"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient(user_agent="OmniBioSeek/0.2 (PubMed accession miner)")
        self.email = os.getenv("NCBI_EMAIL")
        self.api_key = os.getenv("NCBI_API_KEY")
        self._records: dict[str, DatasetRecord] = {}

    def _common_params(self) -> dict[str, str]:
        params: dict[str, str] = {"tool": "OmniBioSeek"}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    @staticmethod
    def _query_terms(query: QuerySpec) -> str:
        tissue_terms = [term for group in query.tissues for term in group.terms]
        if not tissue_terms:
            tissue_terms = ["adipose tissue"]
        # Keep PubMed discovery broad; phenotype and RAAS are scored by curation,
        # not required here, so sparse but relevant papers are not lost.
        tissue = " OR ".join(f'"{term}"[Title/Abstract]' for term in tissue_terms)
        omics = (
            'transcriptom*[Title/Abstract] OR RNA-seq[Title/Abstract] OR '
            '"RNA sequencing"[Title/Abstract] OR proteom*[Title/Abstract] OR '
            '"mass spectrometry"[Title/Abstract] OR "single cell"[Title/Abstract]'
        )
        return f"({tissue}) AND ({omics})"

    def _search_pmids(self, query: QuerySpec) -> list[str]:
        max_results = int(query.metadata.get("literature_max_results", 100))
        params: dict[str, str | int | None] = {
            "db": "pubmed",
            "term": self._query_terms(query),
            "retmode": "json",
            "retmax": max_results,
            "sort": "relevance",
            **self._common_params(),
        }
        payload = self.client.get_json(f"{EUTILS}/esearch.fcgi", params=params)
        return [str(value) for value in payload.get("esearchresult", {}).get("idlist", [])]

    def _fetch_pubmed_xml(self, pmids: list[str]) -> ET.Element:
        if not pmids:
            return ET.Element("PubmedArticleSet")
        params: dict[str, str | int | None] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            **self._common_params(),
        }
        return ET.fromstring(self.client.get_text(f"{EUTILS}/efetch.fcgi", params=params))

    def _fetch_pmc_text(self, pmcid: str) -> str:
        numeric = pmcid.removeprefix("PMC").removeprefix("pmc")
        params: dict[str, str | int | None] = {
            "db": "pmc",
            "id": numeric,
            "retmode": "xml",
            **self._common_params(),
        }
        try:
            root = ET.fromstring(self.client.get_text(f"{EUTILS}/efetch.fcgi", params=params))
        except Exception:
            return ""
        return _node_text(root)

    @staticmethod
    def _modalities(text: str) -> list[Modality]:
        lowered = text.casefold()
        modalities: list[Modality] = []
        if any(term in lowered for term in ("transcriptom", "rna-seq", "rna sequencing")):
            modalities.append(Modality.TRANSCRIPTOMICS)
        if any(term in lowered for term in ("proteom", "mass spectrom")):
            modalities.append(Modality.PROTEOMICS)
        if any(term in lowered for term in ("single-cell", "single cell", "scrna")):
            modalities.append(Modality.SINGLE_CELL)
        return modalities

    def search(self, query: QuerySpec) -> Iterable[DatasetRecord]:
        pmids = self._search_pmids(query)
        root = self._fetch_pubmed_xml(pmids)
        emit_without_accession = bool(query.metadata.get("retain_literature_without_accession", True))
        records: list[DatasetRecord] = []

        for article in root.findall(".//PubmedArticle"):
            pmid, title, abstract, dois, pmcid = _article_fields(article)
            pmc_text = self._fetch_pmc_text(pmcid) if pmcid else ""
            searchable_text = " ".join(part for part in (title, abstract, pmc_text) if part)
            accessions = extract_accessions(searchable_text)
            modalities = self._modalities(searchable_text)

            if accessions:
                for accession in accessions:
                    record = DatasetRecord(
                        source=self.name,
                        accession=accession,
                        canonical_id=accession,
                        title=title,
                        description=abstract,
                        modalities=modalities,
                        pmids=[pmid] if pmid else [],
                        dois=dois,
                        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                        provenance={
                            "literature_mined": True,
                            "mined_accessions": accessions,
                            "pmcid": pmcid,
                            "literature_text": searchable_text[:50000],
                            "cross_accessions": accessions,
                        },
                    )
                    self._records[accession] = record
                    records.append(record)
            elif emit_without_accession and pmid:
                record = DatasetRecord(
                    source=self.name,
                    accession=f"PMID{pmid}",
                    title=title,
                    description=abstract,
                    modalities=modalities,
                    pmids=[pmid],
                    dois=dois,
                    source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    provenance={
                        "literature_mined": True,
                        "literature_only": True,
                        "pmcid": pmcid,
                        "literature_text": searchable_text[:50000],
                    },
                )
                self._records[record.accession] = record
                records.append(record)
        return records

    def fetch_study(self, accession: str) -> DatasetRecord | None:
        return self._records.get(accession)

    def fetch_samples(self, accession: str) -> Iterable[SampleRecord]:
        return []

    def list_files(self, accession: str) -> Iterable[FileRecord]:
        return []

    def download_processed(self, file_record: FileRecord, destination: str) -> FileRecord:
        return file_record
