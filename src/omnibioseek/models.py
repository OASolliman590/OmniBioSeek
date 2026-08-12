"""Typed public records shared by adapters, curation, and storage."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Modality(StrEnum):
    TRANSCRIPTOMICS = "transcriptomics"
    PROTEOMICS = "proteomics"
    SINGLE_CELL = "single_cell"
    GENOMICS = "genomics"
    METABOLOMICS = "metabolomics"
    OTHER = "other"


class MatchPolicy(StrEnum):
    EXACT = "exact"
    TIERED = "tiered"
    BROAD = "broad"


class EligibilityStatus(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class FileKind(StrEnum):
    PROCESSED = "processed"
    METADATA = "metadata"
    RAW = "raw"
    UNKNOWN = "unknown"


class DownloadStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    SKIPPED_RAW = "skipped_raw"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class EvidenceDecision(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"


class TreatmentCategory(StrEnum):
    UNTREATED = "untreated"
    METFORMIN = "metformin"
    OTHER_DRUG = "other_drug"
    LIFESTYLE = "lifestyle"
    COMBINATION = "combination"
    UNKNOWN = "unknown"


class OmniModel(BaseModel):
    model_config = ConfigDict(extra="allow", validate_assignment=True, use_enum_values=False)


class TermGroup(OmniModel):
    name: str
    terms: list[str]
    ontology_ids: list[str] = Field(default_factory=list)

    @field_validator("terms")
    @classmethod
    def non_empty_terms(cls, value: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(term.strip() for term in value if term.strip()))
        if not cleaned:
            raise ValueError("a term group must contain at least one term")
        return cleaned


class QuerySpec(OmniModel):
    name: str = "query"
    organisms: list[str] = Field(default_factory=list)
    taxonomy_ids: list[str] = Field(default_factory=list)
    tissues: list[TermGroup] = Field(default_factory=list)
    diseases: list[TermGroup] = Field(default_factory=list)
    treatments: list[TermGroup] = Field(default_factory=list)
    mechanisms: list[TermGroup] = Field(default_factory=list)
    priority_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    modalities: list[Modality] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=lambda: ["omicsdi", "ncbi", "arc"])
    date_from: date | None = None
    date_to: date | None = None
    match_policy: MatchPolicy = MatchPolicy.EXACT
    require_same_sample: bool = True
    retain_controls: bool = True
    processed_only: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("repositories", mode="before")
    @classmethod
    def normalize_repositories(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip().lower() for item in value if item.strip()))


class TreatmentExposure(OmniModel):
    normalized_name: str | None = None
    original_text: str | None = None
    category: TreatmentCategory = TreatmentCategory.UNKNOWN
    ontology_id: str | None = None
    dose: str | None = None
    duration: str | None = None
    route: str | None = None
    combination: list[str] = Field(default_factory=list)


class DatasetRecord(OmniModel):
    source: str
    accession: str
    canonical_id: str | None = None
    title: str = ""
    description: str = ""
    organisms: list[str] = Field(default_factory=list)
    taxonomy_ids: list[str] = Field(default_factory=list)
    modalities: list[Modality] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    pmids: list[str] = Field(default_factory=list)
    dois: list[str] = Field(default_factory=list)
    repository: str | None = None
    source_url: str | None = None
    eligibility: EligibilityStatus = EligibilityStatus.CANDIDATE
    exclusion_reason: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def record_id(self) -> str:
        return f"{self.source.lower()}:{self.accession}"


class SampleRecord(OmniModel):
    source: str
    accession: str
    dataset_accession: str
    donor_id: str | None = None
    title: str = ""
    organism: str | None = None
    taxonomy_id: str | None = None
    tissue_raw: str | None = None
    tissue_normalized: str | None = None
    tissue_ontology_id: str | None = None
    disease_raw: str | None = None
    disease_normalized: str | None = None
    disease_ontology_id: str | None = None
    treatment: TreatmentExposure = Field(default_factory=TreatmentExposure)
    case_control: str | None = None
    sex: str | None = None
    age: str | None = None
    assay: str | None = None
    library_strategy: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    characteristics: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @property
    def record_id(self) -> str:
        return f"{self.source.lower()}:{self.accession}"


class FileRecord(OmniModel):
    source: str
    dataset_accession: str
    file_id: str
    url: str
    name: str
    kind: FileKind = FileKind.UNKNOWN
    format: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    checksum_algorithm: str = "sha256"
    local_path: str | None = None
    download_status: DownloadStatus = DownloadStatus.PENDING
    provenance: dict[str, Any] = Field(default_factory=dict)

    @property
    def record_id(self) -> str:
        return f"{self.source.lower()}:{self.dataset_accession}:{self.file_id}"


class EvidenceRecord(OmniModel):
    dataset_accession: str
    sample_accession: str | None = None
    category: str
    matched_term: str
    matched_text: str
    source_field: str
    normalized_term: str | None = None
    ontology_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    decision: EvidenceDecision = EvidenceDecision.REVIEW
    curator_note: str | None = None


class RunRecord(OmniModel):
    run_id: str
    command: str
    profile_name: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"
    warnings: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
