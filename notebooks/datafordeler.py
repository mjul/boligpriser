import marimo

__generated_with = "0.21.1"
app = marimo.App()


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Explore Datafordeler APIs
    """)
    return


@app.cell
def _():
    import io
    import os
    import marimo as mo
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    import geoarrow.pyarrow as ga
    import geoarrow.pyarrow.io as gaio
    import geopandas as gpd
    import numpy as np
    from gql import Client, GraphQLRequest, gql
    from gql.transport.aiohttp import AIOHTTPTransport

    return AIOHTTPTransport, Client, gql, mo, os, pa, pc


@app.cell
def _(os):
    api_key = os.getenv("DATAFORDELER_API_KEY")
    assert(api_key, "DATAFORDELER_API_KEY not defined")
    return (api_key,)


@app.cell
def _(api_key):
    bbr_url = f"https://graphql.datafordeler.dk/BBR/v1?apikey={api_key}"
    vur_url = f"https://graphql.datafordeler.dk/VUR/v2?apikey={api_key}"
    return bbr_url, vur_url


@app.cell
def _(AIOHTTPTransport, Client, pa):
    async def download_page(url_with_key, query, bindings, entity):
        transport = AIOHTTPTransport(url=url_with_key, timeout=120)
        client = Client(transport=transport)
        async with client as session:
            result = await session.execute(query, variable_values=bindings)
            table = pa.Table.from_pylist(result[entity]["nodes"])
        return (result, table)

    return (download_page,)


@app.cell
async def _(bbr_url, download_page, gql):
    _query = gql(
            """
            query ($cursor: String, $kommunekode: String!) {
              BBR_Bygning(
                virkningstid: "2026-01-01T00:00:00+01:00"
                first: 1000
                after: $cursor
                where: {
                  kommunekode: {eq: $kommunekode}
                  #status: {eq: "6"}
                }
              ) {
                pageInfo {
                  endCursor
                  hasNextPage
                }
                nodes {
                    status # kode for bygværkselementets status i den pågældende version, dvs. elementets tilstand i den samlede livscyklus
                }
              }
            }    
            """
        )
    result, table = await download_page(bbr_url, _query, {"cursor":None, "kommunekode": "0825"}, "BBR_Bygning")
    return (table,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Hvilke statuskoder er i brug for bygninger?

    Vi har en hypotese om, at vi kun skal kigge på 6 ("Opført"), men lad os se på data.

    Se kodelisten på https://teknik.bbr.dk/kodelister/0/1/0/Livscyklus
    """)
    return


@app.cell
def _(pa, pc, table):
    pc.unique(table["status"]).cast(pa.int32()).sort()
    return


@app.cell
async def _(download_page, gql, vur_url):
    _query = gql(
            """
            query GetVUR_BFEKrydsreference($cursor: String) {
              VUR_BFEKrydsreference(
                first: 1000
                after: $cursor
              ) {
                pageInfo {
                  endCursor
                  hasNextPage
                }
                nodes {
                    BFEKrydsreferenceID
                    BFEnummer
                    datafordelerRowId
                    datafordelerRowVersion
                    datafordelerOpdateringstid
                    fkEjendomsvurderingID
                }
              }
            }    
            """
        )
    bfe_result, bfe_table = await download_page(vur_url, _query, {"cursor":None}, "VUR_BFEKrydsreference")
    return (bfe_table,)


@app.cell
def _(bfe_table):
    bfe_table
    return


if __name__ == "__main__":
    app.run()
