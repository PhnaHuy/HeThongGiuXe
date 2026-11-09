"""Download the evaluated plate models, verifying pinned SHA-256 hashes."""

import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = (
    (
        "models/license_plate_yolo11s.pt",
        "https://huggingface.co/morsetechlab/yolov11-license-plate-detection/resolve/"
        "251a30d7daedca065f56e04b0af04052c907c68f/license-plate-finetune-v1s.pt",
        "95e50c25ab7066dd0ca5aec18fa80349676db08697780d1149576461174d2381",
    ),
    (
        "models/plate_ocr/cct_s_v2_global.onnx",
        "https://github.com/ankandrew/cnn-ocr-lp/releases/download/arg-plates/cct_s_v2_global.onnx",
        "384bbbd2cea3ef54761d3df70822ef3a349ee1a112aeafddbe0e3ba06bc6e47b",
    ),
    (
        "models/plate_ocr/cct_s_v2_global_plate_config.yaml",
        "https://github.com/ankandrew/cnn-ocr-lp/releases/download/arg-plates/"
        "cct_s_v2_global_plate_config.yaml",
        "0335c74a305173bb6f393efed0fde03cadeaa0b649ed8e19f431016d8232d0a6",
    ),
)


def main() -> None:
    for relative_path, url, expected in MODELS:
        target = ROOT / relative_path
        if target.is_file():
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Existing model hash differs; not overwritten: {target}")
            print(f"Verified: {relative_path}")
            continue
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Download hash mismatch: {relative_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"Installed: {relative_path}")


if __name__ == "__main__":
    main()
