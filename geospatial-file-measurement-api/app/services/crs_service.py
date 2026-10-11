"""Identify the source CRS, choose a metre-based projected CRS, and reproject."""
import math

import geopandas as gpd
from pyproj import CRS

WGS84 = CRS.from_epsg(4326)


def crs_label(crs: CRS) -> str:
    """'EPSG:4326' when an EPSG code is known, otherwise the CRS name."""
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.name


def is_metric_projected(crs: CRS) -> bool:
    """True for projected CRSs whose axes are in metres (no reprojection needed)."""
    return crs.is_projected and all(ax.unit_name in ("metre", "meter") for ax in crs.axis_info)


def utm_zone(lon: float) -> int:
    return int(math.floor((lon + 180) / 6) % 60) + 1


def utm_crs_for_lonlat(lon: float, lat: float) -> CRS:
    """UTM zone for a lon/lat; polar stereographic where UTM is undefined (>=84°N, <=80°S)."""
    if lat >= 84:
        return CRS.from_epsg(3413)  # NSIDC Sea Ice Polar Stereographic North
    if lat <= -80:
        return CRS.from_epsg(3031)  # Antarctic Polar Stereographic
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + utm_zone(lon))


def _usable(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    return gdf[~(gdf.geometry.isna() | gdf.geometry.is_empty)]


def select_measurement_crs(gdf: gpd.GeoDataFrame) -> CRS | None:
    """
    Strategy (one measurement CRS per dataset, as reported in the API response):
      1. source CRS missing  -> error (never guessed; the file reader rejects such files)
      2. source already projected in metres -> use it as is
      3. otherwise -> UTM zone containing the centre of the dataset's extent
    Returns None when the dataset has no usable geometry.
    """
    if gdf.crs is None:
        raise ValueError("Source CRS is missing; cannot calculate reliable measurements")
    if is_metric_projected(gdf.crs):
        return gdf.crs
    usable = _usable(gdf)
    if usable.empty:
        return None
    minx, miny, maxx, maxy = usable.to_crs(WGS84).total_bounds
    return utm_crs_for_lonlat((minx + maxx) / 2, (miny + maxy) / 2)


def zone_warnings(gdf: gpd.GeoDataFrame, measurement_crs: CRS | None) -> list[str]:
    """Flag datasets whose extent spans several UTM zones (accuracy degrades away from the zone)."""
    if measurement_crs is None or measurement_crs == gdf.crs:
        return []
    usable = _usable(gdf)
    minx, _, maxx, _ = usable.to_crs(WGS84).total_bounds
    zones = range(utm_zone(minx), utm_zone(maxx) + 1)
    if len(zones) > 1:
        return [
            f"Dataset spans {len(zones)} UTM zones; all features were measured in "
            f"{crs_label(measurement_crs)}, so accuracy decreases far from that zone."
        ]
    return []


def to_measurement_crs(gdf: gpd.GeoDataFrame, measurement_crs: CRS | None) -> gpd.GeoSeries:
    """Return the geometries (2D) expressed in the measurement CRS."""
    geoms = gdf.geometry.force_2d()  # altitude (common in KML) plays no part in planar measures
    if measurement_crs is None or measurement_crs == gdf.crs:
        return geoms
    return geoms.to_crs(measurement_crs)
