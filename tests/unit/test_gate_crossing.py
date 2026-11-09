import pytest

from parking_app.application.gate_crossing import GateCrossingTracker
from parking_app.domain.enums import VehicleType
from parking_app.domain.video import GateLine
from parking_app.domain.vision import GateDirection, VehicleDetection


def detection(track_id: int, center_y: float) -> VehicleDetection:
    return VehicleDetection(
        x1=0.45,
        y1=center_y - 0.05,
        x2=0.55,
        y2=center_y + 0.05,
        confidence=0.9,
        vehicle_type=VehicleType.MOTORCYCLE,
        track_id=track_id,
    )


@pytest.mark.parametrize(
    ("entry_positive", "start_y", "end_y", "expected"),
    [
        (True, 0.3, 0.7, GateDirection.ENTRY),
        (True, 0.7, 0.3, GateDirection.EXIT),
        (False, 0.3, 0.7, GateDirection.EXIT),
        (False, 0.7, 0.3, GateDirection.ENTRY),
    ],
)
def test_stable_crossing_obeys_configured_entry_direction(entry_positive, start_y, end_y, expected):
    tracker = GateCrossingTracker(stable_frames=2)
    line = GateLine(0.1, 0.5, 0.9, 0.5, entry_positive=entry_positive)
    assert tracker.update([detection(1, start_y)], line, 1) == []
    assert tracker.update([detection(1, start_y)], line, 2) == []
    assert tracker.update([detection(1, end_y)], line, 3) == []
    assert tracker.update([detection(1, end_y)], line, 4) == [(detection(1, end_y), expected)]


def test_line_jitter_does_not_create_event_and_same_direction_is_emitted_once():
    tracker = GateCrossingTracker(stable_frames=2)
    line = GateLine()
    sequence = [
        detection(4, 0.3),
        detection(4, 0.3),
        detection(4, 0.505),
        detection(4, 0.495),
        detection(4, 0.3),
        detection(4, 0.3),
        detection(4, 0.7),
        detection(4, 0.7),
        detection(4, 0.3),
        detection(4, 0.3),
    ]
    events = []
    for frame_index, observation in enumerate(sequence, start=1):
        events.extend(tracker.update([observation], line, frame_index))
    assert [direction for _, direction in events] == [
        GateDirection.ENTRY,
        GateDirection.EXIT,
    ]


def test_untracked_detections_are_not_counted_and_reset_clears_session_state():
    tracker = GateCrossingTracker(stable_frames=1)
    line = GateLine()
    assert tracker.update([detection(1, 0.3)], line, 1) == []
    no_id = detection(1, 0.7)
    no_id = VehicleDetection(
        no_id.x1,
        no_id.y1,
        no_id.x2,
        no_id.y2,
        no_id.confidence,
        no_id.vehicle_type,
        None,
    )
    assert tracker.update([no_id], line, 2) == []

    tracker.update([detection(1, 0.3)], line, 3)
    tracker.update([detection(1, 0.3)], line, 4)
    tracker.reset()
    assert tracker.update([detection(1, 0.7)], line, 5) == []


def test_crossing_configuration_is_validated():
    with pytest.raises(ValueError, match="Cấu hình"):
        GateCrossingTracker(deadband=0.5)
