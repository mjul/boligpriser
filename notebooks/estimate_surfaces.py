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

    return gpd, mo, np, pc, pq


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
    vurd_med_bfe = _vurd_uden_bfe.join(raw_bfekryds, keys=["id"], right_keys=["fkEjendomsvurderingID"], join_type="inner").join(raw_ejdrel, keys=["BFEnummer"], right_keys=["bfeNummer"])
    print(vurd_med_bfe.schema)
    return (vurd_med_bfe,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Nøgletal
    Beregn nøgletal, vurderinger normaliseret pr. kvadratmeter.
    Vi dropper først vurderinger med 0-areal.
    """)
    return


@app.cell
def _(pc, vurd_med_bfe):
    # Vi gider ikke dele med nul
    _t = vurd_med_bfe.filter(pc.field("vurderetAreal") > 0)

    _gv_pr_kvm = pc.divide(_t["grundvaerdiBeloeb"], _t["vurderetAreal"])
    _ev_pr_kvm = pc.divide(_t["ejendomvaerdiBeloeb"], _t["vurderetAreal"])
    vurd_med_nøgletal = _t.append_column("grundvaerdi_pr_kvm", _gv_pr_kvm).append_column("ejendomsvaerdi_pr_kvm", _ev_pr_kvm)
    return (vurd_med_nøgletal,)


@app.cell
def _(vurd_med_nøgletal):
    vurd_table = vurd_med_nøgletal
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

    sfe_med_geo = _sfe_med_vurd.drop_columns(["geometri"]).append_column("centroid", _centroids).append_column("poly", _gs.to_arrow())
    return (sfe_med_geo,)


@app.cell
def _(sfe_med_geo):
    sfe_med_geo
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Saml stumperne
    """)
    return


@app.cell
def _(vurd_med_nøgletal):
    vurd_med_nøgletal.group_by(["BFEnummer"]).aggregate([('BFEnummer', 'count')])
    return


@app.cell
def _(gpd, sfe_med_geo, vurd_med_nøgletal):
    gdf = gpd.GeoDataFrame.from_arrow(sfe_med_geo).merge(vurd_med_nøgletal.to_pandas(), on="BFEnummer", how="inner")
    return (gdf,)


@app.cell
def _(gdf):
    gdf
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Tegn kort
    """)
    return


@app.cell
def _(gdf):
    mini_gdf = gdf[gdf["kommunekode"] == "0825"]
    return (mini_gdf,)


@app.cell
def _():
    import lonboard
    import lonboard.colormap
    import matplotlib.colors 
    import palettable.colorbrewer.sequential

    return lonboard, matplotlib, palettable


@app.cell
def _(lonboard, mini_gdf):
    # minigdf has two geometry columns, "poly" and "centroid"
    # we want to use "centroid" here
    _gdf = mini_gdf.copy().drop(columns=["poly"]).set_geometry("centroid")

    sp_layer = lonboard.ScatterplotLayer.from_geopandas(
        _gdf.to_crs(epsg=4326),  # lonboard expects WGS84
        get_fill_color=[0, 120, 255, 128],
        get_radius=10,
        radius_units="meters",
        radius_min_pixels=6,    # never smaller than 6px on screen, so we can see it when zoomed out
    )
    return (sp_layer,)


@app.cell
def _(lonboard, matplotlib, mini_gdf, np, palettable):
    # minigdf has two geometry columns, "poly" and "centroid"
    _gdfx = mini_gdf.copy().drop(columns=["centroid"]).set_geometry("poly")
    _gdfx = _gdfx.to_crs(epsg=4326)
    _gdfx = _gdfx.explode() # simplify polygons

    _heights = _gdfx["grundvaerdi_pr_kvm"].to_numpy()
    _heights = np.nan_to_num(_heights, nan=1.0, posinf=1.0, neginf=1.0).astype(np.float32)

    _normalizer = matplotlib.colors.LogNorm(1, _heights.max(), clip=True)
    _colors = lonboard.colormap.apply_continuous_cmap(
        _normalizer(_heights),
        palettable.colorbrewer.sequential.Oranges_9
    )

    p_layer = lonboard.PolygonLayer.from_geopandas(
        _gdfx,
        get_elevation=_gdfx["grundvaerdi_pr_kvm"],
        #elevation_scale=10,
        get_fill_color=_colors,
        get_line_color=_colors,
        extruded=True,
        filled=True,
        #stroked=False,
        wireframe=False,
    )
    return (p_layer,)


@app.cell
def _(lonboard, p_layer, sp_layer):
    m = lonboard.Map([p_layer, sp_layer, ])
    m.set_view_state(longitude=10.92610393923485, latitude=57.292346989384896, zoom=12, pitch=30.0, bearing=0.0)
    return (m,)


@app.cell
def _(m):
    m
    return


@app.cell
def _(m):
    m.view_state
    return


if __name__ == "__main__":
    app.run()
