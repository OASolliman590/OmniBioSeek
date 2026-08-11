from omnibioseek.models import TreatmentCategory
from omnibioseek.terminology import classify_treatment, contains_exact


def test_exact_matching_observes_word_boundaries():
    assert contains_exact("human PVAT sample", "PVAT")
    assert not contains_exact("XPVAT-like token", "PVAT")
    assert contains_exact("impaired fasting glucose", "impaired fasting glucose")


def test_metformin_and_other_treatments_are_classified():
    exposure = classify_treatment("oral metformin 500 mg for 12 weeks")
    assert exposure.category is TreatmentCategory.METFORMIN
    assert exposure.ontology_id == "CHEBI:6801"
    assert exposure.dose == "500 mg"
    assert exposure.duration == "12 weeks"
    assert classify_treatment("untreated baseline").category is TreatmentCategory.UNTREATED
    assert classify_treatment("lifestyle intervention").category is TreatmentCategory.LIFESTYLE

