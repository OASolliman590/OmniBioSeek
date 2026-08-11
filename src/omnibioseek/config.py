"""YAML query-profile loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from omnibioseek.models import QuerySpec, TermGroup


class ProfileError(ValueError):
    """Raised when a query profile is missing or invalid."""


def _term_groups(value: Any, field: str) -> list[TermGroup]:
    if value is None:
        return []
    if isinstance(value, list):
        groups: list[TermGroup] = []
        for index, item in enumerate(value):
            if isinstance(item, str):
                groups.append(TermGroup(name=item, terms=[item]))
            elif isinstance(item, dict):
                groups.append(TermGroup.model_validate(item))
            else:
                raise ProfileError(f"{field}[{index}] must be a string or mapping")
        return groups
    if isinstance(value, dict):
        return [
            TermGroup(name=name, terms=details if isinstance(details, list) else [details])
            for name, details in value.items()
        ]
    raise ProfileError(f"{field} must be a list or mapping")


def load_profile(path: str | Path) -> QuerySpec:
    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise ProfileError(f"profile not found: {profile_path}")
    try:
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileError(f"invalid YAML in {profile_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProfileError("profile root must be a mapping")

    query = dict(raw.get("query", raw))
    query["name"] = raw.get("name", query.get("name", profile_path.stem))
    for key in ("tissues", "diseases", "treatments"):
        query[key] = _term_groups(query.get(key), key)
    query["metadata"] = {
        **query.get("metadata", {}),
        "profile_path": str(profile_path),
        "profile_version": raw.get("version", 1),
        "profile_description": raw.get("description", ""),
        "curation": raw.get("curation", {}),
        "integration": raw.get("integration", {}),
    }
    try:
        return QuerySpec.model_validate(query)
    except ValidationError as exc:
        raise ProfileError(str(exc)) from exc

