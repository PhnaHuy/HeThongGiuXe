"""G0 smoke checks using synthetic media; these do not measure model accuracy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DETECTION_MODEL = "PP-OCRv5_mobile_det"
RECOGNITION_MODEL = "PP-OCRv5_mobile_rec"
SYNTHETIC_TEXT = "DEMO 12345"


class CheckBlocked(RuntimeError):
    """A prerequisite is missing; this is not a passing check."""


def package_versions() -> dict[str, str]:
    """Read installed package metadata without importing optional runtimes."""
    packages = (
        "numpy",
        "opencv-python",
        "opencv-contrib-python",
        "torch",
        "ultralytics",
        "lap",
        "paddlepaddle",
        "paddleocr",
        "paddlex",
    )
    result = {}
    for package in packages:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            continue
    return result


def configure_local_caches() -> Path:
    """Keep third-party model/settings caches inside this workspace by default."""
    runtime = PROJECT_ROOT / ".runtime"
    defaults = {
        "PADDLE_PDX_CACHE_HOME": runtime / "paddlex",
        "PADDLE_HOME": runtime / "paddle",
        "HF_HOME": runtime / "huggingface",
        "TORCH_HOME": runtime / "torch",
        "YOLO_CONFIG_DIR": runtime / "ultralytics",
        "MPLCONFIGDIR": runtime / "matplotlib",
        "XDG_CACHE_HOME": runtime / "cache",
    }
    for key, path in defaults.items():
        os.environ.setdefault(key, str(path))
    # Never let Ultralytics mutate the environment by installing a missing package.
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault("YOLO_VERBOSE", "false")
    return Path(os.environ["PADDLE_PDX_CACHE_HOME"]) / "official_models"


def synthetic_frame(offset: int = 0) -> Any:
    """Create a clearly synthetic scene without customer or vehicle imagery."""
    import cv2
    import numpy as np

    frame = np.full((360, 640, 3), 235, dtype=np.uint8)
    cv2.rectangle(frame, (60 + offset, 140), (260 + offset, 260), (100, 80, 40), -1)
    cv2.putText(frame, "G0 SYNTHETIC", (25, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    return frame


def check_video(work_dir: Path) -> dict[str, Any]:
    """Verify actual MP4 encode/decode and distinguish EOF from valid frames."""
    import cv2

    work_dir.mkdir(parents=True, exist_ok=True)
    video_path = work_dir / "synthetic.mp4"
    expected_frames = 12
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 360))
    try:
        if not writer.isOpened():
            raise RuntimeError("OpenCV không mở được VideoWriter MP4/mp4v.")
        for index in range(expected_frames):
            writer.write(synthetic_frame(index * 4))
    finally:
        writer.release()

    capture = cv2.VideoCapture(str(video_path))
    actual_frames = 0
    try:
        if not capture.isOpened():
            raise RuntimeError("OpenCV không mở lại được MP4 vừa ghi.")
        while True:
            ok, frame = capture.read()
            if not ok:
                if frame is not None:
                    raise RuntimeError("EOF trả về khung hình không rỗng.")
                break
            if frame.shape != (360, 640, 3):
                raise RuntimeError(f"Kích thước khung không đúng: {frame.shape}.")
            actual_frames += 1
            if actual_frames > expected_frames:
                raise RuntimeError("Video trả về số khung lớn hơn fixture đã ghi.")
    finally:
        capture.release()
    if actual_frames != expected_frames:
        raise RuntimeError(f"Chỉ đọc được {actual_frames}/{expected_frames} khung.")
    return {
        "fixture": str(video_path),
        "synthetic": True,
        "frames_written": expected_frames,
        "frames_read": actual_frames,
        "eof_verified": True,
        "camera_tested": False,
    }


def check_yolo(model_path: Path) -> dict[str, Any]:
    """Run the configured local YOLO model on CPU without auto-downloading it."""
    if not model_path.is_file():
        raise CheckBlocked(f"Chưa có trọng số model tại {model_path}.")
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    frame = synthetic_frame()
    results = model.predict(frame, device="cpu", imgsz=320, verbose=False)
    if len(results) != 1:
        raise RuntimeError("YOLO không trả đúng một kết quả cho một khung hình.")
    counts = []
    for offset in (0, 4):
        tracked = model.track(
            synthetic_frame(offset),
            device="cpu",
            imgsz=320,
            tracker="bytetrack.yaml",
            persist=True,
            verbose=False,
        )
        if len(tracked) != 1:
            raise RuntimeError("Tracking không trả đúng một kết quả cho một khung hình.")
        counts.append(len(tracked[0].boxes))
    return {
        "model": str(model_path),
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "device": "cpu",
        "predict_result_count": len(results),
        "track_frame_detection_counts": counts,
        "synthetic": True,
        "limitation": "Frame tổng hợp có thể không có xe; không đánh giá độ chính xác phát hiện.",
    }


def check_bytetrack() -> dict[str, Any]:
    """Verify ID association with two synthetic boxes independently of YOLO."""
    import numpy as np
    import ultralytics
    from ultralytics.engine.results import Boxes
    from ultralytics.trackers.byte_tracker import BYTETracker
    from ultralytics.utils import YAML

    config = Path(ultralytics.__file__).parent / "cfg" / "trackers" / "bytetrack.yaml"
    tracker_args = SimpleNamespace(**YAML.load(str(config)))
    tracker = BYTETracker(tracker_args)
    ids = []
    for offset in (0, 4):
        boxes = Boxes(
            np.array([[60 + offset, 140, 260 + offset, 260, 0.95, 2]], dtype=np.float32),
            orig_shape=(360, 640),
        )
        tracks = tracker.update(boxes, img=synthetic_frame(offset))
        if len(tracks) != 1:
            raise RuntimeError(f"ByteTrack trả {len(tracks)} track thay vì một track.")
        ids.append(int(tracks[0, 4]))
    if ids[0] != ids[1]:
        raise RuntimeError(f"ByteTrack không giữ ID qua hai khung: {ids}.")
    return {
        "config": str(config),
        "track_ids": ids,
        "synthetic": True,
        "limitation": "Chỉ kiểm tra liên kết hai detection tổng hợp; chưa kiểm tra xe thực tế.",
    }


def check_ocr(work_dir: Path, model_root: Path, allow_download: bool) -> dict[str, Any]:
    """Run OCR on synthetic text; downloads require an explicit CLI option."""
    import cv2
    import numpy as np

    model_paths = {
        "text_detection_model_dir": model_root / DETECTION_MODEL,
        "text_recognition_model_dir": model_root / RECOGNITION_MODEL,
    }
    missing = [str(path) for path in model_paths.values() if not (path / "inference.yml").is_file()]
    if missing and not allow_download:
        raise CheckBlocked(
            "Thiếu model OCR cục bộ: "
            + ", ".join(missing)
            + ". Chỉ dùng --allow-model-download khi chủ động cho phép tải model chính thức."
        )
    # Import after checking local assets: some runtimes probe model hosts on import.
    try:
        import paddle.inference as pi

        if not getattr(pi, "_onednn_patched", False):
            orig_create_predictor = pi.create_predictor

            def safe_create_predictor(config):
                if hasattr(config, "disable_onednn"):
                    config.disable_onednn()
                return orig_create_predictor(config)

            pi.create_predictor = safe_create_predictor
            pi._onednn_patched = True
    except Exception:
        pass

    from paddleocr import PaddleOCR

    kwargs: dict[str, Any] = {
        "device": "cpu",
        "text_detection_model_name": DETECTION_MODEL,
        "text_recognition_model_name": RECOGNITION_MODEL,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    for key, path in model_paths.items():
        if (path / "inference.yml").is_file():
            kwargs[key] = str(path)
    ocr = PaddleOCR(**kwargs)
    image = np.full((180, 760, 3), 255, dtype=np.uint8)
    cv2.putText(image, SYNTHETIC_TEXT, (30, 115), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 0, 0), 5)
    work_dir.mkdir(parents=True, exist_ok=True)
    image_path = work_dir / "synthetic_text.png"
    if not cv2.imwrite(str(image_path), image):
        raise RuntimeError("Không lưu được ảnh tổng hợp dùng cho smoke OCR.")
    predictions = list(ocr.predict(image))
    if len(predictions) != 1:
        raise RuntimeError("OCR không trả đúng một kết quả cho một ảnh.")
    texts = [str(text) for text in predictions[0]["rec_texts"]]
    scores = [float(score) for score in predictions[0]["rec_scores"]]
    return {
        "device": "cpu",
        "detection_model": DETECTION_MODEL,
        "recognition_model": RECOGNITION_MODEL,
        "model_root": str(model_root),
        "model_download_requested": allow_download,
        "fixture": str(image_path),
        "synthetic": True,
        "expected_text": SYNTHETIC_TEXT,
        "recognized_texts": texts,
        "recognition_scores": scores,
        "limitation": "Chỉ chứng minh pipeline suy luận chạy; chưa đo OCR biển số Việt Nam.",
    }


def run_check(name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Report stages independently so one missing model does not hide other results."""
    started = time.perf_counter()
    try:
        result = {"name": name, "status": "passed", "details": operation()}
    except CheckBlocked as error:
        result = {"name": name, "status": "blocked", "error": str(error)}
    except Exception as error:
        result = {
            "name": name,
            "status": "failed",
            "error_type": type(error).__name__,
            "error": str(error),
        }
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    print(f"{name}: {result['status']}", flush=True)
    return result


