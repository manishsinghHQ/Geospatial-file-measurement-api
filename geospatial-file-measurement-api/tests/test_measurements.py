"""Measurement calculations (unit) and the measurements endpoint (integration)."""
import geopandas as gpd
import pytest
from pyproj import CRS, Geod
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon

from app.services.crs_service import select_measurement_crs, to_measurement_crs
from app.services.measurement_service import measure_features
from .conftest import LINE, SAMPLES, SQUARE, make_zip, upload

GEOD = Geod(ellps="WGS84")


def measure(*geoms, crs="EPSG:4326"):
    gdf = gpd.GeoDataFrame(geometry=list(geoms), crs=crs)
    return measure_features(gdf.geometry, to_measurement_crs(gdf, select_measurement_crs(gdf)))


def test_polygon_area_in_square_metres():
    r = measure(SQUARE)[0]
    assert (r.status, r.type, r.unit) == ("OK", "area", "m²")
    assert r.value == pytest.approx(abs(GEOD.geometry_area_perimeter(SQUARE)[0]), rel=0.002)


def test_linestring_length_in_metres():
    r = measure(LINE)[0]
    assert (r.status, r.type, r.unit) == ("OK", "length", "m")
    assert r.value == pytest.approx(GEOD.geometry_length(LINE), rel=0.002)


def test_known_projected_polygon_exact_area():
    r = measure(Polygon([(0, 0), (100, 0), (100, 50), (0, 50)]), crs="EPSG:32643")[0]
    assert r.value == pytest.approx(5000.0)


def test_multi_geometries_supported():
    mp = MultiPolygon([Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]), Polygon([(20, 0), (30, 0), (30, 10), (20, 10)])])
    ml = MultiLineString([[(0, 0), (3, 4)], [(10, 10), (13, 14)]])
    a, b = measure(mp, ml, crs="EPSG:32643")
    assert a.value == pytest.approx(200.0) and b.value == pytest.approx(10.0)


def test_point_has_no_measurement():
    r = measure(Point(77.59, 12.97))[0]
    assert r.status == "NOT_APPLICABLE" and r.value is None and r.type is None


def test_unsupported_geometry_is_explained_not_raised():
    r = measure(GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])]))[0]
    assert r.status == "UNSUPPORTED" and "GeometryCollection" in r.message


def test_empty_and_null_geometry():
    gdf = gpd.GeoDataFrame(geometry=[None, Polygon(), SQUARE], crs="EPSG:4326")
    results = measure_features(gdf.geometry, to_measurement_crs(gdf, select_measurement_crs(gdf)))
    assert [r.status for r in results] == ["EMPTY_GEOMETRY", "EMPTY_GEOMETRY", "OK"]


def test_invalid_geometry_is_reported_not_measured():
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])
    r = measure(bowtie, crs="EPSG:32643")[0]
    assert r.status == "INVALID_GEOMETRY" and "Self-intersection" in r.message and r.value is None


def test_one_bad_feature_does_not_stop_the_rest():
    results = measure(Point(1, 1), SQUARE, GeometryCollection([Point(0, 0)]), LINE)
    assert [r.status for r in results] == ["NOT_APPLICABLE", "OK", "UNSUPPORTED", "OK"]


def test_z_values_are_ignored():
    sq3d = Polygon([(77.59, 12.97, 900), (77.60, 12.97, 900), (77.60, 12.98, 900), (77.59, 12.98, 900)])
    assert measure(sq3d)[0].value == pytest.approx(measure(SQUARE)[0].value)


# ---- endpoint ---------------------------------------------------------------------

def test_measurements_endpoint_format(client, parcels_zip):
    file_id = upload(client, parcels_zip).json()["id"]
    r = client.get(f"/api/files/{file_id}/measurements/")
    assert r.status_code == 200
    data = r.json()
    assert data["file_id"] == file_id
    assert data["source_crs"] == "EPSG:4326" and data["measurement_crs"] == "EPSG:32643"
    first = data["features"][0]
    assert first["feature_id"] == 0 and first["geometry_type"] == "Polygon"
    assert first["properties"] == {"name": "plot-a", "owner": "Asha"}
    assert first["geometry"]["type"] == "Polygon"
    assert first["measurement"]["type"] == "area" and first["measurement"]["unit"] == "m²"
    assert first["measurement"]["value"] == pytest.approx(abs(GEOD.geometry_area_perimeter(SQUARE)[0]), rel=0.002)
    assert data["features"][1]["properties"]["owner"] is None
    assert data["summary"]["measured"] == 2 and data["summary"]["not_measured"] == 0


def test_kml_measurements_with_mixed_geometries(client):
    file_id = upload(client, SAMPLES / "survey.kml").json()["id"]
    feats = {f["properties"]["Name"]: f for f in client.get(f"/api/files/{file_id}/measurements/").json()["features"]}
    assert feats["Park"]["measurement"]["type"] == "area"
    assert feats["Road"]["measurement"]["unit"] == "m"
    assert feats["Gate"]["measurement"] is None and feats["Gate"]["status"] == "NOT_APPLICABLE"
    assert feats["Combo"]["measurement"] is None and feats["Combo"]["status"] == "UNSUPPORTED"


def test_projected_shapefile_is_measured_in_its_own_crs(client):
    file_id = upload(client, SAMPLES / "plots_utm43n.zip").json()["id"]
    d = client.get(f"/api/files/{file_id}/measurements/").json()
    assert d["source_crs"] == d["measurement_crs"] == "EPSG:32643"
    assert d["features"][0]["measurement"]["value"] == pytest.approx(5000.0)


def test_pagination_and_geometry_toggle(client, tmp_path):
    gdf = gpd.GeoDataFrame({"n": range(5)}, geometry=[Point(77 + i / 100, 12) for i in range(5)], crs="EPSG:4326")
    file_id = upload(client, make_zip(gdf, tmp_path)).json()["id"]
    d = client.get(f"/api/files/{file_id}/measurements/", params={"limit": 2, "offset": 3, "include_geometry": False}).json()
    assert [f["feature_id"] for f in d["features"]] == [3, 4]
    assert d["pagination"] == {"limit": 2, "offset": 3, "total": 5}
    assert d["features"][0]["geometry"] is None


def test_measurements_for_failed_file_is_409(client, tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[SQUARE], crs="EPSG:4326")
    failed_id = upload(client, make_zip(gdf, tmp_path, drop=(".prj",))).json()["id"]
    assert client.get(f"/api/files/{failed_id}/measurements/").status_code == 409


def test_measurements_unknown_id_404(client):
    assert client.get("/api/files/nope/measurements/").status_code == 404
