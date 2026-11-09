"""Plate-region detection, multi-image OCR, and consensus proposal."""

from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Protocol

import cv2
import numpy as np

from parking_app.domain.exceptions import ValidationError
from parking_app.domain.plate import (
    PlateOCRObservation,
    PlateRecognition,
    PlateRecognitionOptions,
    normalize_plate,
    validate_normalized_plate,
)
from parking_app.infrastructure.vision.paddle_ocr import PaddleOCRSubprocess, PlateOCRFailure
from parking_app.infrastructure.vision.plate_detector import (
    PlateRegionDetector,
    YOLOPlateRegionDetector,
)


class OCRClient(Protocol):
    def recognize(self, crops: tuple[bytes, ...]) -> tuple[tuple[str, float], ...]: ...


class PlateRecognitionUseCase(Protocol):
    def recognize(self, vehicle_images: tuple[bytes, ...]) -> PlateRecognition: ...


class PlateRecognitionService:
    def __init__(
        self,
        options: PlateRecognitionOptions,
        ocr_client: OCRClient | None = None,
        region_detector: PlateRegionDetector | YOLOPlateRegionDetector | None = None,
    ) -> None:
        self.options = options
        self.ocr_client = ocr_client or PaddleOCRSubprocess(options)
        self.region_detector = region_detector or (
            YOLOPlateRegionDetector(options)
            if options.detector_model_path is not None
            else PlateRegionDetector()
        )

    def recognize(self, vehicle_images: tuple[bytes, ...]) -> PlateRecognition:
        images = vehicle_images[-self.options.max_samples :]
        crops: list[bytes] = []
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
            regions = self.region_detector.detect(image)
            if not regions:
                continue
            for region in regions[: self.options.max_regions]:
                crop = image[region.y1 : region.y2, region.x1 : region.x2]
                if crop.size == 0:
                    continue
                scale = min(3.0, 900 / max(crop.shape[:2]))
                if scale > 1:
                    crop = cv2.resize(
                        crop,
                        None,
                        fx=scale,
                        fy=scale,
                        interpolation=cv2.INTER_CUBIC,
                    )
                success, result = cv2.imencode(".png", crop)
                if success:
                    crops.append(result.tobytes())
                    source_indices.append(source_index)

        if not crops:
            return PlateRecognition((), None, None, None, len(images))

        raw_results = self.ocr_client.recognize(tuple(crops))
        if len(raw_results) != len(crops):
            raise PlateOCRFailure("Số kết quả OCR không khớp số vùng biển đã gửi.")
        observations: list[PlateOCRObservation] = []
        votes: dict[str, dict[int, tuple[float, int]]] = defaultdict(dict)
        for index, (raw_text, confidence) in enumerate(raw_results[: len(crops)]):
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
        # OCR receives lossless PNG; the existing evidence/UI contract is JPEG.
        evidence = cv2.imdecode(np.frombuffer(crops[best_index], dtype=np.uint8), cv2.IMREAD_COLOR)
        success, encoded = cv2.imencode(".jpg", evidence, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not success:
            raise PlateOCRFailure("Không mã hóa được ảnh bằng chứng biển số.")
        return PlateRecognition(
            observations=tuple(observations),
            proposed_plate=proposed,
            confidence=average_confidence,
            plate_image_data=encoded.tobytes(),
            samples_considered=len(images),
        )
