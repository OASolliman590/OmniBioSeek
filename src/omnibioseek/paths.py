"""External-drive-safe output layout."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_ROOT = Path(r"D:\OmniBioSeek-data")


class DataRootError(RuntimeError):
    """Configured data root is missing or unsafe."""


def configured_data_root(override: str | Path | None = None) -> Path:
    raw = override or os.getenv("OMNIBIOSEEK_DATA_DIR") or DEFAULT_DATA_ROOT
    return Path(raw).expanduser()


def ensure_data_root(path: str | Path, *, create: bool = True) -> Path:
    root = Path(path).expanduser()
    if not root.is_absolute():
        raise DataRootError(f"data directory must be absolute: {root}")
    anchor = Path(root.anchor)
    if not anchor.exists():
        raise DataRootError(
            f"drive or mount for {root} is unavailable; refusing to fall back to another disk"
        )
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise DataRootError(f"data path is not a directory: {root}")
    return root.resolve()


@dataclass(frozen=True, slots=True)
class DataLayout:
    root: Path
    catalog: Path
    downloads: Path
    cache: Path
    prepared: Path
    integrated: Path
    reports: Path
    logs: Path

    @classmethod
    def create(cls, root: str | Path) -> DataLayout:
        resolved = ensure_data_root(root)
        layout = cls(
            root=resolved,
            catalog=resolved / "catalog",
            downloads=resolved / "downloads",
            cache=resolved / "cache",
            prepared=resolved / "prepared",
            integrated=resolved / "integrated",
            reports=resolved / "reports",
            logs=resolved / "logs",
        )
        for directory in layout.__dict__.values() if hasattr(layout, "__dict__") else (
            layout.catalog,
            layout.downloads,
            layout.cache,
            layout.prepared,
            layout.integrated,
            layout.reports,
            layout.logs,
        ):
            Path(directory).mkdir(parents=True, exist_ok=True)
        return layout

