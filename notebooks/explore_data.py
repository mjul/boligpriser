import marimo

__generated_with = "0.23.0"
app = marimo.App(
    width="medium",
    layout_file="layouts/explore_data.slides.json",
)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Explore Downloaded Parquet data
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

    return gpd, mo, pa, pc, pq


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## BBR Bygning
    Vi modtager placeringer i EPSG 25832 koordinater fra BBR.
    """)
    return


@app.cell
def _(pq):
    bbr_bygning_raw_table = pq.read_table("data/bbr_bygning-0825.parquet")
    print(bbr_bygning_raw_table.schema)
    return (bbr_bygning_raw_table,)


@app.cell
def _(bbr_bygning_raw_table):
    bbr_bygning_raw_table[:8]
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Ignorer historiske data, behold kun rækkerne med det nyeste `virkningFra` for hvert `id_lokalId`
    """)
    return


@app.cell
def _(bbr_bygning_raw_table, pa):
    def kun_nyeste_virkningsid(t: pa.Table) -> pa.Table:
        _with_ids = t.append_column("row_id", pa.array(range(t.num_rows), type=pa.int64()))

        _latest_row_ids = _with_ids.sort_by([("virkningFra", "ascending")]).group_by("id_lokalId", use_threads=False).aggregate([("row_id", "last"), ("virkningFra", "last")])["row_id_last"]

        _table = _with_ids.take(_latest_row_ids).sort_by("id_lokalId")
        return _table

    bbr_bygning_alle_table = kun_nyeste_virkningsid(bbr_bygning_raw_table)
    return bbr_bygning_alle_table, kun_nyeste_virkningsid


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Bygningernes anvendelser
    """)
    return


@app.cell
def _(bbr_bygning_alle_table):
    bbr_bygning_alle_table.group_by(["byg021BygningensAnvendelse"]).aggregate([("byg021BygningensAnvendelse", "count")])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Bemærk, at anvendelserne har typen `String`.

    Man kan se anvendelserne på kodelisten her: https://teknik.bbr.dk/kodelister/0/1/0/BygAnvendelse

    Her er nogle af de hyppigste koder. Mange af dem har vi ikke interesse i:

    - `110` `Stuehus til landbrugsejendom`
    - `120` `Fritliggende enfamiliehus`
    - `140` `Etagebolig-bygning, flerfamiliehus eller to-familiehus`
    - `510` `Sommerhus`
    - `910` `Garage`
    - `920` `Carport`
    - `930` `Udhus`
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Bygningernes beliggenhed
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Lad os forsimple lidt, så vi kun kigger på villaer (`120`), lejligheder (`140`) og sommerhuse (`510`).
    """)
    return


@app.cell
def _(bbr_bygning_alle_table, pa, pc):
    is_boliger = pc.is_in(
        pc.field("byg021BygningensAnvendelse"),
        value_set=pa.array(["120", "140", "510"])
    )

    bbr_bygning_boliger_table = bbr_bygning_alle_table.filter(is_boliger)
    return (bbr_bygning_boliger_table,)


@app.cell
def _(bbr_bygning_boliger_table, pc):
    wkt_array = pc.struct_field(bbr_bygning_boliger_table.column("byg404Koordinat"), "wkt")
    crs_array = pc.struct_field(bbr_bygning_boliger_table.column("byg404Koordinat"), "crs")
    return crs_array, wkt_array


@app.cell
def _(wkt_array):
    wkt_array
    return


@app.cell
def _(bbr_bygning_boliger_table, crs_array, gpd, wkt_array):
    # Convert full table to pandas (drop the struct column first to avoid issues)
    df = bbr_bygning_boliger_table.drop(["byg404Koordinat"]).to_pandas()

    # Convert the wkt array to a pandas Series
    wkt_series = wkt_array.to_pandas()

    # Build geometries — from_wkt handles null values gracefully
    df["geometry"] = gpd.GeoSeries.from_wkt(wkt_series)

    # Determine CRS from the struct's crs field (it's an EPSG int, e.g. 25832 for ETRS89/UTM32N)
    epsg_code = crs_array.drop_null()[0].as_py()  # take first non-null value

    bbr_bygning_gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=f"EPSG:{epsg_code}")
    return (bbr_bygning_gdf,)


