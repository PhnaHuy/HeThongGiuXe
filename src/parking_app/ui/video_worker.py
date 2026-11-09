"""Bounded playback delivery; OpenCV never executes on the GUI thread."""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import cv2
from PySide6.QtCore import QThread, Signal

from parking_app.application.gate_crossing import GateCrossingTracker
from parking_app.application.parking_space_monitor import ParkingSpaceMonitor
from parking_app.application.video_source import VideoCancelled, VideoError, VideoSource
from parking_app.domain.video import (
    Frame,
    GateLine,
    SourceConfig,
    SourceKind,
    StreamStatus,
    VideoOptions,
    VisionOptions,
)
from parking_app.domain.vision import EventCandidate, GateDirection, VehicleDetection
from parking_app.infrastructure.video.isolated_source import IsolatedVideoSource
from parking_app.infrastructure.vision.yolo_detector import (
    VehicleDetector,
    VisionError,
    YOLOVehicleDetector,
)


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
        vision_options: VisionOptions | None = None,
        detector_factory: Callable[[VisionOptions], VehicleDetector] = YOLOVehicleDetector,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.options = options or VideoOptions()
        self.realtime = realtime
        self.initial_index = initial_index
        self.source_factory = source_factory
        self.vision_options = vision_options or VisionOptions(
            model_path=Path(__file__).resolve().parents[3] / "models" / "yolov8n.pt"
        )
        self.detector_factory = detector_factory
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._paused = False
        self._seek: int | None = None
        self._frame: Frame | None = None
        self._stream_id = ""
        self._line = config.line
        self._line_revision = 0
        self._applied_line_revision = 0
        self.dropped_frames = 0
        self.frames_read = 0
        self._detector: VehicleDetector | None = None
        self._vehicle_samples: dict[int, deque[tuple[int, bytes]]] = defaultdict(
            lambda: deque(maxlen=5)
        )
        self._crossings = GateCrossingTracker(
            deadband=self.vision_options.crossing_deadband,
            stable_frames=self.vision_options.crossing_stable_frames,
            stale_track_frames=self.vision_options.stale_track_frames,
        )
        self._parking_spaces = ParkingSpaceMonitor(config.parking_spaces)

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._frame = None
            self._condition.notify_all()

    def set_gate_line(self, line: GateLine | None) -> None:
        """Apply editor changes at a frame boundary on the processing thread."""
        if line is not None:
            line.validate()
        with self._condition:
            if line != self._line:
                self._line = line
                self._line_revision += 1

    def _crossing_events(self, detections, frame_index):
        with self._condition:
            line = self._line
            revision = self._line_revision
        if revision != self._applied_line_revision:
            self._crossings.reset()
            self._applied_line_revision = revision
        return self._crossings.update(detections, line, frame_index)

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
        if self._detector is not None:
            self._detector.reset()
        self._vehicle_samples.clear()
        self._crossings.reset()
        self._parking_spaces.reset()
        # G4/G5 subscribe here to discard tracking/crossing/OCR state.
        self.stream_reset.emit(self._stream_id)

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
            self._detector = self.detector_factory(self.vision_options)
        except VisionError as exc:
            self.status_changed.emit(StreamStatus.ERROR, str(exc))
            return
        except Exception:
            self.status_changed.emit(
                StreamStatus.ERROR, "Không thể khởi tạo nhận dạng phương tiện."
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
            detections = self._detector.detect(image) if self._detector is not None else ()
            parking_space_states = self._parking_spaces.update(image.shape, detections)
            self._remember_vehicle_samples(image, detections, index)
            frame = Frame(
                source_id=self.config.id,
                source_kind=self.config.kind,
                stream_id=self._stream_id,
                frame_index=index,
                observed_at=observed_at,
                media_time_s=media_time,
                image=image,
                detections=detections,
                parking_space_states=parking_space_states,
            )
            for detection, direction in self._crossing_events(detections, index):
                self.event_candidate.emit(self._candidate(frame, detection, direction))
            self._publish(frame)
            due = time.monotonic() + 1 / source.fps

    def _candidate(
        self,
        frame: Frame,
        detection: VehicleDetection,
        direction: GateDirection,
    ) -> EventCandidate:
        if detection.track_id is None:
            raise VisionError("Sự kiện qua vạch cần track ID hợp lệ.")
        vehicle_crop = self._vehicle_crop(frame.image, detection)
        success, encoded = cv2.imencode(".jpg", vehicle_crop)
        if not success:
            raise VisionError("Không thể mã hóa ảnh phương tiện để nhân viên đối chiếu.")
        sample_data = [data for _, data in self._vehicle_samples.get(detection.track_id, ())]
        if not sample_data or sample_data[-1] != encoded.tobytes():
            sample_data.append(encoded.tobytes())
        return EventCandidate(
            id=uuid.uuid4().hex,
            source_id=frame.source_id,
            source_name=self.config.name,
            source_kind=frame.source_kind,
            stream_id=frame.stream_id,
            track_id=detection.track_id,
            direction=direction,
            vehicle_type=detection.vehicle_type,
            confidence=detection.confidence,
            observed_at=frame.observed_at,
            media_time_s=frame.media_time_s,
            image_data=encoded.tobytes(),
            vehicle_image_samples=tuple(sample_data[-5:]),
        )

    def _remember_vehicle_samples(
        self,
        image,
        detections: tuple[VehicleDetection, ...],
        frame_index: int,
    ) -> None:
        for track_id in tuple(self._vehicle_samples):
            samples = self._vehicle_samples[track_id]
            if samples and frame_index - samples[-1][0] > self.vision_options.stale_track_frames:
                del self._vehicle_samples[track_id]
        if frame_index % 5:
            return
        for detection in detections:
            if detection.track_id is None:
                continue
            crop = self._vehicle_crop(image, detection)
            success, encoded = cv2.imencode(".jpg", crop)
            if success:
                self._vehicle_samples[detection.track_id].append((frame_index, encoded.tobytes()))

    @staticmethod
    def _vehicle_crop(image, detection: VehicleDetection):
        height, width = image.shape[:2]
        x1 = max(0, min(width, round(detection.x1 * width)))
        y1 = max(0, min(height, round(detection.y1 * height)))
        x2 = max(0, min(width, round(detection.x2 * width)))
        y2 = max(0, min(height, round(detection.y2 * height)))
        if x2 <= x1 or y2 <= y1:
            raise VisionError("Không thể cắt ảnh phương tiện từ kết quả phát hiện.")
        return image[y1:y2, x1:x2]
