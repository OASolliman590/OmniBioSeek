from __future__ import annotations

from omnibioseek.models import MatchPolicy, Modality


def test_profile_loads_exact_human_query(query):
    assert query.name == "pvat_prat_predm_kidney"
    assert query.taxonomy_ids == ["9606"]
    assert query.match_policy is MatchPolicy.EXACT
    assert Modality.PROTEOMICS in query.modalities
    assert any(group.name == "metformin" for group in query.treatments)


def test_universal_profile_is_not_hard_coded():
    from pathlib import Path

    from omnibioseek.config import load_profile

    query = load_profile(Path(__file__).parents[1] / "profiles" / "universal_example.yaml")
    assert query.taxonomy_ids == ["10090"]
    assert query.tissues[0].name == "liver"

