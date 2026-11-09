"""Stable, direction-aware gate crossing detection for tracked vehicles."""

from __future__ import annotations

from dataclasses import dataclass, field

from parking_app.domain.video import GateLine
from parking_app.domain.vision import GateDirection, VehicleDetection


@dataclass
class _TrackState:
    stable_side: int | None = None
    pending_side: int | None = None
    pending_count: int = 0
    last_seen_frame: int = 0
    emitted_directions: set[GateDirection] = field(default_factory=set)


class GateCrossingTracker:
    """Debounce signed-side changes and emit at most one event per track/direction."""

    def __init__(
        self,
        *,
        deadband: float = 0.015,
        stable_frames: int = 2,
        stale_track_frames: int = 300,
    ) -> None:
        if not 0 <= deadband < 0.5 or stable_frames < 1 or stale_track_frames < stable_frames:
            raise ValueError("Cấu hình chống rung vạch không hợp lệ.")
        self.deadband = deadband
        self.stable_frames = stable_frames
        self.stale_track_frames = stale_track_frames
        self._tracks: dict[int, _TrackState] = {}

    def reset(self) -> None:
        self._tracks.clear()

    def update(
        self,
        detections: tuple[VehicleDetection, ...] | list[VehicleDetection],
        line: GateLine | None,
        frame_index: int,
    ) -> list[tuple[VehicleDetection, GateDirection]]:
        if line is None:
            return []
        line.validate()
        events: list[tuple[VehicleDetection, GateDirection]] = []
        for detection in detections:
            if detection.track_id is None:
                continue
            state = self._tracks.setdefault(detection.track_id, _TrackState())
            state.last_seen_frame = frame_index
            side = self._stable_side(detection, line)
            if side is None:
                state.pending_side = None
                state.pending_count = 0
                continue
            if side == state.stable_side:
                state.pending_side = None
                state.pending_count = 0
                continue
            if side == state.pending_side:
                state.pending_count += 1
            else:
                state.pending_side = side
                state.pending_count = 1
            if state.pending_count < self.stable_frames:
                continue

            previous_side = state.stable_side
            state.stable_side = side
            state.pending_side = None
            state.pending_count = 0
            if previous_side is None:
                continue

            entering = side > 0 if line.entry_positive else side < 0
            direction = GateDirection.ENTRY if entering else GateDirection.EXIT
            if direction not in state.emitted_directions:
                state.emitted_directions.add(direction)
                events.append((detection, direction))

        oldest_frame = frame_index - self.stale_track_frames
        self._tracks = {
            track_id: state
            for track_id, state in self._tracks.items()
            if state.last_seen_frame >= oldest_frame
        }
        return events

    def _stable_side(self, detection: VehicleDetection, line: GateLine) -> int | None:
        center_x = (detection.x1 + detection.x2) / 2
        center_y = (detection.y1 + detection.y2) / 2
        line_dx = line.x2 - line.x1
        line_dy = line.y2 - line.y1
        line_length = (line_dx**2 + line_dy**2) ** 0.5
        signed_distance = (
            line_dx * (center_y - line.y1) - line_dy * (center_x - line.x1)
        ) / line_length
        if signed_distance > self.deadband:
            return 1
        if signed_distance < -self.deadband:
            return -1
        return None
