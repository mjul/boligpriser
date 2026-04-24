import marimo

__generated_with = "0.23.2"
app = marimo.App()


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Estimering af værdiflader og isolinier for geografisk fordeling af vurderingerne
    """)
    return


@app.cell
def _():
    import io
    import marimo as mo
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    import geoarrow.pyarrow as ga
    import geoarrow.pyarrow.io as gaio
    import geopandas as gpd
    import numpy as np

    return gpd, mo, pc, pq


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Indlæs data
    ### MAT Samlet Fast Ejendom (SFE)
    SFEerne har en geometri (multipolygon) i MAT som vi kan bruge til beliggenheden (vi udregner midterpunktet).
    """)
    return


@app.cell
def _(pq):
    MAT_SFE_FILE = "data/mat_samletfastejendom.parquet"
    print(pq.read_schema(MAT_SFE_FILE))
    raw_sfe = pq.read_table(MAT_SFE_FILE, columns=["BFEnummer", "geometri"])
    return (raw_sfe,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VUR Ejendomsvurderinger
    Her er selve vurderingerne.
    """)
    return


@app.cell
def _(pq):
    VUR_EV_FILE = "data/vur_ejendomsvurdering.parquet"
    print(pq.read_schema(VUR_EV_FILE))
    raw_ev = pq.read_table(VUR_EV_FILE, columns=["id", "ejendomvaerdiBeloeb", "grundvaerdiBeloeb", "vurderetAreal","benyttelseKode", "fkVurderingsejendomID"])
    return (raw_ev,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### VUR BFE krydsreference
    Ejendomsvurderingerne har ikke BFE-nummer, det finder vi her. Det skal bruges for at navigere til SFEerne.
    """)
    return


@app.cell
def _(pq):
    VUR_BFEKRYDS_FILE = "data/vur_bfekrydsreference.parquet"
    print(pq.read_schema(VUR_BFEKRYDS_FILE))
    raw_bfekryds = pq.read_table(VUR_BFEKRYDS_FILE, columns=["BFEnummer", "fkEjendomsvurderingID"])
    return (raw_bfekryds,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### BBR Ejendomsrelation
    Vurderingerne har ikke nogen kommunekode, hvilket er en nem måde begrænse vores data på geografisk. Vi kan finde den i BBR.
    """)
    return


@app.cell
def _(pq):
    BBR_EJDREL_FILE = "data/bbr_ejendomsrelation.parquet"
    print(pq.read_schema(BBR_EJDREL_FILE))
    raw_ejdrel = pq.read_table(BBR_EJDREL_FILE, columns=["bfeNummer", "kommunekode"])
    return (raw_ejdrel,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Sammenstyk data
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Kun villaer og ejerlejligheder
    """)
    return


@app.cell
def _(pc, raw_bfekryds, raw_ejdrel, raw_ev):
    _bolig = pc.field("benyttelseKode") == '01' 
    _ejerlejl_bolig = pc.field("benyttelseKode") == '21' 
    _vurd_uden_bfe = raw_ev.filter(_bolig | _ejerlejl_bolig).select(["id", "ejendomvaerdiBeloeb", "grundvaerdiBeloeb", "vurderetAreal", "benyttelseKode", "fkVurderingsejendomID"])

    # Tilknyt BFE-numre og kommunekoder
    vurd_table = _vurd_uden_bfe.join(raw_bfekryds, keys=["id"], right_keys=["fkEjendomsvurderingID"], join_type="inner").join(raw_ejdrel, keys=["BFEnummer"], right_keys=["bfeNummer"])
    print(vurd_table.schema)
    return (vurd_table,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Geometrier
    Det tager lidt tid at beregne så vi udtrækker først de SFEer, hvor
    der findes en vurdering, så vi kan regne på lidt færre.
    Derefter udregner vi midtpunktet for SFEernes multi-polygoner.
    """)
    return


@app.cell
def _(gpd, pc, raw_sfe, vurd_table):
    _bfeer = pc.unique(vurd_table.column("BFEnummer"))
    _har_vurd = pc.is_in(raw_sfe.column("BFEnummer"), value_set=_bfeer)
    _sfe_med_vurd = raw_sfe.filter(_har_vurd)

    _wkt_array = pc.struct_field(_sfe_med_vurd['geometri'], 'wkt')  # Extract wkt child
    _crs_array = pc.struct_field(_sfe_med_vurd['geometri'], 'crs')  # Extract crs child

    # Check antagelsen om CRS format for en sikkerheds skyld
    assert(pc.unique(_crs_array).to_pylist() == [25832])

    _wkt_series = _wkt_array.to_pandas()
    _gs = gpd.GeoSeries.from_wkt(_wkt_series)
    _gs.crs = "EPSG:25832"
    _centroids = _gs.centroid.to_arrow()  # Back to GeoArrow WKB

    sfe_med_geo = _sfe_med_vurd.append_column("centroid", _centroids)
    return (sfe_med_geo,)


@app.cell
def _(sfe_med_geo):
    sfe_med_geo
    return


if __name__ == "__main__":
    app.run()
