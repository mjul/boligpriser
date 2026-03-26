import marimo

__generated_with = "0.21.1"
app = marimo.App(width="medium", layout_file="layouts/parquet_geo.slides.json")


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Geo Data in Parquet
    """)
    return


@app.cell
def _():
    import io
    import marimo as mo
    import pyarrow as pa
    import pyarrow.parquet as pq
    import geoarrow.pyarrow as ga
    import geoarrow.pyarrow.io as gaio
    import geopandas as gpd

    return ga, gaio, gpd, io, mo, pa


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    We receive spatial points in a composite EPSG 25832 coordinate system from BBR.
    """)
    return


@app.cell
def _():
    locs = [
        { "type": "Point", "crs": 25832, "dimension": "XY", "wkt": "POINT (616671.26 6351002)" },
        { "type": "Point", "crs": 25832, "dimension": "XY", "wkt": "POINT (616673.42 6351007.85)" },
    ]
    loc = locs[0]
    return loc, locs


@app.cell
def _(loc, pa):
    table = pa.Table.from_pylist([{"location": loc}])
    return (table,)


@app.cell
def _(table):
    table.schema
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Now this is not the right geospatial type for points. Let's convert it
    """)
    return


@app.cell
def _(ga, locs):
    _raw = ga.as_wkb(ga.array([x["wkt"] for x in locs])) # wkb does not attach a type
    geolocs = ga.with_crs(_raw, "EPSG:25832")   # so we set it manually
    return (geolocs,)


@app.cell
def _(geolocs):
    geolocs
    return


@app.cell
def _(geolocs, pa):
    geotable = pa.table({"geometry": geolocs})
    print(geotable.schema)
    return (geotable,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Let's just write it to memory, no need to mess with the file system
    """)
    return


@app.cell
def _(gaio, geotable, io):
    mem_file = io.BytesIO()

    gaio.write_geoparquet_table(
        geotable,
        mem_file,
        primary_geometry_column="geometry",
        geometry_columns={"geometry": {"crs": "EPSG:25832"}},
    )
    return (mem_file,)


@app.cell
def _(gpd, mem_file):
    mem_file.seek(0)
    gdf = gpd.read_parquet(mem_file)
    print(gdf.crs)      # Should be EPSG:25832, None means it was lost during write
    return (gdf,)


@app.cell
def _(gdf):
    gdf
    return


@app.cell
def _(gdf):
    # If the crs is missing, we can add it like this
    #    plot_gdf = gdf.set_crs(25832)
    plot_gdf= gdf
    print(plot_gdf.crs)
    return (plot_gdf,)


@app.cell
def _(plot_gdf):
    from lonboard import Map, ScatterplotLayer

    layer = ScatterplotLayer.from_geopandas(
        plot_gdf.to_crs(epsg=4326),  # lonboard expects WGS84
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
