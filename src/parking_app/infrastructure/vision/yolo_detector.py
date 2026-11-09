"""Local YOLOv8 vehicle detection with the bundled ByteTrack tracker."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from parking_app.domain.vision import VehicleDetection

COCO_VEHICLE_CLASSES = {2: "car", 3: "motorcycle"}


class VisionOptionsProtocol(Protocol):
    model_path: Path
    confidence_threshold: float
    image_size: int
    device: str


class VisionError(RuntimeError):
    """A sanitized model or inference failure suitable for the application UI."""


class VehicleDetector(Protocol):
    def detect(self, image) -> tuple[VehicleDetection, ...]: ...

    def reset(self) -> None: ...


class YOLOVehicleDetector:
    def __init__(self, options: VisionOptionsProtocol) -> None:
        self.options = options
        model_path = Path(options.model_path).expanduser().resolve()
        if not model_path.is_file():
            raise VisionError(f"Không tìm thấy model YOLO cục bộ: {model_path}")
        try:
            from ultralytics import YOLO

            self.model = YOLO(str(model_path))
        except Exception as exc:
            raise VisionError("Không thể nạp model YOLO cục bộ.") from exc

    def detect(self, image) -> tuple[VehicleDetection, ...]:
        from parking_app.domain.enums import VehicleType

        try:
            results = self.model.track(
                image,
                persist=True,
                tracker="bytetrack.yaml",
                classes=list(COCO_VEHICLE_CLASSES),
                # ByteTrack needs weak detections for its second association pass.
                conf=min(self.options.confidence_threshold, 0.1),
                imgsz=self.options.image_size,
                device=self.options.device,
                verbose=False,
            )
        except Exception as exc:
            raise VisionError(
                "Không thể phát hiện hoặc theo dõi phương tiện trong khung hình."
            ) from exc

        if not results:
            return ()
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return ()
        coordinates = boxes.xyxy.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        classes = boxes.cls.cpu().tolist()
        height, width = image.shape[:2]
        track_ids = boxes.id
        ids = track_ids.int().cpu().tolist() if track_ids is not None else [None] * len(coordinates)
        class_types = {2: VehicleType.CAR, 3: VehicleType.MOTORCYCLE}
        return tuple(
            VehicleDetection(
                x1=float(box[0]) / width,
                y1=float(box[1]) / height,
                x2=float(box[2]) / width,
                y2=float(box[3]) / height,
                confidence=float(confidence),
                vehicle_type=class_types[int(class_id)],
                track_id=int(track_id) if track_id is not None else None,
            )
            for box, confidence, class_id, track_id in zip(
                coordinates, confidences, classes, ids, strict=True
            )
            if int(class_id) in class_types and confidence >= self.options.confidence_threshold
        )

    def reset(self) -> None:
        predictor = self.model.predictor
        if predictor is None:
            return
        for tracker in getattr(predictor, "trackers", ()):
            tracker.reset()
        # Keep tracker slots: older Ultralytics callbacks reuse the attribute
        # with persist=True even when it is an empty list.
        predictor.vid_path = [None] * len(getattr(predictor, "vid_path", ()))
