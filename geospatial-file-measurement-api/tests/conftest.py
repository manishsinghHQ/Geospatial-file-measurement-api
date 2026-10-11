import os
import tempfile
import zipfile
from pathlib import Path

# Isolated data dir + database; must be set before the app is imported.
_TMP = tempfile.mkdtemp(prefix="geo-tests-")
os.environ["DATA_DIR"] = _TMP
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"

import geopandas as gpd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from shapely.geometry import LineString, Polygon  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

SQUARE = Polygon([(77.59, 12.97), (77.60, 12.97), (77.60, 12.98), (77.59, 12.98)])  # ~1.2 km², Bengaluru
LINE = LineString([(77.59, 12.97), (77.60, 12.98)])
SAMPLES = Path(__file__).parent.parent / "samples"


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


def make_zip(gdf: gpd.GeoDataFrame, tmp_path: Path, name: str = "survey", drop: tuple[str, ...] = ()) -> Path:
    """Write gdf as a Shapefile and zip it, optionally leaving out components (e.g. drop=('.prj',))."""
    src = tmp_path / f"{name}_src"
    src.mkdir()
    gdf.to_file(src / f"{name}.shp", engine="pyogrio")
    zip_path = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in src.iterdir():
            if f.suffix.lower() not in drop:
                zf.write(f, f.name)
    return zip_path


def upload(client: TestClient, path: Path):
    with open(path, "rb") as fh:
        return client.post("/api/files/", files={"file": (path.name, fh, "application/octet-stream")})


@pytest.fixture
def parcels_zip(tmp_path):
    gdf = gpd.GeoDataFrame(
        {"name": ["plot-a", "plot-b"], "owner": ["Asha", None]},
        geometry=[SQUARE, Polygon([(77.61, 12.97), (77.62, 12.97), (77.62, 12.98)])], crs="EPSG:4326",
    )
    return make_zip(gdf, tmp_path, "parcels")
