"""Plate-region detection, multi-image OCR, and consensus proposal."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from math import isfinite
from typing import Protocol

import cv2
import numpy as np

from parking_app.config.settings import DEFAULT_PLATE_MODEL_PATH
from parking_app.domain.exceptions import ValidationError
from parking_app.domain.plate import (
    PlateOCRObservation,
    PlateOCRResult,
    PlateRecognition,
    PlateRecognitionOptions,
    normalize_plate,
    validate_normalized_plate,
)
from parking_app.domain.video import VisionOptions
from parking_app.infrastructure.vision.paddle_ocr import PaddleOCRSubprocess, PlateOCRFailure
from parking_app.infrastructure.vision.plate_detector import PlateDetector, YOLOPlateDetector


class OCRClient(Protocol):
    def recognize(self, images: tuple[bytes, ...]) -> tuple[PlateOCRResult, ...]: ...


class PlateRecognitionUseCase(Protocol):
    def recognize(self, source_images: tuple[bytes, ...]) -> PlateRecognition: ...


class PlateRecognitionService:
    def __init__(
        self,
        options: PlateRecognitionOptions,
        ocr_client: OCRClient | None = None,
        *,
        plate_vision_options: VisionOptions | None = None,
        plate_detector_factory: Callable[[VisionOptions], PlateDetector] = YOLOPlateDetector,
    ) -> None:
        self.options = options
        self.ocr_client = ocr_client or PaddleOCRSubprocess(options)
        self.plate_vision_options = plate_vision_options or VisionOptions(
            model_path=DEFAULT_PLATE_MODEL_PATH
        )
        self.plate_detector_factory = plate_detector_factory
        self._plate_detector: PlateDetector | None = None

    def _detector(self) -> PlateDetector:
        if self._plate_detector is None:
            self._plate_detector = self.plate_detector_factory(self.plate_vision_options)
        return self._plate_detector

    def warmup(self) -> None:
        warmup = getattr(self.ocr_client, "warmup", None)
        if callable(warmup):
            warmup()

    def close(self) -> None:
        close = getattr(self.ocr_client, "close", None)
        if callable(close):
            close()

    def recognize(self, source_images: tuple[bytes, ...]) -> PlateRecognition:
        images = source_images[-self.options.max_samples :]
        encoded_images: list[bytes] = []
        source_indices: list[int] = []
        for source_index, encoded_image in enumerate(images):
            if not encoded_image:
                continue
            image = cv2.imdecode(
                np.frombuffer(encoded_image, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            if image is None:
                continue
            detections = self._detector().detect(image)
            if not detections:
                continue
            detection, (x1, y1, x2, y2) = max(
                ((item, self._plate_bounds(image, item)) for item in detections),
                key=lambda item: self._plate_quality(image, item[0], item[1]),
            )
            if x2 <= x1 or y2 <= y1:
                continue
            image = image[y1:y2, x1:x2]
            scale = min(3.0, 900 / max(image.shape[:2]))
            if scale > 1:
                image = cv2.resize(
                    image,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_CUBIC,
                )
            success, result = cv2.imencode(".png", image)
            if success:
                encoded_images.append(result.tobytes())
                source_indices.append(source_index)

        if not encoded_images:
            return PlateRecognition((), None, None, None, len(images))

        raw_results = self.ocr_client.recognize(tuple(encoded_images))
        if len(raw_results) != len(encoded_images):
            raise PlateOCRFailure("Số kết quả OCR không khớp số ảnh đã gửi.")
        observations: list[PlateOCRObservation] = []
        votes: dict[str, dict[int, tuple[float, int]]] = defaultdict(dict)
        for index, reading in enumerate(raw_results):
            raw_text, confidence = reading.text, reading.confidence
            if not isfinite(confidence) or not 0 <= confidence <= 1:
                raise PlateOCRFailure("Độ tin cậy OCR không hợp lệ.")
            normalized = normalize_plate(raw_text)
            try:
                validate_normalized_plate(normalized)
            except ValidationError:
                normalized_plate = None
            else:
                normalized_plate = normalized
                if confidence >= self.options.min_ocr_confidence:
                    source_index = source_indices[index]
                    previous = votes[normalized].get(source_index, (0.0, index))
                    if confidence >= previous[0]:
                        votes[normalized][source_index] = (confidence, index)
            observations.append(
                PlateOCRObservation(
                    raw_text=raw_text,
                    confidence=confidence,
                    normalized_plate=normalized_plate,
                )
            )

        if not votes:
            return PlateRecognition(tuple(observations), None, None, None, len(images))

        ranked = sorted(
            votes.items(),
            key=lambda item: (len(item[1]), sum(v[0] for v in item[1].values())),
            reverse=True,
        )
        proposed, matching = ranked[0]
        participating = set().union(*(set(reads) for reads in votes.values()))
        # Multiple regions from one frame are not independent temporal votes.
        # A tied/conflicting reading must not silently populate the plate field.
        ambiguous = len(ranked) > 1 and (
            len(matching) <= len(participating) / 2 or len(matching) == len(ranked[1][1])
        )
        if ambiguous:
            return PlateRecognition(tuple(observations), None, None, None, len(images))
        matching_reads = list(matching.values())
        average_confidence = sum(value[0] for value in matching_reads) / len(matching_reads)
        best_index = max(matching_reads, key=lambda item: item[0])[1]
        return PlateRecognition(
            observations=tuple(observations),
            proposed_plate=proposed,
            confidence=average_confidence,
            plate_image_data=raw_results[best_index].plate_image_data,
            samples_considered=len(images),
        )

    @staticmethod
    def _plate_bounds(image, detection) -> tuple[int, int, int, int]:
        height, width = image.shape[:2]
        padding_x = round((detection.x2 - detection.x1) * width * 0.08)
        padding_y = round((detection.y2 - detection.y1) * height * 0.12)
        return (
            max(0, round(detection.x1 * width) - padding_x),
            max(0, round(detection.y1 * height) - padding_y),
            min(width, round(detection.x2 * width) + padding_x),
            min(height, round(detection.y2 * height) + padding_y),
        )

    @staticmethod
    def _plate_quality(image, detection, bounds: tuple[int, int, int, int]) -> float:
        x1, y1, x2, y2 = bounds
        if x2 <= x1 or y2 <= y1:
            return -1
        crop = image[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharpness = min(float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 300, 1)
        size = min((crop.shape[0] * crop.shape[1]) / 12000, 1)
        return 0.45 * detection.confidence + 0.35 * sharpness + 0.2 * size
