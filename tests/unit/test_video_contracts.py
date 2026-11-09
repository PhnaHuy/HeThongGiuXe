import math

import pytest

from parking_app.domain.exceptions import ValidationError
from parking_app.domain.video import GateLine, SourceConfig, SourceKind, VideoOptions


@pytest.mark.parametrize(
    "line", [GateLine(0, 0, 0, 0), GateLine(-1, 0, 1, 0), GateLine(math.nan, 0, 1, 0)]
)
def test_invalid_gate_line_is_rejected(line):
    with pytest.raises(ValidationError):
        line.validate()


@pytest.mark.parametrize(
    "kind, endpoint",
    [(SourceKind.LIVE, "movie.mp4"), (SourceKind.LIVE, "-1"), (SourceKind.MP4, "clip.avi")],
)
def test_source_kind_cannot_disguise_a_file_as_live(kind, endpoint):
    with pytest.raises(ValidationError):
        SourceConfig("source1", "Cổng", kind, endpoint).validate()


def test_source_repr_does_not_expose_credentials():
    config = SourceConfig("cam", "Cổng", SourceKind.LIVE, "rtsp://user:secret@host/live")
    config.validate()
    assert "secret" not in repr(config)


@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan])
def test_video_options_reject_unbounded_or_negative_timeouts(value):
    with pytest.raises(ValidationError):
        VideoOptions(read_timeout_s=value)
