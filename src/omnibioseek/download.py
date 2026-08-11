"""Processed-only, resumable, checksum-verifying downloads."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from omnibioseek.models import DownloadStatus, FileKind, FileRecord


class DownloadError(RuntimeError):
    """A requested processed file could not be downloaded safely."""


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_filename(value: str) -> str:
    name = Path(value).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "download"


class Downloader:
    def __init__(self, *, timeout_seconds: float = 120.0, chunk_size: int = 1024 * 1024) -> None:
        self.timeout_seconds = timeout_seconds
        self.chunk_size = chunk_size

    def download(self, record: FileRecord, destination: str | Path) -> FileRecord:
        if record.kind is FileKind.RAW:
            record.download_status = DownloadStatus.SKIPPED_RAW
            return record
        if record.kind not in {FileKind.PROCESSED, FileKind.METADATA}:
            record.download_status = DownloadStatus.UNAVAILABLE
            return record
        if record.url.startswith("gs://"):
            raise DownloadError("gs:// files must be downloaded by their requester-pays adapter")

        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / safe_filename(record.name)
        partial = target.with_name(f"{target.name}.part")

        if target.exists():
            digest = sha256_file(target)
            if record.checksum and digest.casefold() != record.checksum.casefold():
                raise DownloadError(f"existing file checksum mismatch: {target}")
            record.checksum = digest
            record.local_path = str(target)
            record.size_bytes = target.stat().st_size
            record.download_status = DownloadStatus.DOWNLOADED
            return record

        start = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "OmniBioSeek/0.1"}
        if start:
            headers["Range"] = f"bytes={start}-"
        request = Request(record.url, headers=headers)
        try:
            response = urlopen(request, timeout=self.timeout_seconds)  # noqa: S310
        except (HTTPError, OSError) as exc:
            record.download_status = DownloadStatus.FAILED
            raise DownloadError(f"download failed for {record.url}: {exc}") from exc

        status = getattr(response, "status", 200)
        mode = "ab" if start and status == 206 else "wb"
        try:
            with partial.open(mode) as handle, response:
                while chunk := response.read(self.chunk_size):
                    handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
            partial.replace(target)
        except Exception:
            record.download_status = DownloadStatus.FAILED
            raise

        digest = sha256_file(target)
        if record.checksum and digest.casefold() != record.checksum.casefold():
            record.download_status = DownloadStatus.FAILED
            raise DownloadError(f"checksum mismatch after download: {record.name}")
        record.checksum = digest
        record.local_path = str(target)
        record.size_bytes = target.stat().st_size
        record.download_status = DownloadStatus.DOWNLOADED
        return record

