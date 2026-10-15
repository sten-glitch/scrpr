"""BIGSTEN Roboflow official dataset pilot — one authorized local command.

The public dataset may require a Roboflow account and authorized API key.
Never bypass official export. Downloaded images and reports stay in private/.

Metrics:
  1. Independent TEST/VALID card bounding-box precision, recall and F1
     against uploader-supplied YOLO annotations.
  2. Unlabeled test photos staged for independent printing review.

NOT measured: exact Pokemon identity, foil, condition, slab authentication,
resale price or profit. Artwork rights are separately assessed.

Usage on your own machine:
  python run_roboflow_pilot.py --source detector
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from external_photo_sources import PhotoSourceError, SOURCES, download_roboflow
from external_detection_benchmark import (
    benchmark_yolo, report_html, DetectionBenchmarkError,
)
from prepare_web_photo_review import prepare_web_photo_review, ReviewImportError


class FullPilotError(ValueError):
    pass


def _choose_split(dataset_root: Path, selected: str):
    if selected not in {"auto", "test", "valid"}:
        raise FullPilotError("Allowed split: auto, test, valid")
    splits = ("test", "valid") if selected == "auto" else (selected,)
    for split in splits:
        if (dataset_root / split / "images").is_dir() and (dataset_root / split / "labels").is_dir():
            return split
    raise FullPilotError("Dataset export lacks TEST/VALID image-label split")


def run_pilot(*, source="detector", root="private/roboflow-pilot",
              split="auto", max_images=300, review_count=50,
              download=download_roboflow, benchmark=benchmark_yolo,
              stage_review=prepare_web_photo_review) -> dict:
    """Authorized acquisition and real box detection evaluation, no card IDs."""
    if source not in {"detector", "binder", "scanner"}:
        raise FullPilotError("Unknown registered source")
    if type(max_images) is not int or not 1 <= max_images <= 400:
        raise FullPilotError("Choose 1–400 test images")
    if type(review_count) is not int or not 0 <= review_count <= 200:
        raise FullPilotError("Choose 0–200 photos to stage for human review")
    if not os.environ.get("ROBOFLOW_API_KEY", "").strip():
        raise FullPilotError("Official export requires ROBOFLOW_API_KEY in this shell")
    root = Path(root).expanduser().resolve()
    report_root = root / "reports"
    dataset_root = root / "datasets"
    review_root = root / "human-review"
    if report_root.exists() and any(report_root.iterdir()):
        raise FullPilotError("Refusing to overwrite previous benchmark reports")
    dataset_meta = download(source, root=dataset_root)
    path = Path(dataset_meta["dataset_directory"]).resolve()
    try:
        path.relative_to(dataset_root)
    except ValueError as exc:
        raise FullPilotError("SDK export escaped private data root") from exc
    selected = _choose_split(path, split)
    assessment = benchmark(path, split=selected, source=source, max_images=max_images)
    if assessment.get("card_identity_accuracy_measured") is not False:
        raise FullPilotError("Box detector cannot claim exact identity accuracy")
    staged = None
    if review_count:
        staged = stage_review(path, review_root, source=source, split=selected,
                              max_photos=review_count)
    summary = {
        "status": "AUTHORIZED_EXTERNAL_BOX_DETECTION_RESEARCH_NOT_CARD_ID_ACCURACY",
        "run_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_title": SOURCES[source]["title"],
        "source_url": SOURCES[source]["url"],
        "provider_license_displayed": SOURCES[source]["license_displayed"],
        "authorized_provider_sdk_used": True,
        "provider_data_rights_and_artwork_verified": False,
        "split": selected,
        "photos_evaluated": assessment["samples"]["evaluated"],
        "card_box_precision_vs_publisher_annotations": assessment["metrics"]["precision"],
        "card_box_recall_vs_publisher_annotations": assessment["metrics"]["recall"],
        "card_box_f1_vs_publisher_annotations": assessment["metrics"]["f1"],
        "staged_for_human_review": staged["photo_count"] if staged else 0,
        "exact_identity_accuracy": None,
        "human_ground_truth_reviewer_required": True,
        "note": "Publisher annotations are not independently verified. No commercial card artwork rights or printing-level accuracy established.",
    }
    report_root.mkdir(parents=True, exist_ok=False)
    (report_root / "detection.json").write_text(
        json.dumps(assessment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (report_root / "detection.html").write_text(
        report_html(assessment), encoding="utf-8")
    (report_root / "pilot-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Authorized Roboflow export + OpenCV bounding-box benchmark"
    )
    parser.add_argument("--source", choices=["detector", "binder", "scanner"], required=True)
    parser.add_argument("--root", default="private/roboflow-pilot")
    parser.add_argument("--split", choices=["auto", "test", "valid"], default="auto")
    parser.add_argument("--max-images", type=int, default=300)
    parser.add_argument("--review-count", type=int, default=50)
    args = parser.parse_args(argv)
    report = run_pilot(source=args.source, root=args.root, split=args.split,
                       max_images=args.max_images, review_count=args.review_count)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("Photos remain private. Report:", Path(args.root) / "reports" / "detection.html")
    print("Exact card identities, grades and commercial rights NOT verified")


if __name__ == "__main__":
    main()
