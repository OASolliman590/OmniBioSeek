"""Evidence-based exact curation without silent scope broadening."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnibioseek.models import (
    DatasetRecord,
    EligibilityStatus,
    EvidenceDecision,
    EvidenceRecord,
    QuerySpec,
    SampleRecord,
)
from omnibioseek.terminology import classify_treatment, contains_exact, match_groups


@dataclass(slots=True)
class CurationResult:
    dataset: DatasetRecord
    samples: list[SampleRecord]
    evidence: list[EvidenceRecord] = field(default_factory=list)


def _sample_text(sample: SampleRecord) -> str:
    values = [
        sample.title,
        sample.tissue_raw or "",
        sample.disease_raw or "",
        sample.case_control or "",
        " ".join(f"{key}: {value}" for key, value in sample.characteristics.items()),
        str(sample.provenance.get("treatment_text") or ""),
    ]
    return " | ".join(values)


def _dataset_text(dataset: DatasetRecord) -> str:
    return " | ".join([dataset.title, dataset.description, " ".join(dataset.keywords)])


def curate_dataset(
    dataset: DatasetRecord,
    samples: list[SampleRecord],
    query: QuerySpec,
) -> CurationResult:
    output = dataset.model_copy(deep=True)
    curated_samples = [sample.model_copy(deep=True) for sample in samples]
    evidence: list[EvidenceRecord] = []
    organism_terms = [*query.organisms, *query.taxonomy_ids]

    sample_exact = False
    case_samples = 0
    for sample in curated_samples:
        text = _sample_text(sample)
        tissue_matches = match_groups(text, query.tissues)
        disease_matches = match_groups(text, query.diseases)
        organism_ok = not organism_terms or any(
            contains_exact(text, term)
            or contains_exact(sample.organism or "", term)
            or sample.taxonomy_id == term
            for term in organism_terms
        )
        excluded = [term for term in query.exclude_terms if contains_exact(text, term)]
        for category, matches in (("tissue", tissue_matches), ("disease", disease_matches)):
            for match in matches:
                evidence.append(
                    EvidenceRecord(
                        dataset_accession=dataset.accession,
                        sample_accession=sample.accession,
                        category=category,
                        matched_term=match.term,
                        matched_text=text,
                        source_field="sample_metadata",
                        normalized_term=match.group,
                        ontology_id=match.ontology_id,
                        confidence=1.0,
                        decision=EvidenceDecision.INCLUDE,
                    )
                )
        for term in excluded:
            evidence.append(
                EvidenceRecord(
                    dataset_accession=dataset.accession,
                    sample_accession=sample.accession,
                    category="exclusion",
                    matched_term=term,
                    matched_text=text,
                    source_field="sample_metadata",
                    confidence=1.0,
                    decision=EvidenceDecision.EXCLUDE,
                )
            )
        treatment_text = str(sample.provenance.get("treatment_text") or sample.treatment.original_text or "")
        sample.treatment = classify_treatment(treatment_text)
        if tissue_matches and disease_matches and organism_ok and not excluded:
            sample_exact = True
            case_samples += 1
            sample.case_control = sample.case_control or "case"
            sample.tissue_normalized = tissue_matches[0].group
            sample.tissue_ontology_id = sample.tissue_ontology_id or tissue_matches[0].ontology_id
            sample.disease_normalized = disease_matches[0].group
            sample.disease_ontology_id = sample.disease_ontology_id or disease_matches[0].ontology_id

    dataset_text = _dataset_text(output)
    dataset_tissues = match_groups(dataset_text, query.tissues)
    dataset_diseases = match_groups(dataset_text, query.diseases)
    dataset_excluded = [term for term in query.exclude_terms if contains_exact(dataset_text, term)]

    if sample_exact:
        output.eligibility = EligibilityStatus.APPROVED
        output.exclusion_reason = None
    elif dataset_excluded:
        output.eligibility = EligibilityStatus.REJECTED
        output.exclusion_reason = f"excluded term: {dataset_excluded[0]}"
    elif dataset_tissues and dataset_diseases:
        output.eligibility = EligibilityStatus.NEEDS_REVIEW
        output.exclusion_reason = "study-level match lacks same-sample tissue/disease confirmation"
        for category, matches in (("tissue", dataset_tissues), ("disease", dataset_diseases)):
            for match in matches:
                evidence.append(
                    EvidenceRecord(
                        dataset_accession=dataset.accession,
                        category=category,
                        matched_term=match.term,
                        matched_text=dataset_text,
                        source_field="study_metadata",
                        normalized_term=match.group,
                        ontology_id=match.ontology_id,
                        confidence=0.6,
                        decision=EvidenceDecision.REVIEW,
                    )
                )
    else:
        output.eligibility = EligibilityStatus.REJECTED
        missing = []
        if not dataset_tissues:
            missing.append("exact tissue evidence")
        if not dataset_diseases:
            missing.append("explicit disease evidence")
        output.exclusion_reason = "missing " + " and ".join(missing)

    output.provenance["curation"] = {
        "case_samples": case_samples,
        "retained_controls": query.retain_controls,
        "match_policy": query.match_policy.value,
    }
    return CurationResult(dataset=output, samples=curated_samples, evidence=evidence)

