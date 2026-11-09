"""Stable per-polygon occupancy estimates derived from detected plate regions."""

from __future__ import annotations

from collections import deque

import cv2
import numpy as np

from parking_app.domain.video import ParkingSpace, ParkingSpaceStatus
from parking_app.domain.vision import PlateDetection


class ParkingSpaceMonitor:
    """Apply temporal stability and conservative unknown-state handling."""

    def __init__(
        self,
        spaces: tuple[ParkingSpace, ...],
        stable_frames: int = 3,
        overlap_threshold: float = 0.15,
    ) -> None:
        if stable_frames < 1:
            raise ValueError("stable_frames must be positive")
        if not 0 < overlap_threshold <= 1:
            raise ValueError("overlap_threshold must be between zero and one")
        self.spaces = spaces
        self.stable_frames = stable_frames
        self.overlap_threshold = overlap_threshold
        self._history: dict[str, deque[bool]] = {
            space.code: deque(maxlen=stable_frames) for space in spaces
        }
        self._states = {space.code: ParkingSpaceStatus.UNKNOWN for space in spaces}

    @property
    def states(self) -> dict[str, ParkingSpaceStatus]:
        return dict(self._states)

    def reset(self) -> dict[str, ParkingSpaceStatus]:
        for history in self._history.values():
            history.clear()
        self._states = {space.code: ParkingSpaceStatus.UNKNOWN for space in self.spaces}
        return self.states

    def update(
        self,
        image_shape: tuple[int, ...] | None,
        detections: tuple[PlateDetection, ...] | None,
    ) -> dict[str, ParkingSpaceStatus]:
        if image_shape is None or detections is None or len(image_shape) < 2:
            return self.reset()
        height, width = image_shape[:2]
        if height <= 0 or width <= 0:
            return self.reset()

        for space in self.spaces:
            contour = np.asarray(
                [(round(x * (width - 1)), round(y * (height - 1))) for x, y in space.points],
                dtype=np.int32,
            )
            occupied_now = any(
                self._overlap_ratio(contour, width, height, detection) >= self.overlap_threshold
                or cv2.pointPolygonTest(
                    contour,
                    (
                        (detection.x1 + detection.x2) * width / 2,
                        (detection.y1 + detection.y2) * height / 2,
                    ),
                    False,
                )
                >= 0
                for detection in detections
                if self._valid_detection(detection)
            )
            history = self._history[space.code]
            history.append(occupied_now)
            if len(history) == self.stable_frames and all(history):
                self._states[space.code] = ParkingSpaceStatus.OCCUPIED
            elif len(history) == self.stable_frames and not any(history):
                self._states[space.code] = ParkingSpaceStatus.FREE
            else:
                self._states[space.code] = ParkingSpaceStatus.UNKNOWN
        return self.states

    @staticmethod
    def _valid_detection(detection: PlateDetection) -> bool:
        return (
            all(
                np.isfinite(value)
                for value in (detection.x1, detection.y1, detection.x2, detection.y2)
            )
            and 0 <= detection.x1 < detection.x2 <= 1
            and 0 <= detection.y1 < detection.y2 <= 1
        )

    @staticmethod
    def _overlap_ratio(
        contour: np.ndarray,
        width: int,
        height: int,
        detection: PlateDetection,
    ) -> float:
        x1 = max(0, min(width, int(detection.x1 * width)))
        y1 = max(0, min(height, int(detection.y1 * height)))
        x2 = max(x1 + 1, min(width, int(np.ceil(detection.x2 * width))))
        y2 = max(y1 + 1, min(height, int(np.ceil(detection.y2 * height))))
        roi = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
        shifted = contour.copy()
        shifted[:, 0] -= x1
        shifted[:, 1] -= y1
        cv2.fillPoly(roi, [shifted], 1)
        return float(np.count_nonzero(roi) / roi.size)
