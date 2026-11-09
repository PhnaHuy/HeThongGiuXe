"""Evaluate exact full-plate matches per vehicle event; abstentions/errors count as misses."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parking_app.application.plate_recognition import PlateRecognitionService  # noqa: E402
from parking_app.config.settings import AppSettings  # noqa: E402
from parking_app.domain.plate import normalize_plate, validate_normalized_plate  # noqa: E402


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    correct = sum(row["correct"] for row in rows)
    proposed = sum(row["predicted"] is not None for row in rows)
    groups: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        groups[row["group"]].append(row["correct"])
    return {
        "events": total,
        "correct": correct,
        "exact_plate_accuracy": correct / total if total else None,
        "proposal_coverage": proposed / total if total else None,
        "accuracy_among_proposals": correct / proposed if proposed else None,
        "unique_groups": len(groups),
        "group_macro_accuracy": (
            statistics.mean(statistics.mean(values) for values in groups.values())
            if groups
            else None
        ),
        "errors": sum(row["error"] is not None for row in rows),
        "mean_seconds": statistics.mean(row["seconds"] for row in rows) if rows else None,
        "above_90_percent_on_this_manifest": bool(total and correct / total > 0.9),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--heuristic", action="store_true", help="Compare geometry detector")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    samples = manifest["samples"]
    if not samples or len({sample["id"] for sample in samples}) != len(samples):
        raise ValueError("Manifest must contain nonempty samples with unique IDs")
    options = AppSettings().plate_recognition_options
    if args.heuristic:
        options = replace(options, detector_model_path=None)
    service = PlateRecognitionService(options)
    rows = []
    for sample in samples:
        expected = normalize_plate(sample["plate"])
        validate_normalized_plate(expected)
        if not sample["images"]:
            raise ValueError("Each event needs at least one vehicle image")
        started = time.perf_counter()
        predicted = error = None
        try:
            images = tuple((args.manifest.parent / path).read_bytes() for path in sample["images"])
            predicted = service.recognize(images).proposed_plate
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        row = {
            "id": sample["id"],
            "group": sample["group"],
            "condition": sample.get("condition", "unspecified"),
            "expected": expected,
            "predicted": predicted,
            "correct": predicted == expected,
            "error": error,
            "seconds": round(time.perf_counter() - started, 4),
        }
        rows.append(row)
        print(f"{sample['id']}: {'correct' if row['correct'] else 'miss'}", flush=True)
    report = {
        "scope": manifest.get("scope", "User-supplied manifest; independence not verified"),
        "detector": str(options.detector_model_path or "heuristic"),
        "detector_image_size": options.detector_image_size,
        "detector_confidence": options.detector_confidence,
        "min_ocr_confidence": options.min_ocr_confidence,
        "max_regions": options.max_regions,
        "ocr_worker": str(options.worker_path),
        "summary": summarize(rows),
        "samples": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["above_90_percent_on_this_manifest"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
