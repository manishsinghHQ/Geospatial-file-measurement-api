"""Per-feature area / length calculation. Never raises: problems become a status + message."""
import math
from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

POLYGONS = {"Polygon", "MultiPolygon"}
LINES = {"LineString", "MultiLineString", "LinearRing"}
POINTS = {"Point", "MultiPoint"}

# Documented policy for non-measurable features:
#   NOT_APPLICABLE   points have no area/length -> measurement null
#   UNSUPPORTED      other geometry types (e.g. GeometryCollection) -> measurement null + explanation
#   EMPTY_GEOMETRY   null or empty geometry -> measurement null
#   INVALID_GEOMETRY self-intersections etc. -> NOT measured (we do not silently "repair" data)
#   FAILED           unexpected error for that one feature
#   OK               measured


@dataclass
class MeasurementResult:
    status: str
    type: str | None = None
    value: float | None = None
    unit: str | None = None
    message: str | None = None


def measure_geometry(original: BaseGeometry | None, projected: BaseGeometry | None) -> MeasurementResult:
    try:
        if original is None or original.is_empty:
            return MeasurementResult("EMPTY_GEOMETRY", message="Feature has no geometry")
        gtype = original.geom_type
        if gtype in POINTS:
            return MeasurementResult("NOT_APPLICABLE", message="Points have no area or length")
        if gtype not in POLYGONS | LINES:
            return MeasurementResult("UNSUPPORTED", message=f"Measurement is not supported for {gtype}")
        if not original.is_valid:
            return MeasurementResult("INVALID_GEOMETRY", message=explain_validity(original))

        if gtype in POLYGONS:
            kind, value, unit = "area", projected.area, "m²"
        else:
            kind, value, unit = "length", projected.length, "m"
        if not math.isfinite(value):
            return MeasurementResult("FAILED", message="Reprojection produced non-finite coordinates")
        return MeasurementResult("OK", kind, round(value, 4), unit)
    except Exception as exc:
        return MeasurementResult("FAILED", message=f"{type(exc).__name__}: {exc}")


def measure_features(originals, projected) -> list[MeasurementResult]:
    return [measure_geometry(o, p) for o, p in zip(originals, projected)]
