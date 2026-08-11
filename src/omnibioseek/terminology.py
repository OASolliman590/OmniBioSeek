"""Exact evidence matching and treatment classification."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from omnibioseek.models import TermGroup, TreatmentCategory, TreatmentExposure


def normalized_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", text).strip()


def contains_exact(text: str, term: str) -> bool:
    normalized = normalized_text(text)
    target = normalized_text(term)
    if not target:
        return False
    pattern = rf"(?<![\w]){re.escape(target)}(?![\w])"
    return re.search(pattern, normalized, flags=re.UNICODE) is not None


@dataclass(frozen=True, slots=True)
class TermMatch:
    group: str
    term: str
    ontology_id: str | None


def match_groups(text: str, groups: list[TermGroup]) -> list[TermMatch]:
    matches: list[TermMatch] = []
    for group in groups:
        ontology = group.ontology_ids[0] if group.ontology_ids else None
        for term in group.terms:
            if contains_exact(text, term):
                matches.append(TermMatch(group=group.name, term=term, ontology_id=ontology))
    return matches


METFORMIN_TERMS = ("metformin", "glucophage", "chebi:6801")
LIFESTYLE_TERMS = (
    "lifestyle intervention",
    "diet intervention",
    "exercise intervention",
    "weight loss intervention",
)
UNTREATED_TERMS = ("untreated", "no treatment", "treatment naive", "treatment-naive", "baseline")
DRUG_HINTS = ("treated with", "therapy", "drug", "placebo", "mg", "dose")


def classify_treatment(value: str | None) -> TreatmentExposure:
    original = value or ""
    text = normalized_text(original)
    metformin = any(contains_exact(text, term) for term in METFORMIN_TERMS)
    lifestyle = any(contains_exact(text, term) for term in LIFESTYLE_TERMS)
    untreated = any(contains_exact(text, term) for term in UNTREATED_TERMS)
    other_drug = any(term in text for term in DRUG_HINTS) and not untreated
    active_count = sum((metformin, lifestyle, other_drug and not metformin))

    if active_count > 1:
        category = TreatmentCategory.COMBINATION
    elif metformin:
        category = TreatmentCategory.METFORMIN
    elif lifestyle:
        category = TreatmentCategory.LIFESTYLE
    elif untreated:
        category = TreatmentCategory.UNTREATED
    elif other_drug:
        category = TreatmentCategory.OTHER_DRUG
    else:
        category = TreatmentCategory.UNKNOWN

    dose_match = re.search(r"\b\d+(?:\.\d+)?\s*(?:mg|g|µg|ug)(?:/\w+)?\b", original, re.I)
    duration_match = re.search(
        r"\b\d+(?:\.\d+)?\s*(?:hour|day|week|month|year)s?\b", original, re.I
    )
    route_match = re.search(r"\b(oral|intravenous|subcutaneous|intraperitoneal)\b", original, re.I)
    return TreatmentExposure(
        normalized_name="metformin" if metformin else None,
        original_text=original or None,
        category=category,
        ontology_id="CHEBI:6801" if metformin else None,
        dose=dose_match.group(0) if dose_match else None,
        duration=duration_match.group(0) if duration_match else None,
        route=route_match.group(0).lower() if route_match else None,
    )

