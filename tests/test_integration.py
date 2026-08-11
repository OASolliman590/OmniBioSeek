from omnibioseek.integrate import design_is_identifiable


def test_design_identifiability_rejects_complete_confounding():
    rows = [
        {"study": "A", "condition": "case"},
        {"study": "A", "condition": "case"},
        {"study": "B", "condition": "control"},
    ]
    assert not design_is_identifiable(rows, "study", "condition")


def test_design_identifiability_accepts_within_batch_comparison():
    rows = [
        {"study": "A", "condition": "case"},
        {"study": "A", "condition": "control"},
        {"study": "B", "condition": "case"},
    ]
    assert design_is_identifiable(rows, "study", "condition")

