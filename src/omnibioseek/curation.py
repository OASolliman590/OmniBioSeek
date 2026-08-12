"""Evidence-based curation with exact, tiered, and broad discovery modes."""

from __future__ import annotations

from dataclasses import dataclass, field

from omnibioseek.models import (
    DatasetRecord,
    EligibilityStatus,
    EvidenceDecision,
    EvidenceRecord,
    MatchPolicy,
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


def _add_evidence(evidence, dataset, sample_accession, category, matches, text, source, confidence, decision):
    for match in matches:
        evidence.append(
            EvidenceRecord(
                dataset_accession=dataset.accession,
                sample_accession=sample_accession,
                category=category,
                matched_term=match.term,
                matched_text=text,
                source_field=source,
                normalized_term=match.group,
                ontology_id=match.ontology_id,
                confidence=confidence,
                decision=decision,
            )
        )


def curate_dataset(dataset: DatasetRecord, samples: list[SampleRecord], query: QuerySpec) -> CurationResult:
    output = dataset.model_copy(deep=True)
    curated_samples = [sample.model_copy(deep=True) for sample in samples]
    evidence: list[EvidenceRecord] = []
    organism_terms = [*query.organisms, *query.taxonomy_ids]
    policy = query.match_policy

    sample_exact = False
    sample_tissue_only = False
    sample_disease_only = False
    case_samples = 0
    mechanism_hits = set()

    for sample in curated_samples:
        text = _sample_text(sample)
        tissue_matches = match_groups(text, query.tissues)
        disease_matches = match_groups(text, query.diseases)
        mechanism_matches = match_groups(text, query.mechanisms)
        mechanism_hits.update(match.group for match in mechanism_matches)
        organism_ok = not organism_terms or any(
            contains_exact(text, term)
            or contains_exact(sample.organism or "", term)
            or sample.taxonomy_id == term
            for term in organism_terms
        )
        excluded = [term for term in query.exclude_terms if contains_exact(text, term)]
        _add_evidence(evidence, dataset, sample.accession, "tissue", tissue_matches, text, "sample_metadata", 1.0, EvidenceDecision.INCLUDE)
        _add_evidence(evidence, dataset, sample.accession, "disease", disease_matches, text, "sample_metadata", 1.0, EvidenceDecision.INCLUDE)
        _add_evidence(evidence, dataset, sample.accession, "mechanism", mechanism_matches, text, "sample_metadata", 0.9, EvidenceDecision.REVIEW)
        for term in excluded:
            evidence.append(EvidenceRecord(dataset_accession=dataset.accession, sample_accession=sample.accession, category="exclusion", matched_term=term, matched_text=text, source_field="sample_metadata", confidence=1.0, decision=EvidenceDecision.EXCLUDE))

        treatment_text = str(sample.provenance.get("treatment_text") or sample.treatment.original_text or "")
        sample.treatment = classify_treatment(treatment_text)
        if organism_ok and not excluded:
            sample_tissue_only = sample_tissue_only or bool(tissue_matches)
            sample_disease_only = sample_disease_only or bool(disease_matches)
            if tissue_matches and disease_matches:
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
    dataset_mechanisms = match_groups(dataset_text, query.mechanisms)
    mechanism_hits.update(match.group for match in dataset_mechanisms)
    dataset_excluded = [term for term in query.exclude_terms if contains_exact(dataset_text, term)]
    _add_evidence(evidence, dataset, None, "mechanism", dataset_mechanisms, dataset_text, "study_metadata", 0.7, EvidenceDecision.REVIEW)

    tissue_any = sample_tissue_only or bool(dataset_tissues)
    disease_any = sample_disease_only or bool(dataset_diseases)

    if dataset_excluded:
        output.eligibility = EligibilityStatus.REJECTED
        output.exclusion_reason = f"excluded term: {dataset_excluded[0]}"
    elif sample_exact:
        output.eligibility = EligibilityStatus.APPROVED
        output.exclusion_reason = None
    elif policy is MatchPolicy.EXACT:
        if dataset_tissues and dataset_diseases:
            output.eligibility = EligibilityStatus.NEEDS_REVIEW
            output.exclusion_reason = "study-level match lacks same-sample tissue/disease confirmation"
            _add_evidence(evidence, dataset, None, "tissue", dataset_tissues, dataset_text, "study_metadata", 0.6, EvidenceDecision.REVIEW)
            _add_evidence(evidence, dataset, None, "disease", dataset_diseases, dataset_text, "study_metadata", 0.6, EvidenceDecision.REVIEW)
        else:
            output.eligibility = EligibilityStatus.REJECTED
            missing = []
            if not dataset_tissues:
                missing.append("exact tissue evidence")
            if not dataset_diseases:
                missing.append("explicit disease evidence")
            output.exclusion_reason = "missing " + " and ".join(missing)
    elif policy is MatchPolicy.TIERED:
        if tissue_any and disease_any:
            output.eligibility = EligibilityStatus.NEEDS_REVIEW
            output.exclusion_reason = "tier A/B candidate: tissue and metabolic phenotype evidence require manual confirmation"
        elif tissue_any:
            output.eligibility = EligibilityStatus.NEEDS_REVIEW
            output.exclusion_reason = "tier C/context candidate: target adipose depot without explicit target phenotype"
        else:
            output.eligibility = EligibilityStatus.REJECTED
            output.exclusion_reason = "no target PVAT/PRAT evidence"
    else:  # BROAD: maximize recall; tissue evidence alone is sufficient for candidate retention.
        if tissue_any:
            output.eligibility = EligibilityStatus.NEEDS_REVIEW
            output.exclusion_reason = "broad discovery candidate; phenotype and mechanism require curation"
        else:
            output.eligibility = EligibilityStatus.REJECTED
            output.exclusion_reason = "no target PVAT/PRAT evidence"

    output.provenance["curation"] = {
        "case_samples": case_samples,
        "retained_controls": query.retain_controls,
        "match_policy": policy.value,
        "tissue_evidence": tissue_any,
        "phenotype_evidence": disease_any,
        "mechanism_hits": sorted(mechanism_hits),
    }
    return CurationResult(dataset=output, samples=curated_samples, evidence=evidence)
