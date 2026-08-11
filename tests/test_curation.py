from __future__ import annotations

from omnibioseek.curation import curate_dataset
from omnibioseek.models import DatasetRecord, EligibilityStatus, Modality, SampleRecord


def dataset(accession: str, text: str) -> DatasetRecord:
    return DatasetRecord(
        source="fixture",
        accession=accession,
        title=text,
        description=text,
        organisms=["Homo sapiens"],
        modalities=[Modality.TRANSCRIPTOMICS],
    )


def sample(accession: str, tissue: str, disease: str, treatment: str = "") -> SampleRecord:
    return SampleRecord(
        source="fixture",
        accession=accession,
        dataset_accession="STUDY1",
        organism="Homo sapiens",
        taxonomy_id="9606",
        tissue_raw=tissue,
        disease_raw=disease,
        provenance={"treatment_text": treatment},
    )


def test_exact_same_sample_pvat_prediabetes_is_approved(query):
    result = curate_dataset(
        dataset("STUDY1", "Human adipose study"),
        [sample("S1", "perivascular adipose tissue", "prediabetes", "metformin 500 mg")],
        query,
    )
    assert result.dataset.eligibility is EligibilityStatus.APPROVED
    assert result.samples[0].tissue_normalized == "PVAT"
    assert result.samples[0].disease_normalized == "prediabetes"
    assert result.samples[0].treatment.normalized_name == "metformin"


def test_prat_ckd_is_approved(query):
    result = curate_dataset(
        dataset("STUDY1", "Renal adipose study"),
        [sample("S1", "perirenal adipose tissue", "chronic kidney disease")],
        query,
    )
    assert result.dataset.eligibility is EligibilityStatus.APPROVED


def test_study_level_only_match_requires_review(query):
    result = curate_dataset(
        dataset("STUDY1", "PVAT transcriptomics in prediabetes"),
        [],
        query,
    )
    assert result.dataset.eligibility is EligibilityStatus.NEEDS_REVIEW


def test_known_negative_pvat_without_target_disease_is_rejected(query):
    result = curate_dataset(
        dataset("GSE166355", "Single cell RNA sequencing of human perivascular adipose tissue"),
        [],
        query,
    )
    assert result.dataset.eligibility is EligibilityStatus.REJECTED
    assert "disease" in (result.dataset.exclusion_reason or "")


def test_cancer_nephrectomy_does_not_qualify_as_kidney_disease(query):
    result = curate_dataset(
        dataset("STUDY1", "Perirenal adipose from renal cell carcinoma nephrectomy"),
        [sample("S1", "perirenal adipose tissue", "renal cell carcinoma")],
        query,
    )
    assert result.dataset.eligibility is EligibilityStatus.REJECTED

