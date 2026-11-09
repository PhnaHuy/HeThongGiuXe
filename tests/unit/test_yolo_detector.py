from pathlib import Path

import numpy as np
import pytest

from parking_app.domain.enums import VehicleType
from parking_app.domain.exceptions import ValidationError
from parking_app.domain.video import VisionOptions
from parking_app.infrastructure.vision.yolo_detector import VisionError, YOLOVehicleDetector


class TensorValue:
    def __init__(self, value):
        self.value = np.asarray(value)

    def cpu(self):
        return self

    def tolist(self):
        return self.value.tolist()

    def int(self):
        return TensorValue(self.value.astype(int))


class Boxes:
    xyxy = TensorValue([[10, 20, 90, 80], [25, 30, 75, 70]])
    conf = TensorValue([0.91, 0.82])
    cls = TensorValue([2, 3])
    id = TensorValue([7, 9])

    def __len__(self):
        return 2


class FakeModel:
    def __init__(self):
        self.predictor = None
        self.calls = []

    def track(self, image, **kwargs):
        self.calls.append(kwargs)
        return [type("Result", (), {"boxes": Boxes()})()]


def test_yolo_adapter_maps_coco_classes_and_normalizes_coordinates(tmp_path):
    options = VisionOptions(model_path=tmp_path / "model.pt")
    detector = YOLOVehicleDetector.__new__(YOLOVehicleDetector)
    detector.options = options
    detector.model = FakeModel()

    detections = detector.detect(np.zeros((100, 200, 3), dtype=np.uint8))

    assert [item.vehicle_type for item in detections] == [
        VehicleType.CAR,
        VehicleType.MOTORCYCLE,
    ]
    assert detections[0].x1 == pytest.approx(0.05)
    assert detections[0].y2 == pytest.approx(0.8)
    assert [item.track_id for item in detections] == [7, 9]
    assert detector.model.calls[0]["tracker"] == "bytetrack.yaml"
    assert detector.model.calls[0]["persist"] is True
    assert detector.model.calls[0]["classes"] == [2, 3]


def test_yolo_adapter_requires_an_existing_local_model(tmp_path):
    with pytest.raises(VisionError, match="Không tìm thấy model YOLO cục bộ"):
        YOLOVehicleDetector(VisionOptions(model_path=tmp_path / "missing.pt"))


def test_vision_settings_reject_invalid_values():
    with pytest.raises(ValidationError, match="Ngưỡng tin cậy"):
        VisionOptions(model_path=Path("model.pt"), confidence_threshold=1.0)


def test_tracker_receives_low_confidence_boxes_for_second_association(tmp_path):
    detector = YOLOVehicleDetector.__new__(YOLOVehicleDetector)
    detector.options = VisionOptions(model_path=tmp_path / "model.pt")
    detector.model = FakeModel()
    detector.detect(np.zeros((100, 200, 3), dtype=np.uint8))
    assert detector.model.calls[0]["conf"] == 0.1


def test_reset_preserves_tracker_slots_for_persistent_callbacks():
    from types import SimpleNamespace

    class Tracker:
        reset_count = 0

        def reset(self):
            self.reset_count += 1

    tracker = Tracker()
    detector = YOLOVehicleDetector.__new__(YOLOVehicleDetector)
    detector.model = SimpleNamespace(
        predictor=SimpleNamespace(trackers=[tracker], vid_path=["old"])
    )
    detector.reset()
    assert detector.model.predictor.trackers == [tracker]
    assert tracker.reset_count == 1
    assert detector.model.predictor.vid_path == [None]
