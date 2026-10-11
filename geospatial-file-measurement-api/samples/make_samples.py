"""Regenerates the sample files in this folder:  python samples/make_samples.py"""
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Polygon

OUT = Path(__file__).parent

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>Park</name><description>City park</description>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>
      77.59,12.97,0 77.60,12.97,0 77.60,12.98,0 77.59,12.98,0 77.59,12.97,0
    </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark><name>Road</name>
    <LineString><coordinates>77.59,12.97,0 77.60,12.98,0</coordinates></LineString></Placemark>
  <Placemark><name>Gate</name><Point><coordinates>77.595,12.975,0</coordinates></Point></Placemark>
  <Placemark><name>Combo</name><MultiGeometry>
    <Point><coordinates>77.1,12.1,0</coordinates></Point>
    <LineString><coordinates>77.1,12.1,0 77.2,12.2,0</coordinates></LineString>
  </MultiGeometry></Placemark>
</Document></kml>
"""


def zip_shapefile(gdf: gpd.GeoDataFrame, name: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        gdf.to_file(Path(tmp) / f"{name}.shp", engine="pyogrio")
        with zipfile.ZipFile(OUT / f"{name}.zip", "w") as zf:
            for f in sorted(Path(tmp).iterdir()):
                zf.write(f, f.name)


if __name__ == "__main__":
    (OUT / "survey.kml").write_text(KML, encoding="utf-8")
    zip_shapefile(gpd.GeoDataFrame(
        {"name": ["Plot-1", "Plot-2"], "owner": ["Asha", "Ravi"]},
        geometry=[Polygon([(77.59, 12.97), (77.60, 12.97), (77.60, 12.98), (77.59, 12.98)]),
                  Polygon([(77.61, 12.97), (77.62, 12.97), (77.62, 12.98)])],
        crs="EPSG:4326"), "parcels_wgs84")
    zip_shapefile(gpd.GeoDataFrame(
        {"name": ["Road-1"]}, geometry=[LineString([(77.59, 12.97), (77.60, 12.98)])], crs="EPSG:4326"),
        "roads_wgs84")
    zip_shapefile(gpd.GeoDataFrame(
        {"name": ["Plot-U"]},
        geometry=[Polygon([(500000, 1435000), (500100, 1435000), (500100, 1435050), (500000, 1435050)])],
        crs="EPSG:32643"), "plots_utm43n")
    print("samples written to", OUT)
