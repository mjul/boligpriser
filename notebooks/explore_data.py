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

    return gpd, mo, pc, pq


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    We receive spatial points in a composite EPSG 25832 coordinate system from BBR.
    """)
    return


@app.cell
def _(pq, tablewkt):
    table = pq.read_table("data/bbr_bygning-0825.parquet")
    print(tablewkt.schema)
    return (table,)


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
    )
    m = Map(layer)
    return (m,)


@app.cell
def _(m):
    m
    return


if __name__ == "__main__":
    app.run()
