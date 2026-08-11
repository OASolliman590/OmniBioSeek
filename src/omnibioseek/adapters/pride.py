"""Resolve processed PRIDE files for PXD records discovered through OmicsDI."""

from __future__ import annotations

from collections.abc import Iterable

from omnibioseek.adapters.utils import classify_file, file_format
from omnibioseek.http import HttpClient, HttpError
from omnibioseek.models import FileRecord


class PrideFileResolver:
    base_url = "https://www.ebi.ac.uk/pride/ws/archive/v2/projects"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def list_files(self, accession: str) -> Iterable[FileRecord]:
        try:
            payload = self.client.get_json(f"{self.base_url}/{accession}/files")
        except HttpError:
            return []
        files = payload.get("_embedded", {}).get("files", payload.get("files", payload))
        if not isinstance(files, list):
            return []
        records: list[FileRecord] = []
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                continue
            name = str(item.get("fileName") or item.get("name") or f"file-{index}")
            category_value = item.get("fileCategory") or item.get("category") or ""
            category = (
                str(category_value.get("value") or category_value.get("name") or "")
                if isinstance(category_value, dict)
                else str(category_value)
            )
            locations = item.get("publicFileLocations") or item.get("downloadLink") or []
            if isinstance(locations, str):
                locations = [{"value": locations}]
            url = ""
            for location in locations:
                if isinstance(location, dict):
                    url = str(location.get("value") or location.get("location") or location.get("url") or "")
                if url.startswith(("https://", "ftp://")):
                    break
            if not url:
                continue
            records.append(
                FileRecord(
                    source="pride",
                    dataset_accession=accession,
                    file_id=str(item.get("accession") or index),
                    url=url,
                    name=name,
                    kind=classify_file(name, category),
                    format=file_format(name),
                    size_bytes=item.get("fileSizeBytes") or item.get("fileSize"),
                    provenance={"category": category, "pride": item},
                )
            )
        return records

