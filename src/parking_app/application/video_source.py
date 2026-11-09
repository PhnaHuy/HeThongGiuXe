"""VideoSource port and failures shared by adapters and playback worker."""

from typing import Any, Protocol


class VideoError(Exception):
    """Sanitized failure; never include the camera URL."""


class VideoCancelled(VideoError):
    pass


class VideoSource(Protocol):
    fps: float
    frame_count: int

    def open(self) -> None: ...

    def read(self) -> tuple[int, float | None, Any] | None: ...

    def seek(self, frame_index: int) -> None: ...

    def close(self) -> None: ...
