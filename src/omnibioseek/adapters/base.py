"""Repository adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from omnibioseek.models import DatasetRecord, FileRecord, QuerySpec, SampleRecord


class AdapterError(RuntimeError):
    """A repository adapter could not complete an operation."""


class AdapterUnavailable(AdapterError):
    """An optional service, credential, or dependency is unavailable."""


class RepositoryAdapter(ABC):
    name: str

    @abstractmethod
    def search(self, query: QuerySpec) -> Iterable[DatasetRecord]:
        raise NotImplementedError

    @abstractmethod
    def fetch_study(self, accession: str) -> DatasetRecord | None:
        raise NotImplementedError

    @abstractmethod
    def fetch_samples(self, accession: str) -> Iterable[SampleRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_files(self, accession: str) -> Iterable[FileRecord]:
        raise NotImplementedError

    @abstractmethod
    def download_processed(self, file_record: FileRecord, destination: str) -> FileRecord:
        raise NotImplementedError

