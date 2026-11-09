"""Bounded playback delivery; OpenCV never executes on the GUI thread."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import cv2
from PySide6.QtCore import QThread, Signal

from parking_app.application.parking_space_monitor import ParkingSpaceMonitor
from parking_app.application.video_source import VideoCancelled, VideoError, VideoSource
from parking_app.config.settings import DEFAULT_PLATE_MODEL_PATH
from parking_app.domain.enums import VehicleType
from parking_app.domain.video import (
    Frame,
    SourceConfig,
    SourceKind,
    SourcePurpose,
    StreamStatus,
    VideoOptions,
    VisionOptions,
)
from parking_app.domain.vision import (
    EventCandidate,
    GateDirection,
    PlateDetection,
)
from parking_app.infrastructure.video.isolated_source import IsolatedVideoSource
from parking_app.infrastructure.vision.errors import VisionError
from parking_app.infrastructure.vision.plate_detector import PlateTracker, YOLOPlateDetector


class VideoWorker(QThread):
    frame_available = Signal()
    status_changed = Signal(object, str)
    stream_reset = Signal(str)
    metadata_ready = Signal(float, int)
    event_candidate = Signal(object)

    def __init__(
        self,
        config: SourceConfig,
        options: VideoOptions | None = None,
        *,
        realtime: bool = True,
        initial_index: int = 0,
        source_factory: Callable[..., VideoSource] = IsolatedVideoSource,
        plate_vision_options: VisionOptions | None = None,
        plate_detector_factory: Callable[[VisionOptions], PlateTracker] = YOLOPlateDetector,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.options = options or VideoOptions()
        self.realtime = realtime
        self.initial_index = initial_index
        self.source_factory = source_factory
        self.plate_vision_options = plate_vision_options or VisionOptions(
            model_path=DEFAULT_PLATE_MODEL_PATH
        )
        self.plate_detector_factory = plate_detector_factory
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._paused = False
        self._seek: int | None = None
        self._frame: Frame | None = None
        self._stream_id = ""
        self.dropped_frames = 0
        self.frames_read = 0
        self._plate_detector: PlateTracker | None = None
        self._candidate_tracks: dict[int, int] = {}
        self._parking_spaces = ParkingSpaceMonitor(config.parking_spaces)

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._frame = None
            self._condition.notify_all()

    def set_paused(self, paused: bool) -> None:
        if self.config.kind == SourceKind.MP4:
            with self._condition:
                self._paused = paused
                self._condition.notify_all()

    def seek(self, frame_index: int) -> None:
        if self.config.kind == SourceKind.MP4:
            with self._condition:
                self._seek = frame_index
                self._frame = None
                self._condition.notify_all()

    def take_frame(self) -> Frame | None:
        with self._condition:
            frame, self._frame = self._frame, None
            self._condition.notify_all()
            return frame

    def _reset(self) -> None:
        with self._condition:
            self._frame = None
            self._stream_id = uuid.uuid4().hex
        if self._plate_detector is not None:
            self._plate_detector.reset()
        self._candidate_tracks.clear()
        self._parking_spaces.reset()
        # G4/G5 subscribe here to discard tracking and OCR state.
        self.stream_reset.emit(self._stream_id)

    def _new_candidates(
        self, detections: tuple[PlateDetection, ...], frame_index: int
    ) -> list[PlateDetection]:
        if self.config.purpose == SourcePurpose.PARKING:
            return []
        stale_before = frame_index - self.plate_vision_options.stale_track_frames
        self._candidate_tracks = {
            track_id: last_seen
            for track_id, last_seen in self._candidate_tracks.items()
            if last_seen >= stale_before
        }
        new_tracks = []
        for detection in detections:
            if detection.track_id is None:
                continue
            previous = self._candidate_tracks.get(detection.track_id)
            self._candidate_tracks[detection.track_id] = frame_index
            if previous is None:
                new_tracks.append(detection)
        return new_tracks

    def _publish(self, frame: Frame) -> None:
        with self._condition:
            if self._stop.is_set() or self._seek is not None:
                return
            was_empty = self._frame is None
            if not was_empty:
                self.dropped_frames += 1
            self._frame = frame
        # At most one pending notification; live can replace the one buffered frame.
        if was_empty:
            self.frame_available.emit()

    def run(self) -> None:
        is_file = self.config.kind == SourceKind.MP4
        try:
            self._plate_detector = self.plate_detector_factory(self.plate_vision_options)
        except VisionError as exc:
            self.status_changed.emit(StreamStatus.ERROR, str(exc))
            return
        except Exception:
            self.status_changed.emit(
                StreamStatus.ERROR, "Không thể khởi tạo model phát hiện biển số."
            )
            return
        while not self._stop.is_set():
            source = self.source_factory(self.config, self.options, self._stop.is_set)
            self._reset()
            self.status_changed.emit(StreamStatus.CONNECTING, "")
            try:
                source.open()
                self.metadata_ready.emit(source.fps, source.frame_count)
                if self.initial_index and is_file:
                    source.seek(self.initial_index)
                self._play(source)
                break
            except VideoCancelled:
                break
            except VisionError as exc:
                self._reset()
                self.status_changed.emit(StreamStatus.ERROR, str(exc))
                break
            except Exception:
                self._reset()
                status = StreamStatus.ERROR if is_file else StreamStatus.DISCONNECTED
                self.status_changed.emit(
                    status,
                    "Kiểm tra tệp MP4." if is_file else "Sẽ tự thử kết nối lại.",
                )
                if is_file:
                    break
            finally:
                source.close()
            if self._stop.wait(self.options.reconnect_delay_s):
                break
        if self._stop.is_set():
            self.status_changed.emit(StreamStatus.STOPPED, "")

    def _play(self, source: VideoSource) -> None:
        is_file = self.config.kind == SourceKind.MP4
        status = None
        due = time.monotonic()
        while not self._stop.is_set():
            with self._condition:
                # MP4 uses backpressure: never discard decoded frames to keep up with UI.
                while is_file and self._frame is not None and not self._stop.is_set():
                    self._condition.wait(0.05)
                seek, self._seek = self._seek, None
                paused = self._paused
            if self._stop.is_set():
                return
            if seek is not None:
                source.seek(seek)
                self._reset()
                due = time.monotonic()
            next_status = StreamStatus.PAUSED if paused else StreamStatus.PLAYING
            if next_status != status:
                status = next_status
                self.status_changed.emit(status, "")
                due = time.monotonic()
            if paused and seek is None:
                with self._condition:
                    self._condition.wait(0.05)
                continue
            if is_file and self.realtime and seek is None:
                delay = due - time.monotonic()
                if delay > 0:
                    with self._condition:
                        self._condition.wait(min(delay, 0.05))
                    continue
            result = source.read()
            if self._stop.is_set():
                return
            if result is None:
                if not is_file:
                    raise VideoError("Camera ngừng cung cấp hình.")
                self.status_changed.emit(StreamStatus.EOF, "")
                return
            index, media_time, image = result
            observed_at = datetime.now(UTC)
            self.frames_read += 1
            plate_detections = (
                self._plate_detector.track(image) if self._plate_detector is not None else ()
            )
            parking_space_states = self._parking_spaces.update(image.shape, plate_detections)
            frame = Frame(
                source_id=self.config.id,
                source_kind=self.config.kind,
                stream_id=self._stream_id,
                frame_index=index,
                observed_at=observed_at,
                media_time_s=media_time,
                image=image,
                plate_detections=plate_detections,
                parking_space_states=parking_space_states,
            )
            for detection in self._new_candidates(plate_detections, index):
                self.event_candidate.emit(self._candidate(frame, detection))
            self._publish(frame)
            due = time.monotonic() + 1 / source.fps

    def _candidate(
        self,
        frame: Frame,
        detection: PlateDetection,
    ) -> EventCandidate:
        if detection.track_id is None:
            raise VisionError("Đề xuất biển số cần track ID hợp lệ.")
        success, encoded = cv2.imencode(".jpg", frame.image)
        if not success:
            raise VisionError("Không thể mã hóa ảnh camera để nhân viên đối chiếu.")
        image_data = encoded.tobytes()
        return EventCandidate(
            id=uuid.uuid4().hex,
            source_id=frame.source_id,
            source_name=self.config.name,
            source_kind=frame.source_kind,
            stream_id=frame.stream_id,
            track_id=detection.track_id,
            direction=(
                GateDirection.ENTRY
                if self.config.purpose == SourcePurpose.ENTRY
                else GateDirection.EXIT
            ),
            vehicle_type=VehicleType.MOTORCYCLE,
            confidence=detection.confidence,
            observed_at=frame.observed_at,
            media_time_s=frame.media_time_s,
            image_data=image_data,
            source_image_samples=(image_data,),
        )
