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

    import lonboard as lb
    import lonboard.colormap as lbc
    import matplotlib.colors
    import palettable.colorbrewer.sequential

    return gpd, lb, matplotlib, mo, np, palettable, pc, pq


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


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Globale maksima til farvekodning af ejendomme, så farverne er ensartede over hele landet.
    """)
    return


@app.cell
def _(gdf):
    max_ejendomsvaerdi_pr_kvm = gdf['ejendomsvaerdi_pr_kvm'].max()
    max_grundvaerdi_pr_kvm = gdf['grundvaerdi_pr_kvm'].max()
    return (max_grundvaerdi_pr_kvm,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Afgræns til mindre område for overskuelighed
    """)
    return


@app.cell
def _(gdf):
    # 0155: Dragør
    # 0461: Odense
    # 0740: Silkeborg
    # 0825: Læsø
    mini_gdf = gdf[gdf["kommunekode"] == "0155"]

    assert(mini_gdf.shape[0] > 0)
    return (mini_gdf,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Farvelægning
    """)
    return


@app.cell
def _(lb, matplotlib, max_grundvaerdi_pr_kvm, mini_gdf, np, palettable):
    #heights, heights_max = (mini_gdf["ejendomsvaerdi_pr_kvm"].to_numpy(), max_ejendomsvaerdi_pr_kvm)
    heights, heights_max = (mini_gdf["grundvaerdi_pr_kvm"].to_numpy(), max_grundvaerdi_pr_kvm)

    heights = np.nan_to_num(heights, nan=1.0, posinf=1.0, neginf=1.0).astype(np.float32)

    _normalizer = matplotlib.colors.LogNorm(1, heights_max, clip=True)
    colours = lb.colormap.apply_continuous_cmap(
        _normalizer(heights),
        # .mpl_colormap is continuous
        #palettable.colorbrewer.sequential.Oranges_9.mpl_colormap
        #palettable.colorbrewer.sequential.Blues_8.mpl_colormap
        #palettable.cmocean.sequential.Thermal_10.mpl_colormap
        palettable.colorbrewer.diverging.RdYlGn_10.mpl_colormap # red-yellow-green
    )

    # percentiles in 10% bands
    _binned = np.percentile(heights, np.arange(0, 101, 10))
    _bin_cmap = matplotlib.colors.ListedColormap(palettable.colorbrewer.diverging.RdYlGn_10.mpl_colors)
    _bin_norm = matplotlib.colors.BoundaryNorm(_binned, ncolors=_bin_cmap.N, clip=True)
    binned_colours = lb.colormap.apply_continuous_cmap(
        _bin_norm(heights), 
        _bin_cmap)
    return binned_colours, colours, heights


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Klargør lag
    """)
    return


@app.cell
def _(binned_colours, lb, mini_gdf, np):
    # minigdf has two geometry columns, "poly" and "centroid"
    # we want to use "centroid" here
    _gdf = mini_gdf.drop(columns=["poly"]).set_geometry("centroid")

    # Farvelæg med alpha 0.5 (128 i uint8)
    _med_alpha = np.hstack([binned_colours, 128*np.ones((binned_colours.shape[0],1),dtype=np.uint8)])

    sp_layer = lb.ScatterplotLayer.from_geopandas(
        _gdf.to_crs(epsg=4326),  # lonboard expects WGS84
        get_fill_color= _med_alpha, # [0, 120, 255, 128],
        get_radius=10,
        radius_units="meters",
        radius_min_pixels=3,    # never smaller than 3px on screen, so we can see it when zoomed out
        opacity = 0.8,
    )
    return (sp_layer,)


@app.cell
def _(binned_colours, colours, heights, lb, mini_gdf):
    # minigdf has two geometry columns, "poly" and "centroid"
    _gdfx = mini_gdf.drop(columns=["centroid"]).set_geometry("poly")
    _gdfx = _gdfx.to_crs(epsg=4326)
    # we can _gdfx.explode() to simplify polygons but it looks like we are ok without

    p3d_layer = lb.PolygonLayer.from_geopandas(
        _gdfx,
        get_elevation=heights,
        elevation_scale = 0.01,
        get_fill_color=binned_colours,
        get_line_color=colours,
        extruded=True,
        filled=True,
        #stroked=False,
        wireframe=False,
        opacity = 0.8,
    )

    p2d_layer = lb.SolidPolygonLayer.from_geopandas(
        _gdfx,
        get_fill_color=binned_colours,
        extruded = False,
        filled = True,
        opacity = 0.8,
    )
    return p2d_layer, p3d_layer


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Vis kort over grundværdier pr. kvadratmeter
    """)
    return


@app.cell
def _(lb, p2d_layer, p3d_layer, sp_layer):
    m = lb.Map([sp_layer, p3d_layer, p2d_layer])
    return (m,)


@app.cell
def _(m):
    # Læsø
    #m.set_view_state(longitude=10.92610393923485, latitude=57.292346989384896, zoom=12, pitch=30.0, bearing=0.0)

    # Dragør
    m.set_view_state(longitude=12.653578731608945, latitude=55.59078681012855, zoom=12.777960506764058, pitch=30, bearing=0)

    m
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    NB! Lonboard bruger `deck.gl`, der åbenbart ikke opdaterer 3D-geometrierne hvis vi genberegner cellerne ovenfor. Hvis kortet kun viser scatter-plot laget kan man løse det ved at genindlæse siden i browseren ("reload").
    """)
    return


@app.cell
def _(m):
    print(m.view_state)
    return


if __name__ == "__main__":
    app.run()
