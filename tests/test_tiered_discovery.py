from __future__ import annotations

from pathlib import Path

from omnibioseek.config import load_profile
from omnibioseek.curation import curate_dataset
from omnibioseek.models import DatasetRecord, EligibilityStatus, Modality, SampleRecord


PROFILE = Path(__file__).parents[1] / "profiles" / "pvat_prat_raas_metabolic.yaml"


def _dataset(text: str) -> DatasetRecord:
    return DatasetRecord(
        source="fixture",
        accession="STUDY1",
        title=text,
        description=text,
        modalities=[Modality.TRANSCRIPTOMICS],
    )


def test_profile_loads_mechanism_terms():
    query = load_profile(PROFILE)
    assert query.match_policy.value == "tiered"
    assert any(group.name == "RAAS" for group in query.mechanisms)
    assert any(group.name == "metabolic_syndrome" for group in query.diseases)


def test_tissue_only_study_is_retained_for_review():
    query = load_profile(PROFILE)
    result = curate_dataset(
        _dataset("RNA-seq of perivascular adipose tissue"),
        [],
        query,
    )
    assert result.dataset.eligibility is EligibilityStatus.NEEDS_REVIEW
    assert "tier C/context" in (result.dataset.exclusion_reason or "")


def test_raas_is_annotation_not_mandatory_filter():
    query = load_profile(PROFILE)
    sample = SampleRecord(
        source="fixture",
        accession="S1",
        dataset_accession="STUDY1",
        organism="Homo sapiens",
        taxonomy_id="9606",
        tissue_raw="periaortic adipose tissue",
        disease_raw="metabolic syndrome",
    )
    result = curate_dataset(_dataset("Human adipose transcriptomics"), [sample], query)
    assert result.dataset.eligibility is EligibilityStatus.APPROVED
    assert result.dataset.provenance["curation"]["mechanism_hits"] == []


def test_raas_terms_are_recorded_as_mechanism_evidence():
    query = load_profile(PROFILE)
    result = curate_dataset(
        _dataset("Angiotensin II response in PVAT transcriptomics"),
        [],
        query,
    )
    assert result.dataset.eligibility is EligibilityStatus.NEEDS_REVIEW
    assert "RAAS" in result.dataset.provenance["curation"]["mechanism_hits"]
    assert any(item.category == "mechanism" for item in result.evidence)
