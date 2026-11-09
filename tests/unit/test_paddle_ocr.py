import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from parking_app.domain.plate import PlateRecognitionOptions
from parking_app.infrastructure.vision.paddle_ocr import (
    PaddleOCRSubprocess,
    PlateOCRFailure,
)


def options(tmp_path: Path) -> PlateRecognitionOptions:
    return PlateRecognitionOptions(
        python_path=tmp_path / "python.exe",
        worker_path=tmp_path / "scripts" / "ocr_worker.py",
        cache_dir=tmp_path / "cache",
    )


def test_paddle_ocr_bridge_parses_json_marker_after_runtime_logs(tmp_path, monkeypatch):
    def fake_run(*_args, **_kwargs):
        payload = {"results": [{"text": "51A12345", "confidence": 0.95}]}
        return SimpleNamespace(
            returncode=0,
            stdout=f"runtime log\nPARKING_OCR_RESULT:{json.dumps(payload)}\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = PaddleOCRSubprocess(options(tmp_path)).recognize((b"jpeg-data",))

    assert result == (("51A12345", 0.95),)


def test_paddle_ocr_bridge_surfaces_timeout(tmp_path, monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ocr", 30)

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(PlateOCRFailure, match="thời gian chờ"):
        PaddleOCRSubprocess(options(tmp_path)).recognize((b"jpeg-data",))
