from __future__ import annotations

from pathlib import Path

import pytest

from omnibioseek.config import load_profile


@pytest.fixture()
def profile_path() -> Path:
    return Path(__file__).parents[1] / "profiles" / "pvat_prat_predm_kidney.yaml"


@pytest.fixture()
def query(profile_path: Path):
    return load_profile(profile_path)

