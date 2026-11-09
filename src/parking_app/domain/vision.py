"""Vehicle detections and operator-reviewable gate events."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from parking_app.domain.enums import VehicleType
from parking_app.domain.video import SourceKind


class GateDirection(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


@dataclass(frozen=True)
class PlateDetection:
    """A license-plate region detected in normalized image coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    track_id: int | None = None


@dataclass(frozen=True)
class EventCandidate:
    """A plate track on a fixed-purpose gate camera, pending operator review."""

    id: str
    source_id: str
    source_name: str
    source_kind: SourceKind
    stream_id: str
    track_id: int
    direction: GateDirection
    vehicle_type: VehicleType
    confidence: float
    observed_at: datetime
    media_time_s: float | None
    image_data: bytes
    source_image_samples: tuple[bytes, ...] = ()
