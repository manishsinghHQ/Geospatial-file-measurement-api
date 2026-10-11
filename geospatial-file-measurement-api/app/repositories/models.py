import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FileModel(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))  # shapefile | kml
    status: Mapped[str] = mapped_column(String(16), default="PROCESSING")  # PROCESSING | COMPLETED | FAILED
    crs: Mapped[str | None] = mapped_column(String(64), nullable=True)  # source CRS
    measurement_crs: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    features: Mapped[list["FeatureModel"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", order_by="FeatureModel.feature_id"
    )


class FeatureModel(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    feature_id: Mapped[int] = mapped_column(Integer)  # index of the feature within the file
    geometry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GeoJSON in the source CRS
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    measurement_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # area | length
    measurement_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)

    file: Mapped[FileModel] = relationship(back_populates="features")
