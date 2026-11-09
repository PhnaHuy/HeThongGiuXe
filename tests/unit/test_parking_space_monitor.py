import pytest

from parking_app.application.parking_space_monitor import ParkingSpaceMonitor
from parking_app.domain.enums import VehicleType
from parking_app.domain.exceptions import ValidationError
from parking_app.domain.video import (
    ParkingSpace,
    ParkingSpaceStatus,
    SourceConfig,
    SourceKind,
    SourcePurpose,
)
from parking_app.domain.vision import VehicleDetection

SPACE = ParkingSpace(
    "A01",
    ((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)),
)


def detection(box=(0.4, 0.4, 0.6, 0.6)):
    return VehicleDetection(*box, 0.9, VehicleType.MOTORCYCLE, 1)


@pytest.mark.parametrize(
    "points",
    [
        ((0.1, 0.1), (0.9, 0.9), (0.1, 0.9), (0.9, 0.1)),
        ((0.1, 0.1), (0.9, 0.1), (0.5, 0.1)),
        ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.1)),
        ((0.1, 0.1, 0.5), (0.9, 0.1), (0.9, 0.9)),
    ],
)
def test_invalid_parking_polygons_are_rejected(points):
    with pytest.raises(ValidationError):
        ParkingSpace("A01", points).validate()


def test_parking_spaces_only_belong_to_parking_sources():
    config = SourceConfig(
        "cam",
        "Camera",
        SourceKind.LIVE,
        "0",
        purpose=SourcePurpose.PARKING,
        parking_spaces=(SPACE,),
    )
    config.validate()

    with pytest.raises(ValidationError, match="khu đỗ"):
        SourceConfig(
            "gate",
            "Cổng",
            SourceKind.LIVE,
            "0",
            parking_spaces=(SPACE,),
        ).validate()

    with pytest.raises(ValidationError, match="không được trùng"):
        SourceConfig(
            "duplicate",
            "Khu đỗ",
            SourceKind.LIVE,
            "0",
            purpose=SourcePurpose.PARKING,
            parking_spaces=(
                SPACE,
                ParkingSpace("a01", ((0.1, 0.6), (0.4, 0.6), (0.4, 0.9), (0.1, 0.9))),
            ),
        ).validate()


def test_polygon_rejects_self_intersecting_edges():
    with pytest.raises(ValidationError, match="tự giao"):
        ParkingSpace(
            "A01",
            ((0.0, 0.0), (1.0, 1.0), (0.2, 0.5), (1.0, 0.1)),
        ).validate()


def test_monitor_requires_stable_detections_before_reporting_occupancy():
    monitor = ParkingSpaceMonitor((SPACE,), stable_frames=2)

    assert monitor.update((100, 100, 3), (detection(),)) == {"A01": ParkingSpaceStatus.UNKNOWN}
    assert monitor.update((100, 100, 3), (detection(),)) == {"A01": ParkingSpaceStatus.OCCUPIED}
    assert monitor.update((100, 100, 3), ()) == {"A01": ParkingSpaceStatus.UNKNOWN}
    assert monitor.update((100, 100, 3), ()) == {"A01": ParkingSpaceStatus.FREE}


def test_monitor_resets_to_unknown_after_missing_data_and_requires_fresh_frames():
    monitor = ParkingSpaceMonitor((SPACE,), stable_frames=2)
    monitor.update((100, 100, 3), (detection(),))
    monitor.update((100, 100, 3), (detection(),))

    assert monitor.update(None, ()) == {"A01": ParkingSpaceStatus.UNKNOWN}
    assert monitor.update((100, 100, 3), (detection(),)) == {"A01": ParkingSpaceStatus.UNKNOWN}
    assert monitor.update((100, 100, 3), (detection(),)) == {"A01": ParkingSpaceStatus.OCCUPIED}


def test_detection_outside_polygon_does_not_mark_space_occupied():
    monitor = ParkingSpaceMonitor((SPACE,), stable_frames=1)

    assert monitor.update((100, 100, 3), (detection((0.0, 0.0, 0.1, 0.1)),)) == {
        "A01": ParkingSpaceStatus.FREE
    }
