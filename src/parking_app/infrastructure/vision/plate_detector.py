"""Ultralytics detector for trained license-plate regions."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from parking_app.domain.vision import PlateDetection
from parking_app.infrastructure.vision.errors import VisionError


class PlateVisionOptions(Protocol):
    model_path: Path
    confidence_threshold: float
    image_size: int
    device: str


class PlateDetector(Protocol):
    def detect(self, image) -> tuple[PlateDetection, ...]: ...


class PlateTracker(PlateDetector, Protocol):
    def track(self, image) -> tuple[PlateDetection, ...]: ...

    def reset(self) -> None: ...


class YOLOPlateDetector:
    def __init__(self, options: PlateVisionOptions) -> None:
        self.options = options
        model_path = Path(options.model_path).expanduser().resolve()
        if not model_path.is_file():
            raise VisionError(f"Không tìm thấy model biển số cục bộ: {model_path}")
        try:
            from ultralytics import YOLO

            self.model = YOLO(str(model_path))
        except Exception as exc:
            raise VisionError("Không thể nạp model phát hiện biển số cục bộ.") from exc

        names = self.model.names
        self.plate_class_ids = tuple(
            class_id
            for class_id, name in (names.items() if isinstance(names, dict) else enumerate(names))
            if "plate" in str(name).casefold() or "biển số" in str(name).casefold()
        )
        if not self.plate_class_ids:
            raise VisionError("Model được chọn không có lớp phát hiện biển số.")

    def detect(self, image) -> tuple[PlateDetection, ...]:
        return self._infer(image, tracking=False)

    def track(self, image) -> tuple[PlateDetection, ...]:
        return self._infer(image, tracking=True)

    def _infer(self, image, *, tracking: bool) -> tuple[PlateDetection, ...]:
        try:
            operation = self.model.track if tracking else self.model.predict
            arguments = {
                "classes": list(self.plate_class_ids),
                "conf": self.options.confidence_threshold,
                "imgsz": self.options.image_size,
                "device": self.options.device,
                "verbose": False,
            }
            if tracking:
                arguments.update(tracker="bytetrack.yaml", persist=True)
            results = operation(image, **arguments)
        except Exception as exc:
            raise VisionError("Không thể phát hiện vùng biển số trong khung hình.") from exc

        if not results:
            return ()
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return ()
        coordinates = boxes.xyxy.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        track_ids = boxes.id
        ids = track_ids.int().cpu().tolist() if track_ids is not None else [None] * len(coordinates)
        height, width = image.shape[:2]
        return tuple(
            PlateDetection(
                x1=float(box[0]) / width,
                y1=float(box[1]) / height,
                x2=float(box[2]) / width,
                y2=float(box[3]) / height,
                confidence=float(confidence),
                track_id=int(track_id) if track_id is not None else None,
            )
            for box, confidence, track_id in zip(coordinates, confidences, ids, strict=True)
        )

    def reset(self) -> None:
        predictor = self.model.predictor
        if predictor is None:
            return
        for tracker in getattr(predictor, "trackers", ()):
            tracker.reset()
        predictor.vid_path = [None] * len(getattr(predictor, "vid_path", ()))
