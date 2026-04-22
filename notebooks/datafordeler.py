import marimo

__generated_with = "0.23.2"
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
    import pyproj
    import shapely
    from gql import Client, GraphQLRequest, gql
    from gql.transport.aiohttp import AIOHTTPTransport

    return AIOHTTPTransport, Client, gpd, gql, mo, os, pa, pc


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
                #registreringstid: "2026-01-01T00:00:00+01:00"
                virkningstid: "2026-01-01T00:00:00+01:00"
                first: 1000
                after: $cursor
                where: {
                  kommunekode: {eq: $kommunekode}
                  #byg021BygningensAnvendelse: {in: ["120", "140", "510"]}
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
    ### BBR Ejendomsrelation
    """)
    return


@app.cell
async def _(bbr_url, download_page, gql):
    _query = gql(
        """
        query GetBBREjendomsrelation($cursor: String, $kommunekode: String!) {
          BBR_Ejendomsrelation(
            virkningstid: "2026-01-01T00:00:00+01:00"
            first: 1000
            after: $cursor
            where: {
              kommunekode: {eq: $kommunekode}
              status: { eq: "7" } #  7: Gældende
              bfeNummer: {eq: 3253407}
            }
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                id_lokalId
                kommunekode
                status # kode for bygværkselementets status i den pågældende version, dvs. elementets tilstand i den samlede livscyklus 
                bfeNummer # Long, angiver den fælles ejendomsidentifikation for den bestemte faste ejendom som den tilhørende BBR-entitet udgør eller indgår 
                ejendomsnummer # String
                ejendomstype # String
                ejerlejlighed # String
                ejerlejlighedsnummer # Long
                vurderingsejendomsnummer # Long
                virkningFra # tidspunktet hvor virkningen af den pågældende version af bygværkselementet er startet
                virkningTil # tidspunktet hvor virkningen af den pågældende version af bygværkselementet ophører
            }
          }
        }    
        """
    )

    er_result, er_table = await download_page(bbr_url, _query, {"cursor":None, "kommunekode": "0825"}, "BBR_Ejendomsrelation")
    return (er_table,)


@app.cell
def _(er_table):
    er_table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### BBR BygningEjendomsrelation
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Der er en lidt mere specialiseret relation mellem bygninger og ejendomsrelation i BBR, lad os kigge på den:
    """)
    return


@app.cell
async def _(bbr_url, download_page, gql):
    _query = gql(
        """
        query GetBBRBygningEjendomsrelation($cursor: String, $kommunekode: String!) {
          BBR_BygningEjendomsrelation(
            virkningstid: "2026-01-01T00:00:00+01:00"
            first: 1000
            after: $cursor
            where: {
              kommunekode: {eq: $kommunekode}
              #status: { eq: "7" } #  7: Gældende
            }
          ) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
                id_lokalId
                kommunekode
                bygning # 
                bygningPaaFremmedGrund #
                forretningshaendelse
                forretningsomraade
                status # kode for bygværkselementets status i den pågældende version, dvs. elementets tilstand i den samlede livscyklus 
                virkningFra # tidspunktet hvor virkningen af den pågældende version af bygværkselementet er startet
                virkningTil # tidspunktet hvor virkningen af den pågældende version af bygværkselementet ophører
            }
          }
        }    
        """
    )

    ber_result, ber_table = await download_page(bbr_url, _query, {"cursor":None, "kommunekode": "0825"}, "BBR_BygningEjendomsrelation")
    return (ber_table,)


@app.cell
def _(ber_table):
    ber_table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Det ser ikke ud til, at vi kan bruge dette til så meget.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VUR
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### VUR Ejendomsvurdering
    """)
    return


@app.cell
async def _(download_page, gql, vur_url):
    _query = gql(
    """
            query GetVUR_Ejendomsvurdering($cursor: String, $vurderingsaar: Long!) {
              VUR_Ejendomsvurdering(
                first: 1000
                after: $cursor
                where: {
                  ajourfoeringDato: {lt: "2026-01-01T00:00:00+01:00"}
                  aar: {eq: $vurderingsaar}
                }
              ) {
                pageInfo {
                  endCursor
                  hasNextPage
                }
                nodes {
                    id
                    datafordelerRowId
                    datafordelerRowVersion
                    aar
                    ejendomvaerdiBeloeb
                    grundvaerdiBeloeb
                    juridiskKategoriKode # Kode der angiver den juridiske kategori, som ejendommen er tildelt ved denne ejendomsvurdering.
                    juridiskKategoriTekst # Tekst, der beskriver den juridiske kategori, som ejendommen er tildelt ved denne ejendomsvurdering
                    juridiskUnderkategoriKode
                    juridiskUnderkategoriTekst
                    vurderetAreal # Vurderet grundareal. Ejendommens samlede vurderede areal i m2 (incl. Vejareal).
                    ajourfoeringDato # Timestamp for hvornår en vurdering, en eventuel vurderingsændring, årsregulering eller §4/4A vurdering er  opdateret enten maskinelt ved en batch-kørsel eller i forbindelse med sagsbehandling.
                    aendringDato # Dato for seneste gældende vurdering.
                    benyttelseKode
                    antalMedvurderedeLejligheder # Antal medvurderede lejligheder i den vurderede ejendom
                    vurderingskredsKode
                    VURMark # Angiver kilde-system og type for vurderingen -- nødvendig for at afgøre om det er den gældende vurdering
                    fkVurderingsejendomID
                }
              }
            }    
            """
        )
    ev_result, ev_table = await download_page(vur_url, _query, {"cursor":None, "vurderingsaar": 2022}, "VUR_Ejendomsvurdering")
    return (ev_table,)


@app.cell
def _(ev_table):
    ev_table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
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


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### VUR Grundværdispecifikation
    """)
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
    gvspec_table.sort_by([("fkEjendomsvurderingID", "ascending"), ("loebenummer", "ascending")])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Matrikler
    ### Ejerlejlighed
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
def _():
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Samlet Fast Ejendom
    MAT_Ejerlejlighed mangler geometrien, men der er en reference til MAT_SamletFastEjendom. Lad os se på den:
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


@app.cell
def _(gpd, pc, sfe_table):
    _wkt_array = pc.struct_field(sfe_table['geometri'], 'wkt')  # Extract wkt child
    _crs_array = pc.struct_field(sfe_table['geometri'], 'crs')  # Extract crs child
    _crs_code = 25832  # Fixed 25832

    _wkt_series = _wkt_array.to_pandas()
    _gs = gpd.GeoSeries.from_wkt(_wkt_series)
    _gs.crs = "EPSG:25832"  # From your crs field
    _centroids = _gs.centroid.to_arrow()  # Back to GeoArrow WKB

    sfe_med_geo = sfe_table.drop_columns(["geometri"]).append_column("geometry", _centroids)
    print(sfe_med_geo.schema)
    sfe_med_geo
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
