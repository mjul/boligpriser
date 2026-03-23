# Boligpriser

Map the house prices in Denmark using public data.

## Structure

- `downloader.py` - Download the data and aggregate it into Geoparquet files.
- `explorer.py` - Analyse and plot the data.

## Data Sources

## Installation

Ensure you have `uv` installed.
Fiona and GDAL wheels are not available for Python 3.14 yet, so use the older version:

```
uv python pin 3.13
```

Then

```
uv sync
```


## Tech Stack

- `uv` for managing Python versions and environments
- `marimo` for the notebooks

- `gql` GraphQL client for downloading data from http://www.datafordeler.dk 

- `geopandas` for geospatial analysis

- `fiona` for reading and writing GeoJSON
- `pyarrow` for reading and writing Parquet

## Data

### Schemas
I recommend to download these to `schemas` for reference:

- BBR GraphQL Schema: https://datafordeler.dk/GraphQLSchema/BBR.graphql
- VUR GraphQL Schema: https://datafordeler.dk/GraphQLSchema/VUR.graphql

### Queries
I recommend writing these by hand rather than using the "Byg GraphQL Query" feature  on the Datafordeler website, since
it generates invalid queries if they contain composite types. You can use it to sketch out the queries you need, then 
use the schemas to make the queries work.

The support staff at Datafordeler recommended using a third-party tool to generate queries from the GraphQL schemas. 
The buggy feature on their website is a "known defect" (March 23, 2026).

