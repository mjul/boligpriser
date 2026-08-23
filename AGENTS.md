# AGENTS.md

Guidance for coding agents working in this repository.

## Project

**Boligpriser**: maps the distribution of housing prices (villaer and ejerlejligheder) in Denmark using public data from [Datafordeleren](https://datafordeler.dk). The README (in Danish) is the authoritative domain documentation, especially the "Data" section on the BBR/MAT/VUR datasets and their quirks.

## Commands

`uv` manages Python version and environment. Python is pinned to 3.13 (`.python-version`) because Fiona/GDAL wheels are not yet available for newer versions — do not bump this casually.

```sh
uv sync                 # install dependencies
uv run ty check         # type check (the only static verification configured)
uv run downloader.py vur ejendomsvurdering    # download VUR data (requires API key)
uv run marimo edit notebooks/explore_data.py  # open a notebook
```

There is no test suite. Verify changes with `uv run ty check` plus a targeted run of the changed code path.

## Environment

- `DATAFORDELER_API_KEY` — required by `downloader.py`; without it it raises immediately.
- `DATA_DIR` — output directory override (default `data/`).
- `HTTP_TIMEOUT_SECONDS` — HTTP timeout (default 120).

Never commit API keys. Data files are gitignored; do not commit anything under `data/`.

## Structure

- `downloader.py` — CLI that pages through Datafordeleren's GraphQL APIs (`gql` + async transport) and writes GeoParquet to `data/`. One `download_*` function per dataset; `DownloaderConfig` maps each dataset to its output file name.
- `notebooks/` — **marimo** notebooks stored as `.py` files (`app = marimo.App(...)`), not Jupyter. Edit them with `marimo edit`, never hand-edit cell code around; keep the generated structure intact. `datafordeler.py` experiments against the live API (needs API key).
- `schemas/` — reference copies of the Datafordeler GraphQL schemas (BBR.graphql, MAT.graphql, VUR.graphql). Fetch them when adding/changing queries; they are the only reliable schema reference.
- `data/` — downloaded Parquet files (gitignored). Query directly with DuckDB, e.g. `select count(*) from 'data/mat_samletfastejendom.parquet';`.
- `images/` — rendered output referenced by the README.

CLI shape: `uv run downloader.py <bbr|mat|vur> <dataset>` — see `cli_parser()` in `downloader.py`.

## Domain notes (avoid rediscovering these)

- The Datafordeler GraphQL API is paginated at max 1000 rows per request; full downloads take hours. Do not trigger full downloads casually; use the small-municipality entries in `KOMMUNEKODER` for experiments.
- There is no connected graph across schemas ("GraphQL without graph"); joins must be done client-side or via many calls. Do not use the "Fleksibel opslagslogik" schema variant.
- VUR key relationships: `Ejendomsvurdering.fkVurderingsejendomID` joins to `Vurderingsejendom.VURejendomsid`, **not** `vurderingsejendomID` despite the naming. BFE number is the future-proof key.
- Status codes are inconsistent across entities: some use numeric codes (`7` = Gældende), MAT uses strings (`"Gældende"`); for `Bygning` the relevant lifecycle status is `6 - Opført`, not `7`. Check the README section per dataset before filtering.
- `benyttelseKode` is deprecated in favor of `juridiskKategoriKode`/`juridiskUnderkategoriKode` (undocumented).
- Hand-write GraphQL queries against the schema in `schemas/`; Datafordeler's own query builder produces invalid queries for composite types.

## Conventions

- Match existing style: type-annotated modern Python (3.13, `from __future__ import annotations`), dataclasses with slots for config.
- Danish is used in user-facing docs (README) and much of the domain vocabulary; keep new domain terms consistent with existing usage rather than translating.
