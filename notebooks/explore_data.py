import marimo

__generated_with = "0.21.1"
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
    raw_table = pq.read_table("data/bbr_bygning-0825.parquet")
    print(raw_table.schema)
    return (raw_table,)


@app.cell
def _(raw_table):
    raw_table[:8]
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Ignorer historiske data, behold kun rækkerne med det nyeste `virkningFra` for hvert `id_lokalId`
    """)
    return


@app.cell
def _(pa, raw_table):
    def kun_nyeste_virkningsid(t: pa.Table) -> pa.Table:
        _with_ids = t.append_column("row_id", pa.array(range(t.num_rows), type=pa.int64()))

        _latest_row_ids = _with_ids.sort_by([("virkningFra", "ascending")]).group_by("id_lokalId", use_threads=False).aggregate([("row_id", "last"), ("virkningFra", "last")])["row_id_last"]

        _table = _with_ids.take(_latest_row_ids).sort_by("id_lokalId")
        return _table

    table = kun_nyeste_virkningsid(raw_table)
    return kun_nyeste_virkningsid, table


@app.cell
def _(pc, table):
    wkt_array = pc.struct_field(table.column("byg404Koordinat"), "wkt")
    crs_array = pc.struct_field(table.column("byg404Koordinat"), "crs")
    return crs_array, wkt_array


@app.cell
def _(wkt_array):
    wkt_array
    return


@app.cell
def _(crs_array, gpd, table, wkt_array):
    # Convert full table to pandas (drop the struct column first to avoid issues)
    df = table.drop(["byg404Koordinat"]).to_pandas()

    # Convert the wkt array to a pandas Series
    wkt_series = wkt_array.to_pandas()

    # Build geometries — from_wkt handles null values gracefully
    df["geometry"] = gpd.GeoSeries.from_wkt(wkt_series)

    # Determine CRS from the struct's crs field (it's an EPSG int, e.g. 25832 for ETRS89/UTM32N)
    epsg_code = crs_array.drop_null()[0].as_py()  # take first non-null value

    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=f"EPSG:{epsg_code}")
    return (gdf,)


@app.cell
def _(gdf):
    gdf
    return


@app.cell
def _(gdf):
    from lonboard import Map, ScatterplotLayer

    layer = ScatterplotLayer.from_geopandas(
        gdf.to_crs(epsg=4326),  # lonboard expects WGS84
        get_fill_color=[0, 120, 255, 128],
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

    ## BBR Ejendomsrelation
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


if __name__ == "__main__":
    app.run()
