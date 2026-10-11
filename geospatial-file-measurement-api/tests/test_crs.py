"""CRS identification, selection and transformation, checked against trusted references."""
import geopandas as gpd
import pytest
from pyproj import CRS, Geod
from shapely.geometry import Point, Polygon

from app.services.crs_service import (
    crs_label, is_metric_projected, select_measurement_crs, to_measurement_crs, utm_crs_for_lonlat, zone_warnings,
)
from .conftest import SQUARE


def gdf_of(geom, crs="EPSG:4326"):
    return gpd.GeoDataFrame(geometry=[geom], crs=crs)


@pytest.mark.parametrize("lon,lat,epsg", [
    (77.59, 12.97, 32643), (-0.12, 51.5, 32630), (-74.0, 40.7, 32618),
    (151.2, -33.9, 32756), (10, 89, 3413), (0, -85, 3031),
])
def test_utm_zone_selection(lon, lat, epsg):
    assert utm_crs_for_lonlat(lon, lat).to_epsg() == epsg


def test_selection_agrees_with_geopandas_estimate_utm_crs():
    gdf = gdf_of(SQUARE)
    assert select_measurement_crs(gdf) == gdf.estimate_utm_crs()


def test_geographic_source_gets_metric_utm_crs():
    crs = select_measurement_crs(gdf_of(SQUARE))
    assert crs.to_epsg() == 32643 and is_metric_projected(crs)


def test_metric_projected_source_is_kept():
    gdf = gdf_of(Polygon([(0, 0), (10, 0), (10, 10)]), "EPSG:32643")
    assert select_measurement_crs(gdf) == gdf.crs


def test_non_metric_projected_source_is_reprojected_to_utm():
    gdf = gdf_of(SQUARE).to_crs("EPSG:2272")  # NAD83 / Pennsylvania South (US survey feet)
    assert not is_metric_projected(gdf.crs)
    assert is_metric_projected(select_measurement_crs(gdf))


def test_missing_crs_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="CRS is missing"):
        select_measurement_crs(gpd.GeoDataFrame(geometry=[SQUARE]))


def test_dataset_without_geometry_has_no_measurement_crs():
    assert select_measurement_crs(gpd.GeoDataFrame(geometry=[None], crs="EPSG:4326")) is None


def test_transformation_matches_geodesic_reference():
    gdf = gdf_of(SQUARE)
    projected = to_measurement_crs(gdf, select_measurement_crs(gdf))
    reference, _ = Geod(ellps="WGS84").geometry_area_perimeter(SQUARE)
    assert projected.iloc[0].area == pytest.approx(abs(reference), rel=0.002)
    assert projected.iloc[0].area > 1_000_000  # not the ~0.0001 "square degrees"


def test_transformation_is_round_trip_exact():
    gdf = gdf_of(Point(77.5946, 12.9716))
    back = to_measurement_crs(gdf, CRS.from_epsg(32643)).to_crs(4326)
    assert back.iloc[0].x == pytest.approx(77.5946, abs=1e-9)
    assert back.iloc[0].y == pytest.approx(12.9716, abs=1e-9)


def test_multi_zone_dataset_produces_warning():
    gdf = gpd.GeoDataFrame(geometry=[Point(70, 10), Point(80, 10)], crs="EPSG:4326")
    warnings = zone_warnings(gdf, select_measurement_crs(gdf))
    assert warnings and "UTM zones" in warnings[0]
    assert zone_warnings(gdf_of(SQUARE), select_measurement_crs(gdf_of(SQUARE))) == []


def test_crs_label():
    assert crs_label(CRS.from_epsg(4326)) == "EPSG:4326"
