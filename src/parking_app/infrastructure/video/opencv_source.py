"""OpenCV source, owned exclusively by the capture child process."""

import math
from pathlib import Path

import cv2

from parking_app.application.video_source import VideoError
from parking_app.domain.video import SourceConfig, SourceKind, VideoOptions


class OpenCVVideoSource:
    def __init__(self, config: SourceConfig, options: VideoOptions) -> None:
        self.config = config
        self.options = options
        self.capture = None
        self.fps = options.fallback_fps
        self.frame_count = 0
        self.next_index = 0

    def open(self) -> None:
        self.close()
        self.config.validate()
        endpoint = self.config.endpoint.strip()
        if self.config.kind == SourceKind.MP4 and not Path(endpoint).is_file():
            raise VideoError("Không tìm thấy tệp MP4.")
        self.capture = cv2.VideoCapture()
        if self.config.kind == SourceKind.LIVE and endpoint.isdecimal():
            opened = self.capture.open(int(endpoint))
        elif self.config.kind == SourceKind.MP4:
            opened = self.capture.open(
                endpoint,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    int(self.options.open_timeout_s * 1000),
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    int(self.options.read_timeout_s * 1000),
                ],
            )
        else:
            # Some HTTP/MJPEG streams and OpenCV builds cannot be opened by
            # FFmpeg with timeout parameters. The parent process still bounds
            # this fallback if a native backend blocks.
            try:
                opened = self.capture.open(
                    endpoint,
                    cv2.CAP_FFMPEG,
                    [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                        int(self.options.open_timeout_s * 1000),
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                        int(self.options.read_timeout_s * 1000),
                    ],
                )
            except cv2.error:
                opened = False
            if not opened:
                self.capture.release()
                self.capture = cv2.VideoCapture()
                opened = self.capture.open(endpoint, cv2.CAP_ANY)
        if not opened:
            raise VideoError("Không mở được nguồn. Kiểm tra tệp hoặc kết nối camera.")
        fps = self.capture.get(cv2.CAP_PROP_FPS)
        self.fps = fps if math.isfinite(fps) and 0 < fps <= 240 else self.options.fallback_fps
        count = self.capture.get(cv2.CAP_PROP_FRAME_COUNT)
        self.frame_count = max(0, int(count)) if math.isfinite(count) else 0
        self.next_index = 0

    def read(self):
        if self.capture is None:
            raise VideoError("Nguồn chưa được mở.")
        ok, image = self.capture.read()
        if not ok or image is None or image.size == 0:
            if self.config.kind == SourceKind.LIVE:
                raise VideoError("Camera không cung cấp khung hình mới.")
            if self.next_index == 0 or (self.frame_count and self.next_index < self.frame_count):
                raise VideoError("Không giải mã được video hoặc video kết thúc sớm.")
            return None
        index = self.next_index
        self.next_index += 1
        media_time = None
        if self.config.kind == SourceKind.MP4:
            milliseconds = self.capture.get(cv2.CAP_PROP_POS_MSEC)
            media_time = milliseconds / 1000 if milliseconds > 0 else index / self.fps
        return index, media_time, image

    def seek(self, frame_index: int) -> None:
        if self.config.kind != SourceKind.MP4 or self.capture is None:
            raise VideoError("Chỉ có thể tua tệp MP4 đã mở.")
        if frame_index < 0 or (self.frame_count and frame_index >= self.frame_count):
            raise VideoError("Vị trí tua nằm ngoài video.")
        if not self.capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index):
            raise VideoError("Nguồn không hỗ trợ tua tới vị trí này.")
        actual = self.capture.get(cv2.CAP_PROP_POS_FRAMES)
        self.next_index = max(0, int(actual))

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
