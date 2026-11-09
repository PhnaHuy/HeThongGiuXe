"""Local learned plate detection and a geometry baseline for vehicle crops."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from parking_app.domain.plate import PlateRecognitionOptions
from parking_app.infrastructure.vision.paddle_ocr import PlateOCRFailure


@dataclass(frozen=True)
class PlateRegion:
    x1: int
    y1: int
    x2: int
    y2: int
    score: float


class YOLOPlateRegionDetector:
    """Lazy local plate-only model; initialization happens on the OCR worker."""

    def __init__(self, options: PlateRecognitionOptions) -> None:
        self.options = options
        self.model = None

    def detect(self, image: np.ndarray) -> tuple[PlateRegion, ...]:
        if self.model is None:
            path = self.options.detector_model_path
            if path is None or not Path(path).is_file():
                raise PlateOCRFailure(f"Thiếu model phát hiện biển số cục bộ: {path}")
            try:
                from ultralytics import YOLO

                model = YOLO(str(path))
                if len(model.names) != 1:
                    raise ValueError(
                        "Cần model một lớp biển số, không dùng model COCO nhận diện xe."
                    )
                self.model = model
            except Exception as exc:
                raise PlateOCRFailure(f"Không nạp được detector biển số: {exc}") from exc
        try:
            results = self.model.predict(
                image,
                conf=self.options.detector_confidence,
                imgsz=self.options.detector_image_size,
                device=self.options.detector_device,
                max_det=self.options.max_regions,
                verbose=False,
            )
        except Exception as exc:
            raise PlateOCRFailure("Không chạy được detector biển số.") from exc
        if not results or results[0].boxes is None:
            return ()
        height, width = image.shape[:2]
        regions = []
        for box in results[0].boxes.data.cpu().tolist():
            x1, y1, x2, y2, confidence, _class_id = box
            # Leave a small border so OCR does not clip edge characters.
            pad_x, pad_y = (x2 - x1) * 0.04, (y2 - y1) * 0.08
            region = PlateRegion(
                max(0, int(x1 - pad_x)),
                max(0, int(y1 - pad_y)),
                min(width, int(np.ceil(x2 + pad_x))),
                min(height, int(np.ceil(y2 + pad_y))),
                float(confidence),
            )
            if region.x2 > region.x1 and region.y2 > region.y1:
                regions.append(region)
        return tuple(sorted(regions, key=lambda item: item.score, reverse=True))


class PlateRegionDetector:
    """Propose likely one- or two-row plate regions using image geometry."""

    def detect(self, image: np.ndarray) -> tuple[PlateRegion, ...]:
        if image.ndim != 3 or image.shape[0] < 16 or image.shape[1] < 24:
            return ()

        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(gray, 50, 150)
        kernel_width = max(5, min(31, width // 12))
        kernel_height = max(2, min(7, height // 40))
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (kernel_width, kernel_height),
        )
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(
            closed,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        image_area = width * height
        regions: list[PlateRegion] = []

        for contour in contours:
            x, y, region_width, region_height = cv2.boundingRect(contour)
            area = region_width * region_height
            aspect_ratio = region_width / region_height
            area_ratio = area / image_area
            if (
                region_width < max(18, round(width * 0.12))
                or region_height < max(7, round(height * 0.045))
                or aspect_ratio < 0.7
                or aspect_ratio > 6.0
                or area_ratio < 0.002
                or area_ratio > 0.4
            ):
                continue

            roi_edges = edges[y : y + region_height, x : x + region_width]
            edge_density = cv2.countNonZero(roi_edges) / max(1, area)
            ratio_distance = min(
                abs(np.log(aspect_ratio / 3.2)),
                abs(np.log(aspect_ratio / 1.15)),
            )
            aspect_score = float(np.exp(-ratio_distance))
            texture_score = min(1.0, edge_density / 0.18)
            area_score = min(1.0, area_ratio / 0.08)
            score = 0.5 * aspect_score + 0.35 * texture_score + 0.15 * area_score
            padding_x = max(2, round(region_width * 0.04))
            padding_y = max(2, round(region_height * 0.08))
            regions.append(
                PlateRegion(
                    x1=max(0, x - padding_x),
                    y1=max(0, y - padding_y),
                    x2=min(width, x + region_width + padding_x),
                    y2=min(height, y + region_height + padding_y),
                    score=score,
                )
            )

        return tuple(sorted(regions, key=lambda item: item.score, reverse=True)[:2])
