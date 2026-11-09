import cv2
import numpy as np

from parking_app.application.plate_recognition import PlateRecognitionService
from parking_app.domain.plate import PlateRecognitionOptions
from parking_app.infrastructure.vision.plate_detector import PlateRegionDetector


def plate_image(text="51A12345"):
    image = np.full((220, 360, 3), (110, 150, 195), dtype=np.uint8)
    cv2.rectangle(image, (80, 120), (280, 180), (255, 255, 255), -1)
    cv2.rectangle(image, (80, 120), (280, 180), (0, 0, 0), 3)
    cv2.putText(
        image,
        text,
        (92, 162),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return image, encoded.tobytes()


class SequenceOCR:
    def __init__(self, results):
        self.results = results
        self.received = ()

    def recognize(self, crops):
        self.received = crops
        return tuple(self.results)


def options(tmp_path):
    return PlateRecognitionOptions(
        python_path=tmp_path / "python.exe",
        worker_path=tmp_path / "ocr_worker.py",
        cache_dir=tmp_path / "cache",
    )


def test_plate_region_detector_finds_one_row_and_two_row_plate_shapes():
    detector = PlateRegionDetector()
    one_row, _ = plate_image()
    two_row = np.full((260, 260, 3), (100, 130, 170), dtype=np.uint8)
    cv2.rectangle(two_row, (65, 75), (195, 205), (255, 255, 255), -1)
    cv2.rectangle(two_row, (65, 75), (195, 205), (0, 0, 0), 3)
    cv2.putText(two_row, "51A", (85, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(two_row, "12345", (78, 178), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

    assert detector.detect(one_row)
    assert detector.detect(two_row)
    assert detector.detect(np.zeros((40, 40, 3), dtype=np.uint8)) == ()


def test_recognition_fuses_normalized_results_from_multiple_vehicle_images(tmp_path):
    _, image_data = plate_image()
    ocr = SequenceOCR((("51A-12345", 0.8), ("51A12345", 0.95)))
    service = PlateRecognitionService(options(tmp_path), ocr_client=ocr)

    result = service.recognize((image_data, image_data))

    assert result.proposed_plate == "51A12345"
    assert result.confidence == 0.875
    assert result.raw_text == "51A-12345 | 51A12345"
    assert result.samples_considered == 2
    assert result.plate_image_data is not None
    assert len(ocr.received) == 2


def test_recognition_preserves_ambiguous_characters_instead_of_correcting_them(tmp_path):
    _, image_data = plate_image()
    service = PlateRecognitionService(
        options(tmp_path),
        ocr_client=SequenceOCR((("51A12O45", 0.9),)),
    )

    result = service.recognize((image_data,))

    assert result.proposed_plate == "51A12O45"


def test_recognition_joins_two_row_plate_lines_without_losing_raw_layout(tmp_path):
    _, image_data = plate_image()
    service = PlateRecognitionService(
        options(tmp_path),
        ocr_client=SequenceOCR((("51A\n12345", 0.9),)),
    )

    result = service.recognize((image_data,))

    assert result.proposed_plate == "51A12345"
    assert result.raw_text == "51A\n12345"


def test_no_plate_region_returns_manual_review_result_without_calling_ocr(tmp_path):
    image = np.zeros((80, 100, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    ocr = SequenceOCR(())

    result = PlateRecognitionService(options(tmp_path), ocr_client=ocr).recognize(
        (encoded.tobytes(),)
    )

    assert result.proposed_plate is None
    assert result.observations == ()
    assert ocr.received == ()
