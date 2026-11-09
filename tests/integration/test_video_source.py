import multiprocessing
import threading
import time

import cv2
import numpy as np
import pytest

from parking_app.application.video_source import VideoCancelled, VideoError
from parking_app.domain.video import SourceConfig, SourceKind, VideoOptions
from parking_app.infrastructure.video.isolated_source import IsolatedVideoSource, _LatestLiveFrame
from parking_app.infrastructure.video.opencv_source import OpenCVVideoSource


def test_live_reader_discards_old_frames_while_consumer_is_busy():
    class ControlledSource:
        def __init__(self):
            self.permits = threading.Semaphore(0)
            self.count = 0

        def read(self):
            self.permits.acquire()
            self.count += 1
            return (self.count, None, self.count)

    source = ControlledSource()
    reader = _LatestLiveFrame(source)
    try:
        source.permits.release()
        assert reader.read()[0] == 1
        for _ in range(5):
            source.permits.release()
        with reader.condition:
            assert reader.condition.wait_for(lambda: reader.sequence == 6, timeout=2)
        assert reader.read()[0] == 6
    finally:
        reader.stop()
        source.permits.release()
        reader.thread.join(2)


def test_camera_url_retries_with_automatic_backend(monkeypatch):
    calls = []

    class Capture:
        def open(self, *args):
            calls.append(args)
            return len(calls) == 2

        def release(self):
            pass

        def get(self, prop):
            return 0

    monkeypatch.setattr(cv2, "VideoCapture", Capture)
    url = "rtsp://tuan:tuan123@192.168.1.150:8554/live"
    source = OpenCVVideoSource(SourceConfig("cam", "Camera", SourceKind.LIVE, url), VideoOptions())
    source.open()
    assert calls[0][0:2] == (url, cv2.CAP_FFMPEG)
    assert calls[1] == (url, cv2.CAP_ANY)
    source.close()


def test_webcam_index_is_opened_as_integer(monkeypatch):
    calls = []

    class Capture:
        def open(self, *args):
            calls.append(args)
            return True

        def release(self):
            pass

        def get(self, prop):
            return 0

    monkeypatch.setattr(cv2, "VideoCapture", Capture)
    source = OpenCVVideoSource(SourceConfig("cam", "Camera", SourceKind.LIVE, "2"), VideoOptions())
    source.open()
    assert calls == [(2,)]
    source.close()


@pytest.fixture
def mp4_path(tmp_path):
    path = tmp_path / "generated.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 20, (160, 96))
    assert writer.isOpened(), "MP4 fixture encoder is unavailable"
    for index in range(12):
        writer.write(np.full((96, 160, 3), index * 15, dtype=np.uint8))
    writer.release()
    return path


def test_isolated_decoder_reads_all_frames_eof_and_seek(mp4_path):
    source = IsolatedVideoSource(
        SourceConfig("file", "Demo", SourceKind.MP4, str(mp4_path)), VideoOptions()
    )
    try:
        source.open()
        pid = source.process.pid
        assert source.frame_count == 12
        frames = [source.read() for _ in range(12)]
        assert [frame[0] for frame in frames] == list(range(12))
        assert frames[-1][1] > frames[0][1]
        assert frames[0][2].shape == (96, 160, 3)
        assert source.read() is None
        source.seek(4)
        assert source.read()[0] == 4
    finally:
        source.close()
    assert pid not in [p.pid for p in multiprocessing.active_children()]


def test_corrupt_mp4_is_error_not_eof(tmp_path):
    path = tmp_path / "broken.mp4"
    path.write_bytes(b"not a video")
    source = IsolatedVideoSource(
        SourceConfig("bad", "Broken", SourceKind.MP4, str(path)), VideoOptions()
    )
    try:
        with pytest.raises(VideoError):
            source.open()
    finally:
        source.close()


def test_cancel_decoder_does_not_leave_child(mp4_path):
    cancelled = False
    source = IsolatedVideoSource(
        SourceConfig("file", "Demo", SourceKind.MP4, str(mp4_path)),
        VideoOptions(),
        lambda: cancelled,
    )
    source.open()
    pid = source.process.pid
    cancelled = True
    start = time.monotonic()
    try:
        with pytest.raises(VideoCancelled):
            source.read()
    finally:
        source.close()
    assert time.monotonic() - start < 3
    assert pid not in [p.pid for p in multiprocessing.active_children()]


def _unresponsive_decoder(connection):
    connection.recv()
    time.sleep(15)


@pytest.mark.parametrize("cancel", [False, True])
def test_unresponsive_native_decoder_is_bounded_and_reaped(cancel):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_unresponsive_decoder, args=(child,), daemon=True)
    process.start()
    child.close()
    started = time.monotonic()
    source = IsolatedVideoSource(
        SourceConfig("fake", "Camera treo giả lập", SourceKind.LIVE, "0"),
        VideoOptions(read_timeout_s=0.3),
        lambda: cancel and time.monotonic() - started >= 0.1,
    )
    source.process, source.connection = process, parent
    pid = process.pid
    try:
        with pytest.raises(VideoCancelled if cancel else VideoError):
            source.read()
    finally:
        source.close()
    assert time.monotonic() - started < 3
    assert pid not in [p.pid for p in multiprocessing.active_children()]
