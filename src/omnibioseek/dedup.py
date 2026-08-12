"""Cross-repository study deduplication with explicit source provenance."""

from __future__ import annotations

import re

from omnibioseek.models import DatasetRecord

ACCESSION_PATTERN = re.compile(
    r"\b(?:GSE\d+|GSM\d+|SRP\d+|SRX\d+|SRS\d+|SRR\d+|ERP\d+|ERX\d+|ERS\d+|ERR\d+|"
    r"PRJNA\d+|PRJEB\d+|PXD\d+|E-MTAB-\d+|E-GEOD-\d+|S-BSST\d+|MTBLS\d+)\b",
    re.I,
)


def cross_accessions(record: DatasetRecord) -> set[str]:
    values = {record.accession.upper()}
    values.update(str(value).upper() for value in record.provenance.get("cross_accessions", []))
    values.update(ACCESSION_PATTERN.findall(f"{record.title} {record.description}"))
    return values


def deduplicate(records: list[DatasetRecord]) -> list[DatasetRecord]:
    groups: list[list[DatasetRecord]] = []
    group_tokens: list[set[str]] = []
    for record in records:
        tokens = cross_accessions(record) | {f"PMID:{value}" for value in record.pmids}
        tokens |= {f"DOI:{value.casefold()}" for value in record.dois}
        matches = [index for index, existing in enumerate(group_tokens) if tokens & existing]
        if not matches:
            groups.append([record])
            group_tokens.append(tokens)
            continue
        target = matches[0]
        groups[target].append(record)
        group_tokens[target].update(tokens)
        for index in reversed(matches[1:]):
            groups[target].extend(groups.pop(index))
            group_tokens[target].update(group_tokens.pop(index))

    deduplicated: list[DatasetRecord] = []
    priority = {"ncbi": 0, "arc": 1, "pride": 2, "omicsdi": 3, "pubmed": 4}
    for index, group in enumerate(groups):
        primary = sorted(group, key=lambda item: priority.get(item.source, 10))[0].model_copy(deep=True)
        primary.canonical_id = sorted(group_tokens[index])[0] if group_tokens else primary.record_id
        primary.provenance["alternate_sources"] = [
            {"source": item.source, "accession": item.accession, "record_id": item.record_id}
            for item in group
            if item.record_id != primary.record_id
        ]
        primary.provenance["alternate_records"] = [
            item.model_dump(mode="json", exclude_none=True)
            for item in group
            if item.record_id != primary.record_id
        ]
        if any(item.source == "arc" for item in group):
            primary.provenance["preferred_matrix_source"] = "arc"
        deduplicated.append(primary)
    return deduplicated
