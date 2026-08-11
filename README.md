# OmniBioSeek

OmniBioSeek is a universal, provenance-first Python engine for discovering and
collecting public omics datasets by organism, tissue, disease, treatment, and
modality. The first release connects OmicsDI, NCBI GEO/SRA, and Arc
scBaseCount. Search rules live in YAML profiles rather than application code.

> **Scientific boundary:** OmniBioSeek discovers and prepares public data. It
> does not make clinical claims, silently broaden inclusion criteria, or treat
> single cells as biological replicates.

## Features

- Pluggable repository adapter contract.
- OmicsDI transcriptomics and proteomics discovery with PRIDE file resolution.
- NCBI GEO/SRA search, GEO SOFT sample parsing, and processed-file manifests.
- Arc scBaseCount metadata filtering with requester-pays failure reporting.
- Exact, auditable tissue/disease evidence and treatment classification.
- Processed-only, resumable, SHA-256-verified downloads.
- SQLite catalog plus CSV and optional Parquet exports.
- Conservative per-study preparation and modality-specific pooling.
- Included PVAT/PRAT–prediabetes–kidney-disease example profile.

## External-drive layout

The supported project layout is:

```text
D:\OmniBioSeek\       # Git-tracked code
D:\OmniBioSeek-data\  # catalogs, downloads, caches, prepared objects, reports
```

OmniBioSeek defaults to the second path and refuses to fall back to another
drive if `D:` is unavailable. Override it only with an absolute path:

```powershell
$env:OMNIBIOSEEK_DATA_DIR = 'D:\OmniBioSeek-data'
```

## Installation

Python 3.11 or 3.12 is supported.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,analysis]"
omnibioseek preflight
```

The lighter installation `pip install -e .` supports search, curation, catalog,
and standard downloads. The `analysis` extra adds pandas, PyArrow, AnnData,
Scanpy, and Google Cloud filesystem support.

## Credentials

```powershell
$env:NCBI_EMAIL = 'researcher@example.org'   # strongly recommended
$env:NCBI_API_KEY = '...'                    # optional; raises NCBI rate limit
$env:GOOGLE_CLOUD_PROJECT = 'project-id'     # Arc requester-pays access
```

Secrets are never accepted in profiles and must not be committed. If Google
Cloud access is missing, Arc produces a visible warning while other sources
continue.

## Usage

```powershell
omnibioseek search --profile profiles\pvat_prat_predm_kidney.yaml
omnibioseek curate --profile profiles\pvat_prat_predm_kidney.yaml
omnibioseek download --profile profiles\pvat_prat_predm_kidney.yaml --approved-only
omnibioseek prepare --profile profiles\pvat_prat_predm_kidney.yaml
omnibioseek integrate --profile profiles\pvat_prat_predm_kidney.yaml
```

Or run the complete sequence:

```powershell
omnibioseek run --profile profiles\pvat_prat_predm_kidney.yaml
```

Ambiguous study-level matches remain `needs_review` and are not downloaded by
the default workflow. Raw FASTQ/SRA and raw mass-spectrometry files are stored
as manifest entries with `skipped_raw`, never downloaded.

## Universal profiles

Profiles may use any organisms, taxonomy IDs, tissues, diseases, treatments,
modalities, and enabled repositories. See
[`profiles/universal_example.yaml`](profiles/universal_example.yaml). Terms are
matched exactly during curation; API adapters may use broader candidate queries
so that evidence can be checked locally.

## Output

The data root contains:

```text
catalog/omnibioseek.sqlite
catalog/exports/*.csv
downloads/<source>/<accession>/
prepared/<accession>/
integrated/
reports/<profile>.md
```

Every included record retains its source URL, search query, matched evidence,
and checksum. A zero-match run is valid and is reported without altering the
profile.

## Development

```powershell
python -m pytest
ruff check src tests
mypy src
```

Contributions use one focused pull request per milestone. Real datasets and
generated matrices never belong in Git.