@app.cell
def _(bbr_bygning_gdf):
    bbr_bygning_gdf
    return


@app.cell
def _(bbr_bygning_gdf):
    from lonboard import Map, ScatterplotLayer
    from lonboard.colormap import apply_categorical_cmap

    # Colour according to Anvendelse
    colour_map = {
        "120": [0, 120, 255, 180],
        "140": [255, 140, 0, 180],
        "510": [0, 180, 90, 180],
    }

    fill_colours = apply_categorical_cmap(bbr_bygning_gdf["byg021BygningensAnvendelse"], colour_map)

    layer = ScatterplotLayer.from_geopandas(
        bbr_bygning_gdf.to_crs(epsg=4326),  # lonboard expects WGS84
        #get_fill_color=[0, 120, 255, 128],
        get_fill_color=fill_colours,
        get_radius=10,
        radius_units="meters",
        radius_min_pixels=6,    # never smaller than 6px on screen, so we can see it when zoomed out
    )
    m = Map(layer)
    return (m,)


@app.cell
def _(m):
    m
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Nu har vi således styr på bygningerne og deres placering.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## BBR Ejendomsrelation

    Her kan vi se bygningens BFE-nummer. Dette er nøglen til at koble det til vurderingerne.
    """)
    return


@app.cell
def _(pq):
    raw_ejendomsrelation = pq.read_table("data/bbr_ejendomsrelation-0825.parquet")
    print(raw_ejendomsrelation.schema)
    return (raw_ejendomsrelation,)


@app.cell
def _(kun_nyeste_virkningsid, raw_ejendomsrelation):
    ejendomsrelation_table = kun_nyeste_virkningsid(raw_ejendomsrelation)
    return (ejendomsrelation_table,)


@app.cell
def _(ejendomsrelation_table):
    ejendomsrelation_table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Som vi kan se ovenfor er `vurderingsejendomsnummer` ikke udfyldt, så vi kan ikke bruge det til at knytte vurderingerne
    til bygningerne.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VUR Vurderingsejendom
    Vi kan i stedet forsøge os med vurderingsejendommene, objektet for ejendomsvurderingerne.
    """)
    return


@app.cell
def _(pq):
    raw_vurderingsejendom = pq.read_table("data/vur_vurderingsejendom.parquet")
    print(raw_vurderingsejendom.schema)
    print()
    print("Antal vurderingsejendomme: ", raw_vurderingsejendom.shape[0])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Der var ikke nogen krydsreference heller.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VUR Ejendomsvurdering
    """)
    return


@app.cell
def _(pq):
    raw_ejendomsvurdering = pq.read_table("data/vur_ejendomsvurdering.parquet")
    print(raw_ejendomsvurdering.schema)
    print()
    print("Antal ejendomsvurderinger: ", raw_ejendomsvurdering.shape[0])
    return (raw_ejendomsvurdering,)


@app.cell
def _(raw_ejendomsvurdering):
    raw_ejendomsvurdering
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Ejendomsvurderingerne har sikkert flere datapunkter pr. ejendom, så lad os prøve at gruppere og filtrere
    """)
    return


@app.cell
def _(raw_ejendomsvurdering):
    raw_ejendomsvurdering.sort_by("aendringDato").group_by("fkVurderingsejendomID", use_threads=False).aggregate([("aendringDato", "count"), ("fkVurderingsejendomID", "last")]).sort_by("aendringDato_count")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VUR BFE krydsreference
    Her er endelig en nøgle til at krydse de forskellige datasæt:
    """)
    return


@app.cell
def _(pq):
    raw_bfekryds = pq.read_table("data/vur_bfekrydsreference.parquet")
    print(raw_bfekryds.schema)
    return (raw_bfekryds,)


@app.cell
def _(raw_bfekryds):
    raw_bfekryds.group_by(["BFEnummer"], use_threads=False).aggregate([("BFEnummer", "count")]).sort_by([("BFEnummer_count", "descending")])
    return


@app.cell
def _(pc, raw_bfekryds):
    pc.mean(raw_bfekryds.group_by(["BFEnummer"], use_threads=False).aggregate([("BFEnummer", "count")])["BFEnummer_count"])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Vurderinger med placeringer
    """)
    return


