"""Upload, validation, error handling, file information and persistence."""
import zipfile

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.repositories.file_repository import FileRepository
from .conftest import SAMPLES, SQUARE, make_zip, upload


def test_health_and_ui(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_upload_kml(client):
    r = upload(client, SAMPLES / "survey.kml")
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "survey.kml" and body["file_type"] == "kml"
    assert body["feature_count"] == 4 and body["crs"] == "EPSG:4326" and body["status"] == "COMPLETED"
    assert body["measurement_crs"] == "EPSG:32643" and body["uploaded_at"]


def test_upload_shapefile_zip(client, parcels_zip):
    r = upload(client, parcels_zip)
    assert r.status_code == 201
    assert r.json()["feature_count"] == 2 and r.json()["file_type"] == "shapefile"


def test_get_file_information(client, parcels_zip):
    file_id = upload(client, parcels_zip).json()["id"]
    r = client.get(f"/api/files/{file_id}/")
    assert r.status_code == 200
    assert r.json()["id"] == file_id and r.json()["status"] == "COMPLETED"


def test_timestamps_are_timezone_aware_after_reload(client, parcels_zip):
    file_id = upload(client, parcels_zip).json()["id"]
    engine.dispose()
    assert client.get(f"/api/files/{file_id}/").json()["uploaded_at"].endswith("Z")


def test_kml_properties_exclude_styling_noise(client):
    file_id = upload(client, SAMPLES / "survey.kml").json()["id"]
    props = client.get(f"/api/files/{file_id}/measurements/").json()["features"][0]["properties"]
    assert set(props) == {"Name", "description"}


def test_list_files(client, parcels_zip):
    upload(client, parcels_zip)
    upload(client, SAMPLES / "survey.kml")
    d = client.get("/api/files/").json()
    assert d["total"] == 2 and d["items"][0]["filename"] == "survey.kml"  # newest first


# ---- validation / error handling ---------------------------------------------------

def test_unsupported_extension_400(client, tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hello")
    r = upload(client, p)
    assert r.status_code == 400 and "Unsupported" in r.json()["detail"]
    assert client.get("/api/files/").json()["total"] == 0  # rejected before registering


def test_corrupt_zip_is_controlled_error(client, tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"this is not a zip")
    r = upload(client, p)
    assert r.status_code == 422 and r.json()["code"] == "INVALID_ARCHIVE"
    assert "Traceback" not in r.text


def test_zip_without_shp(client, tmp_path):
    p = tmp_path / "empty.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("readme.txt", "nothing here")
    r = upload(client, p)
    assert r.status_code == 422 and r.json()["code"] == "MISSING_SHAPEFILE_COMPONENTS"


@pytest.mark.parametrize("missing", [".shx", ".dbf"])
def test_missing_required_shapefile_components(client, tmp_path, missing):
    r = upload(client, make_zip(gpd.GeoDataFrame(geometry=[SQUARE], crs="EPSG:4326"), tmp_path, drop=(missing,)))
    assert r.status_code == 422
    assert r.json()["code"] == "MISSING_SHAPEFILE_COMPONENTS" and missing in r.json()["detail"]


def test_missing_crs_is_flagged_not_guessed(client, tmp_path):
    r = upload(client, make_zip(gpd.GeoDataFrame(geometry=[SQUARE], crs="EPSG:4326"), tmp_path, drop=(".prj",)))
    assert r.status_code == 422 and r.json()["code"] == "CRS_MISSING"
    info = client.get(f"/api/files/{r.json()['id']}/").json()  # failure is recorded and queryable
    assert info["status"] == "FAILED" and info["error_code"] == "CRS_MISSING"


def test_zip_slip_rejected(client, tmp_path):
    p = tmp_path / "evil.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("../evil.shp", "x")
    r = upload(client, p)
    assert r.status_code == 422 and "unsafe" in r.json()["detail"]


def test_invalid_kml_is_controlled_error(client, tmp_path):
    p = tmp_path / "broken.kml"
    p.write_text("<kml><not-closed>")
    r = upload(client, p)
    assert r.status_code == 422 and r.json()["code"] == "UNREADABLE_FILE"


def test_upload_size_limit(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 10)
    p = tmp_path / "big.kml"
    p.write_text("x" * 100)
    assert upload(client, p).status_code == 413
    assert client.get("/api/files/").json()["total"] == 0


def test_unknown_file_id_404(client):
    assert client.get("/api/files/does-not-exist/").status_code == 404


# ---- persistence -------------------------------------------------------------------

def test_data_survives_application_restart(client, parcels_zip):
    file_id = upload(client, parcels_zip).json()["id"]
    engine.dispose()  # drop every pooled connection, as a process restart would
    with SessionLocal() as db:  # brand-new session straight from the SQLite file
        repo = FileRepository(db)
        record = repo.get(file_id)
        assert record.status == "COMPLETED" and record.feature_count == 2
        assert len(repo.get_features(file_id, 10, 0)) == 2
    with TestClient(__import__("app.main", fromlist=["app"]).app) as fresh:  # fresh client instance
        assert fresh.get(f"/api/files/{file_id}/measurements/").status_code == 200
