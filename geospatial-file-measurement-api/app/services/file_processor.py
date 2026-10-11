"""Orchestration: read -> choose CRS -> reproject -> measure -> persist."""
import logging
from pathlib import Path

from ..repositories.file_repository import FileRepository
from ..repositories.models import FeatureModel, FileModel
from .crs_service import crs_label, select_measurement_crs, to_measurement_crs, zone_warnings
from .file_reader import FileValidationError, feature_records, read_geodata
from .measurement_service import measure_features

log = logging.getLogger(__name__)


def process_file(repo: FileRepository, record: FileModel, path: Path) -> FileModel:
    try:
        gdf = read_geodata(path, record.file_type)
        measurement_crs = select_measurement_crs(gdf)
        projected = to_measurement_crs(gdf, measurement_crs)
        results = measure_features(gdf.geometry, projected)
        records = feature_records(gdf)

        features = [
            FeatureModel(
                feature_id=i,
                geometry_type=geom.geom_type if geom is not None else None,
                geometry=rec.get("geometry"),
                properties=rec.get("properties") or {},
                status=r.status, message=r.message,
                measurement_type=r.type, measurement_value=r.value, measurement_unit=r.unit,
            )
            for i, (geom, rec, r) in enumerate(zip(gdf.geometry, records, results))
        ]
        return repo.save_result(
            record, crs=crs_label(gdf.crs),
            measurement_crs=crs_label(measurement_crs) if measurement_crs else None,
            warnings=zone_warnings(gdf, measurement_crs), features=features,
        )
    except FileValidationError as exc:
        return repo.mark_failed(record, exc.code, exc.message)
    except Exception as exc:  # last-resort guard: report, never leak a traceback
        log.exception("Unexpected error while processing %s", record.id)
        return repo.mark_failed(record, "PROCESSING_ERROR", f"Unexpected error: {type(exc).__name__}")