@app.cell
def _(pc, raw_ejendomsvurdering):
    _bolig = pc.field("benyttelseKode") == '01' 
    _ejerlejl_bolig = pc.field("benyttelseKode") == '21' 
    bolig_vurd_uden_bfe = raw_ejendomsvurdering.filter(_bolig | _ejerlejl_bolig).select(["id", "ejendomvaerdiBeloeb", "grundvaerdiBeloeb", "benyttelseKode", "fkVurderingsejendomID"])
    return (bolig_vurd_uden_bfe,)


@app.cell
def _(bolig_vurd_uden_bfe, raw_bfekryds):
    bolig_vurd_med_bfe = bolig_vurd_uden_bfe.join(raw_bfekryds, keys=["fkVurderingsejendomID"], right_keys=["fkEjendomsvurderingID"], join_type="inner").select(["id", "ejendomvaerdiBeloeb", "grundvaerdiBeloeb", "benyttelseKode", "fkVurderingsejendomID", "BFEnummer"])
    bolig_vurd_med_bfe
    return (bolig_vurd_med_bfe,)


@app.cell
def _(ejendomsrelation_table):
    ejendomsrelation_table.schema
    return


@app.cell
def _(bbr_bygning_boliger_table):
    bbr_bygning_boliger_table.schema
    return


@app.cell
def _(bbr_bygning_boliger_table, bolig_vurd_med_bfe, ejendomsrelation_table):
    bygning_vurd = bolig_vurd_med_bfe.join(ejendomsrelation_table.drop_columns(["vurderingsejendomsnummer","row_id", "virkningFra", "virkningTil"]), keys=["BFEnummer"], right_keys=["bfeNummer"]).join(bbr_bygning_boliger_table.drop_columns(["byg404Koordinat", "row_id", "virkningFra", "virkningTil", "kommunekode"]).rename_columns({"status": "bbr_status"}), keys=["id_lokalId"], right_keys=["id_lokalId"], join_type="inner")
    bygning_vurd.schema
    return (bygning_vurd,)


@app.cell
def _(bygning_vurd):
    bygning_vurd
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Der lader således ikke til at være nogen på Læsø.
    """)
    return


@app.cell
def _(bbr_bygning_boliger_table, pc):
    print("Kommunekoder for bygninger i vores datasæt:", pc.unique(bbr_bygning_boliger_table.column("kommunekode")))
    return


@app.cell
def _(bolig_vurd_med_bfe, ejendomsrelation_table, pc):
    _t = bolig_vurd_med_bfe.join(ejendomsrelation_table.drop_columns(["vurderingsejendomsnummer","row_id", "virkningFra", "virkningTil"]), keys=["BFEnummer"], right_keys=["bfeNummer"]).column("kommunekode")
    print("Kommunekoder for VUR ejendomsvurderinger i vores datasæt:", pc.count(_t), pc.unique(_t))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Det var mærkeligt. Lad os se på kildedata:
    """)
    return


@app.cell
def _(ejendomsrelation_table, pc):
    pc.unique(ejendomsrelation_table.column("kommunekode"))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
 
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## VUR Grundværdispecifikationer
    """)
    return


@app.cell
def _(pq):
    gvspec_table = pq.read_table("data/vur_grundvaerdispecifikation.parquet")
    return (gvspec_table,)


@app.cell
def _(bolig_vurd_med_bfe, gvspec_table):
    print(gvspec_table.schema)
    print()
    print(bolig_vurd_med_bfe.schema)
    return


@app.cell
def _(bolig_vurd_med_bfe, gvspec_table):
    bolig_vurd_med_bfe.join(gvspec_table, keys=["fkVurderingsejendomID"], right_keys=["fkEjendomsvurderingID"], join_type="inner")
    return


if __name__ == "__main__":
    app.run()
