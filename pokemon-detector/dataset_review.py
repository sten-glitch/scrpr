"""BIGSTEN Photo Review Lab: local, human-attested holdout labels.

This module is intentionally independent of image recognition and any paid
model. Labels never become automatic "ground truth": a reviewer must explicitly
attest an inspected card identity and reference, with photo file hash recorded.

Only JSON + metadata; source photos stay in a chosen local private directory.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from photo_inputs import _mime_from_signature, PhotoInputError

MAX_PHOTOS = 500
MAX_CASES = 500
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
KINDS = {"single", "graded", "binder", "lot", "sealed", "negative"}


class PhotoReviewError(ValueError):
    pass


def _safe_name(name: str) -> str:
    if (not isinstance(name, str) or len(name) > 180
            or not name or name != Path(name).name
            or name.startswith(".")
            or name.endswith(".") or "/" in name or "\\" in name
            or Path(name).suffix.lower() not in IMAGE_SUFFIXES):
        raise PhotoReviewError("Only direct JPG/PNG/WebP filenames are allowed")
    return name


def _safe_bbox(box):
    if box is None:
        return None
    if (not isinstance(box, list) or len(box) != 4
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in box)
            or not (box[0] < box[2] and box[1] < box[3])
            or (box[2] - box[0]) * (box[3] - box[1]) < .0004):
        raise PhotoReviewError("bbox_xyxy must specify a meaningful normalized rectangle")
    return [round(float(v), 5) for v in box]


def _iou(a, b):
    if a is None or b is None:
        return 1.0
    w = max(0., min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0., min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    aa = (a[2] - a[0]) * (a[3] - a[1])
    bb = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (aa + bb - inter) if aa + bb - inter else 0.0


class PhotoReviewStore:
    def __init__(self, photo_root: str | Path, dataset_path: str | Path,
                 catalog: list[dict] | None = None):
        self.photo_root = Path(photo_root).expanduser().resolve()
        if not self.photo_root.is_dir():
            raise PhotoReviewError("Photo folder does not exist")
        self.dataset_path = Path(dataset_path).expanduser().resolve()
        if self.dataset_path.suffix.lower() != ".json":
            raise PhotoReviewError("Dataset output must be JSON")
        if self.dataset_path.is_symlink() or self.dataset_path == self.photo_root:
            raise PhotoReviewError("Refusing unsafe dataset output path")
        if self.dataset_path.parent == self.photo_root:
            raise PhotoReviewError("Keep private labels separate from photo directory")
        self.dataset_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.catalog = catalog or []
        if not isinstance(self.catalog, list):
            raise PhotoReviewError("Catalog must be JSON array")
        self.known_keys = {c.get("identity_key") for c in self.catalog
                           if isinstance(c,dict) and isinstance(c.get("identity_key"),str)}
        self.photo_names = self._scan()
        if not self.photo_names:
            raise PhotoReviewError("No usable photos in chosen folder (JPG/PNG/WebP, max 5 MiB)")
        self.rows = {}
        if self.dataset_path.is_file():
            try:
                payload = json.loads(self.dataset_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
                    raise PhotoReviewError("Existing dataset is not a valid cases manifest")
                for case in payload["cases"]:
                    checked = self._validate(case, existing=False, bypass_hash=False)
                    if checked["case_id"] in self.rows:
                        raise PhotoReviewError("Duplicate case_id found in existing dataset")
                    self.rows[checked["case_id"]] = checked
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise PhotoReviewError("Could not read existing private dataset") from exc

    def _scan(self):
        items = []
        for path in sorted(self.photo_root.iterdir(), key=lambda p: p.name.lower()):
            if path.is_symlink() or not path.is_file() or path.name.startswith("."):
                continue
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if path.stat().st_size == 0 or path.stat().st_size > MAX_IMAGE_BYTES:
                continue
            try:
                head = path.read_bytes()
                _mime_from_signature(path, head)
            except (PhotoInputError, OSError):
                continue
            items.append(path.name)
            if len(items) > MAX_PHOTOS:
                raise PhotoReviewError("More than 500 photos: split this evaluation dataset")
        return tuple(items)

    def image(self, name: str) -> tuple[bytes, str]:
        name = _safe_name(name)
        if name not in self.photo_names:
            raise PhotoReviewError("Unknown or unapproved photograph")
        path = self.photo_root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
            raise PhotoReviewError("Photo is unavailable or has changed")
        data = path.read_bytes()
        try:
            mime = _mime_from_signature(path, data)
        except PhotoInputError as exc:
            raise PhotoReviewError("Photo signature invalid") from exc
        return data, mime

    def _validate(self, record: dict, *, existing: bool, bypass_hash: bool) -> dict:
        if not isinstance(record, dict):
            raise PhotoReviewError("Expected label record object")
        cid = record.get("case_id")
        if not isinstance(cid,str) or not re.fullmatch(r"[A-Za-z0-9_-]{4,100}",cid):
            raise PhotoReviewError("case_id must be a unique safe ID (4–100 characters)")
        name = _safe_name(record.get("image_file"))
        data, _mime = self.image(name)
        digest = hashlib.sha256(data).hexdigest()
        provided = record.get("photo_sha256")
        if provided is not None and provided != digest:
            raise PhotoReviewError("Photo has changed after labeling: digest mismatch")
        if record.get("split") != "holdout":
            raise PhotoReviewError("Photo Review Lab only produces heldout labels")
        if record.get("annotation_verified") is not True:
            raise PhotoReviewError("Reviewer must explicitly confirm independent ground truth")
        kind = record.get("kind")
        if kind not in KINDS:
            raise PhotoReviewError("Unsupported case category")
        expected = record.get("expected_identity_key")
        if kind == "negative":
            if expected is not None:
                raise PhotoReviewError("Negative cases cannot have a card identity")
        elif not isinstance(expected, str) or not expected.strip() or len(expected)>256:
            raise PhotoReviewError("Positive cases require a precise expected_identity_key")
        if expected is not None and self.known_keys and expected not in self.known_keys:
            raise PhotoReviewError("Card key not in loaded catalog; check exact variant")
        reviewer = record.get("reviewer")
        evidence = record.get("annotation_reference")
        if not isinstance(reviewer,str) or not 2<=len(reviewer.strip())<=100:
            raise PhotoReviewError("Human reviewer name or nickname required")
        if not isinstance(evidence,str) or not 3<=len(evidence.strip())<=200:
            raise PhotoReviewError("Provide a real independent annotation reference")
        box = _safe_bbox(record.get("bbox_xyxy"))
        details = record.get("notes","")
        if not isinstance(details,str) or len(details)>500:
            raise PhotoReviewError("Notes must be short text")
        reviewed_at = record.get("reviewed_at")
        if reviewed_at:
            try:
                stamp = dt.date.fromisoformat(reviewed_at)
            except (TypeError, ValueError) as exc:
                raise PhotoReviewError("reviewed_at must be ISO YYYY-MM-DD") from exc
            if stamp > dt.datetime.now(dt.timezone.utc).date():
                raise PhotoReviewError("Reviewed date cannot be in the future")
        else:
            reviewed_at = dt.datetime.now(dt.timezone.utc).date().isoformat()
        return {
            "case_id":cid, "kind":kind, "split":"holdout",
            "image_file":name, "expected_identity_key":expected,
            "bbox_xyxy":box, "annotation_verified":True,
            "annotation_reference":evidence.strip(), "reviewer":reviewer.strip(),
            "photo_sha256":digest, "reviewed_at":reviewed_at,
            "notes":details.strip(),
        }

    def _serialize(self):
        return {"dataset_version":1, "dataset_type":"PRIVATE_HUMAN_ATTESTED_HOLDOUT",
                "generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
                "cases":[self.rows[k] for k in sorted(self.rows)]}

    def export(self):
        with self.lock:
            return self._serialize()

    def summary(self):
        with self.lock:
            cases=self._serialize()["cases"]
            by_photo={}
            for row in cases:
                by_photo.setdefault(row["image_file"],[]).append(row)
            count={"single":0,"graded":0,"binder":0,"lot":0,"sealed":0,"negative":0}
            for row in cases:
                count[row["kind"]]+=1
            return {"images":list(self.photo_names), "cases":cases,
                    "photo_count":len(self.photo_names),
                    "labeled_photos":len(by_photo), "labeled_cases":len(cases),
                    "target_cases":50, "by_kind":count,
                    "status":"PRIVATE_REVIEW_ONLY_NOT_CALIBRATED",
                    "catalog_keys":len(self.known_keys)}

    def save(self, record: dict):
        with self.lock:
            checked=self._validate(record, existing=True, bypass_hash=False)
            cid=checked["case_id"]
            previous=self.rows.get(cid)
            if previous is not None and previous["image_file"]!=checked["image_file"]:
                raise PhotoReviewError("Cannot reassign an existing case to another photo")
            if cid not in self.rows and len(self.rows)>=MAX_CASES:
                raise PhotoReviewError("500 label limit reached; create a separate dataset")
            for old_id, old in self.rows.items():
                if old_id!=cid and old["image_file"]==checked["image_file"]:
                    if _iou(old["bbox_xyxy"],checked["bbox_xyxy"])>.80:
                        raise PhotoReviewError("Overlapping or duplicate labels for same photo")
            candidate={**self.rows, cid:checked}
            # Write atomically; always close file before rename on Windows.
            new_data={"dataset_version":1, "dataset_type":"PRIVATE_HUMAN_ATTESTED_HOLDOUT",
                      "generated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
                      "cases":[candidate[k] for k in sorted(candidate)]}
            fd,tmp=tempfile.mkstemp(dir=str(self.dataset_path.parent),
                                    prefix=".bigsten-label-",suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(new_data,stream,indent=2,ensure_ascii=False)
                    stream.write("\n")
                os.replace(tmp,self.dataset_path)
                self.rows=candidate
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return checked
