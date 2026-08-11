"""OmniBioSeek command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from omnibioseek.config import ProfileError, load_profile
from omnibioseek.models import QuerySpec
from omnibioseek.paths import DataRootError, configured_data_root
from omnibioseek.pipeline import Pipeline

app = typer.Typer(
    name="omnibioseek",
    help="Universal, provenance-first public omics dataset discovery and collection.",
    no_args_is_help=True,
)

ProfileOption = Annotated[
    Path,
    typer.Option("--profile", "-p", exists=True, dir_okay=False, readable=True, help="YAML query profile."),
]
DataOption = Annotated[
    Path | None,
    typer.Option("--data-dir", help="Absolute data root; defaults to OMNIBIOSEEK_DATA_DIR or D:\\OmniBioSeek-data."),
]


def _load(profile: Path, data_dir: Path | None) -> tuple[Pipeline, QuerySpec]:
    try:
        query = load_profile(profile)
        pipeline = Pipeline(configured_data_root(data_dir))
        return pipeline, query
    except (ProfileError, DataRootError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@app.command()
def search(profile: ProfileOption, data_dir: DataOption = None) -> None:
    """Discover studies and enrich available sample metadata."""
    pipeline, query = _load(profile, data_dir)
    records = pipeline.search(query)
    typer.echo(f"Discovered {len(records)} deduplicated dataset records.")


@app.command()
def curate(profile: ProfileOption, data_dir: DataOption = None) -> None:
    """Apply exact evidence rules; unresolved studies remain review-only."""
    pipeline, query = _load(profile, data_dir)
    records = pipeline.curate(query)
    counts: dict[str, int] = {}
    for record in records:
        counts[record.eligibility.value] = counts.get(record.eligibility.value, 0) + 1
    typer.echo(json.dumps(counts, indent=2))


@app.command()
def download(
    profile: ProfileOption,
    data_dir: DataOption = None,
    approved_only: Annotated[bool, typer.Option("--approved-only/--include-review")] = True,
) -> None:
    """Download processed/metadata files; raw files are always manifest-only."""
    pipeline, query = _load(profile, data_dir)
    paths = pipeline.download(query, approved_only=approved_only)
    typer.echo(f"Downloaded {len(paths)} files.")


@app.command()
def prepare(profile: ProfileOption, data_dir: DataOption = None) -> None:
    """Prepare approved downloaded files without hidden scientific transformations."""
    pipeline, query = _load(profile, data_dir)
    artifacts = pipeline.prepare(query)
    typer.echo(f"Prepared {len(artifacts)} artifacts.")


@app.command()
def integrate(profile: ProfileOption, data_dir: DataOption = None) -> None:
    """Pool only compatible modality-specific artifacts."""
    pipeline, query = _load(profile, data_dir)
    results = pipeline.integrate(query)
    typer.echo(json.dumps(results, indent=2))


@app.command(name="run")
def run_pipeline(profile: ProfileOption, data_dir: DataOption = None) -> None:
    """Run discovery, curation, approved downloads, preparation, and integration."""
    pipeline, query = _load(profile, data_dir)
    pipeline.run(query)
    typer.echo(f"Completed profile {query.name}; outputs: {pipeline.layout.root}")


@app.command()
def preflight(data_dir: DataOption = None) -> None:
    """Validate the configured external-drive layout without querying repositories."""
    root = configured_data_root(data_dir)
    try:
        pipeline = Pipeline(root)
    except DataRootError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Data root ready: {pipeline.layout.root}")


if __name__ == "__main__":
    app()
