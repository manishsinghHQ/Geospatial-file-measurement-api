from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..repositories.file_repository import FileRepository
from ..schemas.file_schema import (
    ErrorResponse, FeatureMeasurement, FileListResponse, FileResponse, MeasurementResponse,
    MeasurementValue, Pagination, Summary,
)
from ..services.file_processor import process_file
from ..services.file_reader import FileValidationError, detect_file_type

router = APIRouter(prefix="/api/files", tags=["files"])
CHUNK = 1024 * 1024


def get_repo(db: Session = Depends(get_db)) -> FileRepository:
    return FileRepository(db)


def _get_or_404(repo: FileRepository, file_id: str):
    record = repo.get(file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="File not found")
    return record


@router.post(
    "/", response_model=FileResponse, status_code=201,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def upload_file(file: UploadFile = File(...), repo: FileRepository = Depends(get_repo)):
    """Upload a `.kml` or a `.zip` containing a Shapefile; it is validated, processed and registered."""
    filename = Path(file.filename or "").name
    try:
        file_type = detect_file_type(filename)
    except FileValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    record = repo.create(filename, file_type)
    dest = settings.upload_dir / f"{record.id}{Path(filename).suffix.lower()}"
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="File too large")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        repo.discard()
        raise

    record = process_file(repo, record, dest)
    if record.status == "FAILED":
        return JSONResponse(
            status_code=422, content={"detail": record.error, "code": record.error_code, "id": record.id}
        )
    return record


@router.get("/", response_model=FileListResponse)
def list_files(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               repo: FileRepository = Depends(get_repo)):
    """List uploaded files, newest first (used by the web UI)."""
    items, total = repo.list_files(limit, offset)
    return FileListResponse(total=total, items=items)


@router.get("/{file_id}/", response_model=FileResponse, responses={404: {"model": ErrorResponse}})
def get_file(file_id: str, repo: FileRepository = Depends(get_repo)):
    return _get_or_404(repo, file_id)


@router.delete("/{file_id}/", status_code=204, responses={404: {"model": ErrorResponse}})
def delete_file(file_id: str, repo: FileRepository = Depends(get_repo)):
    """Delete a file's record, its stored measurements and the uploaded original."""
    record = _get_or_404(repo, file_id)
    repo.delete(record)
    for stored in settings.upload_dir.glob(f"{file_id}.*"):
        stored.unlink(missing_ok=True)
    return Response(status_code=204)


@router.get(
    "/{file_id}/measurements/", response_model=MeasurementResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def get_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    include_geometry: bool = Query(True),
    repo: FileRepository = Depends(get_repo),
):
    record = _get_or_404(repo, file_id)
    if record.status != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"File is not ready (status: {record.status})")

    s = repo.summary(file_id)
    features = [
        FeatureMeasurement(
            feature_id=f.feature_id, geometry_type=f.geometry_type, properties=f.properties,
            geometry=f.geometry if include_geometry else None, status=f.status, message=f.message,
            measurement=MeasurementValue(type=f.measurement_type, value=f.measurement_value, unit=f.measurement_unit)
            if f.status == "OK" else None,
        )
        for f in repo.get_features(file_id, limit, offset)
    ]
    return MeasurementResponse(
        file_id=record.id, source_crs=record.crs, measurement_crs=record.measurement_crs,
        warnings=record.warnings or [],
        summary=Summary(total_area_sq_m=s["total_area_sq_m"], total_length_m=s["total_length_m"],
                        measured=s["measured"], not_measured=record.feature_count - s["measured"]),
        pagination=Pagination(limit=limit, offset=offset, total=record.feature_count),
        features=features,
    )