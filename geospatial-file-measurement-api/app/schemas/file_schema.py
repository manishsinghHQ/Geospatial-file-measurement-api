from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: str | None
    measurement_crs: str | None
    status: str
    warnings: list[str] = []
    error_code: str | None = None
    error: str | None = None
    uploaded_at: datetime

    @field_validator("uploaded_at")
    @classmethod
    def _as_utc(cls, v: datetime) -> datetime:
        # SQLite returns naive datetimes; they are stored as UTC.
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


class FileListResponse(BaseModel):
    total: int
    items: list[FileResponse]


class MeasurementValue(BaseModel):
    type: str  # "area" | "length"
    value: float
    unit: str  # "m²" | "m"


class FeatureMeasurement(BaseModel):
    feature_id: int
    geometry_type: str | None
    properties: dict[str, Any]
    geometry: dict[str, Any] | None = None
    status: str  # OK | NOT_APPLICABLE | UNSUPPORTED | EMPTY_GEOMETRY | INVALID_GEOMETRY | FAILED
    message: str | None = None
    measurement: MeasurementValue | None = None


class Summary(BaseModel):
    total_area_sq_m: float
    total_length_m: float
    measured: int
    not_measured: int


class Pagination(BaseModel):
    limit: int
    offset: int
    total: int


class MeasurementResponse(BaseModel):
    file_id: str
    source_crs: str | None
    measurement_crs: str | None
    warnings: list[str]
    summary: Summary
    pagination: Pagination
    features: list[FeatureMeasurement]


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None
    id: str | None = None
