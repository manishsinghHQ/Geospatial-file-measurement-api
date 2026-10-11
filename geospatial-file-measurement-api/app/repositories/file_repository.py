"""Persistence for file metadata and processed per-feature results."""
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import FeatureModel, FileModel


class FileRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, filename: str, file_type: str) -> FileModel:
        record = FileModel(filename=filename, file_type=file_type)
        self.db.add(record)
        self.db.flush()
        return record

    def save_result(
        self, record: FileModel, *, crs: str | None, measurement_crs: str | None,
        warnings: list[str], features: list[FeatureModel],
    ) -> FileModel:
        for f in features:
            f.file_id = record.id
        self.db.add_all(features)  # one transaction, bulk insert
        record.crs, record.measurement_crs = crs, measurement_crs
        record.warnings = warnings
        record.feature_count = len(features)
        record.status = "COMPLETED"
        self.db.commit()
        return record

    def mark_failed(self, record: FileModel, code: str, message: str) -> FileModel:
        self.db.rollback()
        record.status, record.error_code, record.error = "FAILED", code, message
        self.db.add(record)
        self.db.commit()
        return record

    def delete(self, record: FileModel) -> None:
        # Bulk-delete the features first: far cheaper than loading thousands of ORM objects.
        self.db.execute(delete(FeatureModel).where(FeatureModel.file_id == record.id))
        self.db.delete(record)
        self.db.commit()

    def discard(self) -> None:
        self.db.rollback()

    def get(self, file_id: str) -> FileModel | None:
        return self.db.get(FileModel, file_id)

    def list_files(self, limit: int, offset: int) -> tuple[list[FileModel], int]:
        total = self.db.scalar(select(func.count()).select_from(FileModel)) or 0
        rows = self.db.scalars(
            select(FileModel).order_by(FileModel.uploaded_at.desc()).limit(limit).offset(offset)
        ).all()
        return list(rows), total

    def get_features(self, file_id: str, limit: int, offset: int) -> list[FeatureModel]:
        return list(self.db.scalars(
            select(FeatureModel).where(FeatureModel.file_id == file_id)
            .order_by(FeatureModel.feature_id).limit(limit).offset(offset)
        ))

    def summary(self, file_id: str) -> dict:
        def total(kind: str) -> float:
            return self.db.scalar(
                select(func.coalesce(func.sum(FeatureModel.measurement_value), 0.0)).where(
                    FeatureModel.file_id == file_id, FeatureModel.measurement_type == kind
                )
            ) or 0.0

        measured = self.db.scalar(
            select(func.count()).where(FeatureModel.file_id == file_id, FeatureModel.status == "OK")
        ) or 0
        return {"total_area_sq_m": total("area"), "total_length_m": total("length"), "measured": measured}