import importlib.util
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from parking_app.application.plate_recognition import PlateRecognitionService
from parking_app.config.settings import AppSettings
from parking_app.domain.plate import PlateRecognitionOptions
from parking_app.infrastructure.vision.paddle_ocr import PlateOCRFailure
from parking_app.infrastructure.vision.plate_detector import PlateRegion, YOLOPlateRegionDetector


def options(tmp_path):
    return PlateRecognitionOptions(tmp_path / "python", tmp_path / "worker", tmp_path / "cache")


class Regions:
    def detect(self, image):
        return (PlateRegion(0, 0, 30, 20, 0.9), PlateRegion(30, 0, 60, 20, 0.8))


class OCR:
    def __init__(self, values):
        self.values = values

    def recognize(self, crops):
        return tuple(self.values)


def recognize(tmp_path, values, count=1):
    _, encoded = cv2.imencode(".png", np.full((40, 80, 3), 128, dtype=np.uint8))
    service = PlateRecognitionService(options(tmp_path), OCR(values), Regions())
    return service.recognize((encoded.tobytes(),) * count)


def test_second_region_can_recover_plate_and_evidence_remains_jpeg(tmp_path):
    result = recognize(tmp_path, [("", 0), ("60F364435", 0.95)])
    assert result.proposed_plate == "60F364435"
    assert result.plate_image_data.startswith(b"\xff\xd8")


def test_same_frame_regions_do_not_outvote_independent_frames(tmp_path):
    result = recognize(
        tmp_path,
        [
            ("60F364435", 0.95),
            ("60F364435", 0.95),
            ("60F364436", 0.9),
            ("", 0),
            ("60F364436", 0.9),
            ("", 0),
        ],
        count=3,
    )
    assert result.proposed_plate == "60F364436"


def test_conflicting_frames_abstain_and_preserve_raw_observations(tmp_path):
    result = recognize(
        tmp_path,
        [
            ("60F364435", 0.95),
            ("", 0),
            ("60F364436", 0.9),
            ("", 0),
        ],
        count=2,
    )
    assert result.proposed_plate is None
    assert "60F364435" in result.raw_text and "60F364436" in result.raw_text


def test_low_confidence_is_not_auto_proposed(tmp_path):
    assert recognize(tmp_path, [("60F364435", 0.2), ("", 0)]).proposed_plate is None


@pytest.mark.parametrize("values", [[("60F364435", 0.9)], [("x", float("nan")), ("", 0)]])
def test_invalid_ocr_responses_fail_explicitly(tmp_path, values):
    with pytest.raises(PlateOCRFailure):
        recognize(tmp_path, values)


def test_missing_plate_model_fails_on_worker_not_constructor(tmp_path):
    detector = YOLOPlateRegionDetector(
        replace(options(tmp_path), detector_model_path=tmp_path / "x")
    )
    with pytest.raises(PlateOCRFailure, match="model"):
        detector.detect(np.zeros((50, 50, 3), dtype=np.uint8))


def test_yolo_plate_boxes_are_clipped_to_image(tmp_path):
    detector = YOLOPlateRegionDetector(options(tmp_path))
    boxes = SimpleNamespace(
        data=SimpleNamespace(
            cpu=lambda: SimpleNamespace(tolist=lambda: [[-4, -2, 100, 60, 0.9, 0]])
        )
    )
    detector.model = SimpleNamespace(predict=lambda *a, **kw: [SimpleNamespace(boxes=boxes)])
    assert detector.detect(np.zeros((50, 80, 3), dtype=np.uint8)) == (
        PlateRegion(0, 0, 80, 50, 0.9),
    )


def load_script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paddle_two_rows_sorted_geometrically_with_numpy_scores():
    worker = load_script("ocr_worker")
    text, score = worker._reading_order(
        {
            "rec_texts": ["64435", "F3", "60"],
            "rec_scores": np.array([0.9, 0.9, 0.9]),
            "rec_polys": [
                [[0, 30], [50, 30], [50, 45], [0, 45]],
                [[30, 2], [50, 2], [50, 17], [30, 17]],
                [[0, 0], [20, 0], [20, 15], [0, 15]],
            ],
        }
    )
    assert text == "60\nF3\n64435"
    assert score == pytest.approx(0.9)


def test_evaluation_counts_abstentions_and_errors_in_denominator():
    script = load_script("evaluate_plates")
    rows = [
        dict(correct=True, predicted="A", group="a", error=None, seconds=1),
        dict(correct=False, predicted=None, group="b", error="timeout", seconds=2),
    ]
    summary = script.summarize(rows)
    assert summary["exact_plate_accuracy"] == 0.5
    assert summary["accuracy_among_proposals"] == 1
    assert not summary["above_90_percent_on_this_manifest"]


def test_config_selects_isolated_fast_runtime_and_paddle_fallback(monkeypatch):
    monkeypatch.setenv("PARKING_OCR_BACKEND", "fast_plate")
    fast = AppSettings().plate_recognition_options
    assert fast.worker_path.name == "plate_ocr_worker.py"
    assert fast.python_path.parent.parent.name == ".venv-alpr"
    monkeypatch.setenv("PARKING_OCR_BACKEND", "paddle")
    assert AppSettings().plate_recognition_options.worker_path.name == "ocr_worker.py"
