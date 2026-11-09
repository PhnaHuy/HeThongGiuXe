"""Bound capture calls even when a native camera driver ignores OpenCV timeouts.

Only decoding runs in a local child process. It has no database/service access.
The QThread supervisor can cancel it without terminating a Qt thread.
"""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from collections.abc import Callable

from parking_app.application.video_source import VideoCancelled, VideoError
from parking_app.domain.video import SourceConfig, SourceKind, VideoOptions


class _LatestLiveFrame:
    """Continuously drain the decoder while consumers process the newest frame."""

    def __init__(self, source) -> None:
        self.source = source
        self.condition = threading.Condition()
        self.latest = None
        self.sequence = 0
        self.delivered = 0
        self.error = None
        self.stopped = False
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.thread.start()

    def _capture(self) -> None:
        try:
            while True:
                result = self.source.read()
                if result is None:
                    raise VideoError("Camera ng?ng cung c?p h?nh.")
                with self.condition:
                    if self.stopped:
                        return
                    self.latest = result
                    self.sequence += 1
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error = exc
                self.condition.notify_all()

    def read(self):
        with self.condition:
            while self.sequence == self.delivered and self.error is None and not self.stopped:
                self.condition.wait()
            if self.error is not None:
                raise VideoError("Camera kh?ng cung c?p khung h?nh m?i.") from self.error
            if self.stopped:
                raise VideoError("Ngu?n camera ?? d?ng.")
            self.delivered = self.sequence
            return self.latest

    def stop(self) -> None:
        with self.condition:
            self.stopped = True
            self.condition.notify_all()

def capture_process(connection, config: SourceConfig, options: VideoOptions) -> None:
    # Native FFmpeg/OpenCV can print URLs on errors, bypassing Python logging.
    with open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), 2)
    from parking_app.infrastructure.video.opencv_source import OpenCVVideoSource

    source = OpenCVVideoSource(config, options)
    live_reader = None
    try:
        while True:
            command, value = connection.recv()
            try:
                if command == "open":
                    source.open()
                    if config.kind == SourceKind.LIVE:
                        live_reader = _LatestLiveFrame(source)
                    result = (source.fps, source.frame_count)
                elif command == "read":
                    result = live_reader.read() if live_reader is not None else source.read()
                elif command == "seek":
                    source.seek(value)
                    result = None
                elif command == "close":
                    break
                else:
                    raise VideoError("Lệnh nguồn hình không hợp lệ.")
                connection.send((True, result))
            except VideoError as exc:
                connection.send((False, str(exc)))
            except Exception:
                connection.send((False, "Không xử lý được nguồn hình."))
    except (EOFError, BrokenPipeError, OSError):
        pass  # Parent closed the private IPC channel during cancellation.
    finally:
        if live_reader is not None:
            live_reader.stop()
        source.close()
        connection.close()


class IsolatedVideoSource:
    def __init__(
        self,
        config: SourceConfig,
        options: VideoOptions,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.config = config
        self.options = options
        self.cancelled = cancelled
        self.process = None
        self.connection = None
        self.fps = options.fallback_fps
        self.frame_count = 0

    def open(self) -> None:
        self.close()
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=capture_process,
            args=(child, self.config, self.options),
            daemon=True,
        )
        try:
            self.process.start()
            child.close()
            self.fps, self.frame_count = self._request("open", None, self.options.open_timeout_s)
        except Exception:
            child.close()
            self.close()
            raise

    def _request(self, command: str, value, timeout: float):
        if self.connection is None:
            raise VideoError("Nguồn chưa được mở.")
        deadline = time.monotonic() + timeout
        try:
            self.connection.send((command, value))
            while time.monotonic() < deadline:
                if self.cancelled():
                    raise VideoCancelled("Đã hủy đọc nguồn.")
                if self.connection.poll(0.05):
                    success, result = self.connection.recv()
                    if not success:
                        raise VideoError(result)
                    return result
                if self.process is None or not self.process.is_alive():
                    raise VideoError("Tiến trình đọc hình đã dừng.")
        except (EOFError, BrokenPipeError, OSError) as exc:
            raise VideoError("Mất kết nối với tiến trình đọc hình.") from exc
        raise VideoError("Quá thời gian chờ nguồn hình.")

    def read(self):
        return self._request("read", None, self.options.read_timeout_s)

    def seek(self, frame_index: int) -> None:
        self._request("seek", frame_index, self.options.read_timeout_s)

    def close(self) -> None:
        process, connection = self.process, self.connection
        self.process = self.connection = None
        if connection is not None:
            try:
                connection.send(("close", None))
            except (OSError, EOFError):
                pass  # Capture process may already have exited after a decoder failure.
            connection.close()
        if process is not None and process.pid is not None:
            process.join(0.2)
            if process.is_alive():
                process.terminate()
                process.join(1)
            if process.is_alive():
                process.kill()
                process.join(1)
            process.close()
