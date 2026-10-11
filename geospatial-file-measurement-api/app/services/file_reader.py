"""Validate and read uploaded files (KML or zipped Shapefile) into a GeoDataFrame."""
import json
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from ..core.config import settings


class FileValidationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


def detect_file_type(filename: str) -> str:
    name = filename.lower()
    if name.endswith(".zip"):
        return "shapefile"
    if name.endswith(".kml"):
        return "kml"
    raise FileValidationError(
        "UNSUPPORTED_EXTENSION", "Unsupported file type. Upload a .zip (Shapefile) or .kml", 400
    )


def _safe_extract(zip_path: Path, dest: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if sum(i.file_size for i in zf.infolist()) > settings.max_unzipped_bytes:
                raise FileValidationError("ARCHIVE_TOO_LARGE", "Zip archive is too large when uncompressed")
            root = dest.resolve()
            for member in zf.infolist():
                if not (dest / member.filename).resolve().is_relative_to(root):  # zip-slip guard
                    raise FileValidationError("INVALID_ARCHIVE", "Zip contains an unsafe file path")
            zf.extractall(dest)
    except zipfile.BadZipFile as exc:
        raise FileValidationError("INVALID_ARCHIVE", "File is not a valid zip archive") from exc


def _locate_shapefile(root: Path) -> Path:
    shps = [p for p in root.rglob("*") if p.suffix.lower() == ".shp"
            and not p.name.startswith("._") and "__MACOSX" not in p.parts]
    if not shps:
        raise FileValidationError("MISSING_SHAPEFILE_COMPONENTS", "Archive does not contain a .shp file")
    if len(shps) > 1:
        raise FileValidationError("MULTIPLE_SHAPEFILES", f"Archive must contain one Shapefile (found {len(shps)})")
    shp = shps[0]
    siblings = {p.suffix.lower() for p in shp.parent.iterdir() if p.stem.lower() == shp.stem.lower()}
    missing = [ext for ext in (".shx", ".dbf") if ext not in siblings]
    if missing:
        raise FileValidationError(
            "MISSING_SHAPEFILE_COMPONENTS",
            f"Shapefile is missing required component(s): {', '.join(missing)}",
        )
    return shp


def _read_shapefile_zip(path: Path) -> gpd.GeoDataFrame:
    with tempfile.TemporaryDirectory() as tmp:
        _safe_extract(path, Path(tmp))
        return gpd.read_file(_locate_shapefile(Path(tmp)), engine="pyogrio")


# Presentation-only KML fields that carry no survey information.
KML_NOISE = {"tessellate", "extrude", "visibility", "drawOrder", "icon", "altitudeMode",
             "timestamp", "begin", "end", "snippet"}


def _read_kml(path: Path) -> gpd.GeoDataFrame:
    # Each KML Folder/Document is a GDAL layer; read them all.
    layers = [name for name, _ in pyogrio.list_layers(path)]
    frames = []
    for layer in layers:
        gdf = gpd.read_file(path, layer=layer, engine="pyogrio")
        if len(gdf):
            if len(layers) > 1:
                gdf["layer"] = layer
            frames.append(gdf)
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf = pd.concat(frames, ignore_index=True)
    empty_cols = [c for c in gdf.columns if c != gdf.geometry.name and (c in KML_NOISE or gdf[c].isna().all())]
    gdf = gdf.drop(columns=empty_cols)  # keep only real attributes (Name, description, ...)
    return gpd.GeoDataFrame(gdf, geometry=gdf.geometry.name, crs=frames[0].crs or "EPSG:4326")


def read_geodata(path: Path, file_type: str) -> gpd.GeoDataFrame:
    try:
        gdf = _read_shapefile_zip(path) if file_type == "shapefile" else _read_kml(path)
    except FileValidationError:
        raise
    except Exception as exc:  # corrupt or unreadable content -> controlled error, no traceback
        raise FileValidationError("UNREADABLE_FILE", f"Could not read geospatial data: {exc}") from exc
    if gdf.crs is None:
        raise FileValidationError(
            "CRS_MISSING",
            "The file has no coordinate reference system (a Shapefile needs its .prj). "
            "The CRS is not guessed because measurements would be unreliable.",
        )
    return gdf


def feature_records(gdf: gpd.GeoDataFrame) -> list[dict]:
    """GeoJSON features (geometry + properties); GeoDataFrame.to_json copes with NaN/dates/numpy."""
    return json.loads(gdf.to_json(drop_id=True, na="null"))["features"]
