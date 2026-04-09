import marimo

__generated_with = "0.23.0"
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
    mat_url = f"https://graphql.datafordeler.dk/MAT/v1?apikey={api_key}"
    return bbr_url, mat_url, vur_url


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


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## BBR
    ### BBR Bygning
    """)
    return


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


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VUR
    ### VUR BFEKrydsreference
    """)
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


@app.cell
async def _(download_page, gql, vur_url):
    _query = gql(
            """
            query GetVUR_Grundvaerdispecifikation($cursor: String) {
              VUR_Grundvaerdispecifikation(
                first: 1000
                after: $cursor
              ) {
                pageInfo {
                  endCursor
                  hasNextPage
                }
                nodes {
                    GrundvaerdispecifikationID
                    loebenummer # Fortløbende nummer pr specifikation.
                    datafordelerRowId
                    datafordelerRowVersion
                    datafordelerOpdateringstid
                    fkEjendomsvurderingID
                    areal # Angivelse af arealet i m2 pr. specifikation.
                    beloeb # Udregnet grundværdi (i hele kr.) for en given grundværdispecifikation.
                    enhedBeloeb # Enhedsbeløb angiver prisen pr. enhed i en grundværdispecifikation.
                    prisKode # Priskoden angiver arten af en enhedspris i en grundværdispecifikation.
                    tekst # Forklarende tekst i tilknytning til en grundværdispecifikation.
                }
              }
            }    
            """
        )
    gvspec_result, gvspec_table = await download_page(vur_url, _query, {"cursor":None}, "VUR_Grundvaerdispecifikation")
    return (gvspec_table,)


@app.cell
def _(gvspec_table):
    gvspec_table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Matrikler
    ### Ejerjlighed
    """)
    return


@app.cell
async def _(download_page, gql, mat_url):
    _query = gql(
            """
            query GetMAT_Ejerlejlighed($cursor: String) {
              MAT_Ejerlejlighed(
                first: 1000
                after: $cursor
                registreringstid: "2026-01-01T00:00:00+01:00"
                virkningstid: "2026-01-01T00:00:00+01:00"
                where: {
                  status: {
                    eq: "Gældende" # status 7: Gældende
                  }
                }
              ) {
                pageInfo {
                  endCursor
                  hasNextPage
                }
                nodes {
                    BFEnummer
                    datafordelerRowId
                    datafordelerRowVersion
                    datafordelerOpdateringstid
                    ejerlejlighedsnummer # identifikation af den enkelte ejerlejlighed der ligger i en hovedejendom
                    id_lokalId
                    samletFastEjendomLokalId
                    status # angivelse af hvor et forretningsobjekt er i sin livscyklus
                    virkningFra
                    virkningTil
                }
              }
            }    
            """
        )
    ejl_result, ejl_table = await download_page(mat_url, _query, {"cursor":None}, "MAT_Ejerlejlighed")
    return (ejl_table,)


@app.cell
def _(ejl_table):
    ejl_table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    MAT_Ejerlejlighed mangler geomterien, men der er en reference til MAT_SamletFastEjendom. Lad os se på den:
    """)
    return


@app.cell
async def _(download_page, gql, mat_url):
    _query = gql(
            """
            query GetMAT_SamletFastEjendom($cursor: String) {
              MAT_SamletFastEjendom(
                first: 1000
                after: $cursor
                registreringstid: "2026-01-01T00:00:00+01:00"
                virkningstid: "2026-01-01T00:00:00+01:00"
                where: {
                  status: {
                    eq: "Gældende" # status 7: Gældende
                  }
                }
              ) {
                pageInfo {
                  endCursor
                  hasNextPage
                }
                nodes {
                    BFEnummer
                    datafordelerRowId
                    datafordelerRowVersion
                    datafordelerOpdateringstid
                    geometri { type crs dimension wkt } # objektets geografiske placering, CRS: EPSG:25832
                    id_lokalId
                    status # angivelse af hvor et forretningsobjekt er i sin livscyklus
                    virkningFra
                    virkningTil
                }
              }
            }    
            """
        )
    sfe_result, sfe_table = await download_page(mat_url, _query, {"cursor":None}, "MAT_SamletFastEjendom")
    return (sfe_table,)


@app.cell
def _(sfe_table):
    sfe_table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Samlet Fast Ejendom har hele geometrien (multi-polygon), vi ønsker os blot centerpunktet.
    """)
    return


if __name__ == "__main__":
    app.run()