def main() -> int:
    """Execute selected runtime checks and write a machine-readable G0 report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("vision", "ocr", "all"), default="all")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "g0-vision.json")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--vehicle-model", type=Path, default=PROJECT_ROOT / "models" / "yolov8n.pt"
    )
    parser.add_argument("--ocr-model-root", type=Path)
    parser.add_argument("--allow-model-download", action="store_true")
    args = parser.parse_args()
    default_ocr_root = configure_local_caches()
    work_dir = (args.work_dir or PROJECT_ROOT / ".runtime" / "g0-media" / args.component).resolve()
    checks = [run_check("opencv_mp4", lambda: check_video(work_dir))]
    if args.component in ("vision", "all"):
        checks.append(run_check("yolo_cpu", lambda: check_yolo(args.vehicle_model.resolve())))
        checks.append(run_check("bytetrack", check_bytetrack))
    else:
        checks.append({"name": "yolo_cpu", "status": "skipped", "reason": "OCR interpreter"})
        checks.append({"name": "bytetrack", "status": "skipped", "reason": "OCR interpreter"})
    if args.component in ("ocr", "all"):
        ocr_root = (args.ocr_model_root or default_ocr_root).resolve()
        checks.append(
            run_check(
                "paddleocr_cpu", lambda: check_ocr(work_dir, ocr_root, args.allow_model_download)
            )
        )
    else:
        checks.append(
            {"name": "paddleocr_cpu", "status": "skipped", "reason": "Vision interpreter"}
        )
    report = {
        "stage": "G0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "component": args.component,
        "packages": package_versions(),
        "checks": checks,
        "scope": (
            "Synthetic smoke checks only; no camera, parking events or plate accuracy evaluation."
        ),
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {output}", flush=True)
    return int(any(check["status"] in ("failed", "blocked") for check in checks))


if __name__ == "__main__":
    raise SystemExit(main())
