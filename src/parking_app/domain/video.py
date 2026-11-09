"""Source contracts for M02; independent of OpenCV and Qt."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from parking_app.domain.exceptions import ValidationError

if TYPE_CHECKING:
    from parking_app.domain.vision import PlateDetection


class SourceKind(StrEnum):
    LIVE = "LIVE"
    MP4 = "MP4"


class SourcePurpose(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    PARKING = "PARKING"


class StreamStatus(StrEnum):
    CONNECTING = "Đang kết nối"
    PLAYING = "Đang phát"
    PAUSED = "Tạm dừng"
    DISCONNECTED = "Mất kết nối — không có hình hiện tại"
    EOF = "Đã hết video"
    ERROR = "Lỗi nguồn hình"
    STOPPED = "Đã dừng"


class ParkingSpaceStatus(StrEnum):
    FREE = "Trống"
    OCCUPIED = "Có xe"
    UNKNOWN = "Không xác định"


@dataclass(frozen=True)
class ParkingSpace:
    """A named parking polygon in normalized camera coordinates."""

    code: str
    points: tuple[tuple[float, float], ...]

    def validate(self) -> None:
        if not self.code.strip() or self.code != self.code.strip() or len(self.code) > 30:
            raise ValidationError("Mã ô đỗ phải có từ 1 đến 30 ký tự.")
        if len(self.points) < 3:
            raise ValidationError("Vùng ô đỗ cần ít nhất 3 đỉnh.")
        if any(len(point) != 2 for point in self.points):
            raise ValidationError("Mỗi đỉnh polygon phải có đúng hai tọa độ.")
        if any(
            not all(math.isfinite(value) and 0 <= value <= 1 for value in point)
            for point in self.points
            for value in point
        ):
            raise ValidationError("Tọa độ polygon phải hữu hạn và nằm trong khoảng 0–1.")
        if len(set(self.points)) != len(self.points):
            raise ValidationError("Các đỉnh polygon không được lặp lại.")
        area = sum(
            self.points[index][0] * self.points[(index + 1) % len(self.points)][1]
            - self.points[(index + 1) % len(self.points)][0] * self.points[index][1]
            for index in range(len(self.points))
        )
        if abs(area) < 1e-6:
            raise ValidationError("Polygon phải bao quanh một vùng có diện tích.")

        def orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        def on_segment(
            a: tuple[float, float], b: tuple[float, float], point: tuple[float, float]
        ) -> bool:
            return min(a[0], b[0]) <= point[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= point[
                1
            ] <= max(a[1], b[1])

        def intersects(
            a: tuple[float, float],
            b: tuple[float, float],
            c: tuple[float, float],
            d: tuple[float, float],
        ) -> bool:
            ab_c, ab_d = orientation(a, b, c), orientation(a, b, d)
            cd_a, cd_b = orientation(c, d, a), orientation(c, d, b)
            if ab_c * ab_d < 0 and cd_a * cd_b < 0:
                return True
            return (
                (ab_c == 0 and on_segment(a, b, c))
                or (ab_d == 0 and on_segment(a, b, d))
                or (cd_a == 0 and on_segment(c, d, a))
                or (cd_b == 0 and on_segment(c, d, b))
            )

        count = len(self.points)
        for first in range(count):
            a, b = self.points[first], self.points[(first + 1) % count]
            for second in range(first + 1, count):
                if second == first + 1 or (first == 0 and second == count - 1):
                    continue
                c, d = self.points[second], self.points[(second + 1) % count]
                if intersects(a, b, c, d):
                    raise ValidationError("Các cạnh polygon không được tự giao nhau.")


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    kind: SourceKind
    endpoint: str = field(repr=False)
    purpose: SourcePurpose = SourcePurpose.ENTRY
    parking_spaces: tuple[ParkingSpace, ...] = ()

    def validate(self) -> None:
        if not self.id or len(self.id) > 50 or not self.name.strip() or len(self.name) > 100:
            raise ValidationError("Nguồn hình cần mã và tên hợp lệ (tên tối đa 100 ký tự).")
        if not isinstance(self.kind, SourceKind) or not isinstance(self.purpose, SourcePurpose):
            raise ValidationError("Loại hoặc mục đích nguồn hình không hợp lệ.")
        endpoint = self.endpoint.strip()
        if not endpoint:
            raise ValidationError("Cần nhập chỉ số webcam, địa chỉ camera hoặc tệp MP4.")
        if self.kind == SourceKind.MP4:
            if Path(endpoint).suffix.lower() != ".mp4":
                raise ValidationError("Chế độ thử nghiệm chỉ nhận tệp .mp4.")
        elif not endpoint.isdecimal():
            try:
                parsed = urlsplit(endpoint)
                valid = parsed.scheme.lower() in {"rtsp", "rtsps", "http", "https"}
                valid = valid and bool(parsed.hostname)
            except ValueError:
                valid = False
            if not valid:
                raise ValidationError("Camera cần chỉ số webcam từ 0 hoặc URL RTSP/HTTP hợp lệ.")
        codes: set[str] = set()
        for space in self.parking_spaces:
            space.validate()
            normalized_code = space.code.strip().casefold()
            if normalized_code in codes:
                raise ValidationError("Mã các ô đỗ trong cùng camera không được trùng.")
            codes.add(normalized_code)
        if self.parking_spaces and self.purpose != SourcePurpose.PARKING:
            raise ValidationError("Chỉ camera có mục đích khu đỗ mới được cấu hình polygon ô.")


@dataclass(frozen=True)
class Frame:
    source_id: str
    source_kind: SourceKind
    stream_id: str
    frame_index: int
    observed_at: datetime
    media_time_s: float | None
    image: Any = field(repr=False, compare=False)
    plate_detections: tuple[PlateDetection, ...] = ()
    parking_space_states: dict[str, ParkingSpaceStatus] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoOptions:
    open_timeout_s: float = 8.0
    read_timeout_s: float = 4.0
    reconnect_delay_s: float = 2.0
    stale_after_s: float = 3.0
    fallback_fps: float = 25.0

    def __post_init__(self) -> None:
        values = (
            self.open_timeout_s,
            self.read_timeout_s,
            self.reconnect_delay_s,
            self.stale_after_s,
            self.fallback_fps,
        )
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValidationError("Thời gian chờ và FPS dự phòng phải là số dương hữu hạn.")


@dataclass(frozen=True)
class VisionOptions:
    model_path: Path
    confidence_threshold: float = 0.25
    image_size: int = 640
    device: str = "cpu"
    stale_track_frames: int = 300

    def __post_init__(self) -> None:
        if not math.isfinite(self.confidence_threshold) or not 0 < self.confidence_threshold < 1:
            raise ValidationError("Ngưỡng tin cậy YOLO phải nằm giữa 0 và 1.")
        if self.image_size < 32 or self.image_size > 4096:
            raise ValidationError("Kích thước suy luận YOLO phải nằm trong khoảng 32–4096.")
        if not self.device.strip():
            raise ValidationError("Thiết bị suy luận không được để trống.")
        if self.stale_track_frames < 1:
            raise ValidationError("Thời gian lưu track phải ít nhất một khung hình.")
