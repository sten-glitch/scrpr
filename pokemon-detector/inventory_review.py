"""Photo inventory reconciliation: distinguish observations from physical copies.

We do NOT infer unique physical objects across separate photographs. A card
could have been photographed twice, or two identical cards might both exist.
We return an observation-based quantity RANGE and human review issues,
never a verified count or an automatic purchase authorization.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

def intersection_over_union(a, b):
    """Minimal unit-square IoU with no dependency on the benchmark or vision."""
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0

IDENTITY_FIELDS = ("name", "set", "number", "language", "finish", "grade_company", "grade_number")


def _fingerprint(observation: dict, identity_key: str | None) -> str:
    if identity_key:
        return "catalog:" + identity_key
    fields = [str(observation.get(k) or "").strip().lower() for k in IDENTITY_FIELDS]
    if fields[0] and fields[1] and fields[2] and fields[3] not in ("", "unknown"):
        return "visual:" + json.dumps(fields, separators=(",", ":"))
    # Cannot even distinguish this card from other unknowns across photos.
    # Group unknown objects conservatively by class for bounding purposes.
    cls = "sealed" if observation.get("condition") == "sealed" else (
        "graded" if observation.get("grade_company") else "unresolved")
    return "unidentified:" + cls


def _distinct_detections(observations, indices) -> tuple[list[int], list[int]]:
    """Collapse same-photo same-identity VERY HIGH IoU detector duplicates only.

    Returns observation indices of kept detections plus potential overlaps.
    The output is evidence for review, not independently confirmed ownership.
    """
    kept, repeats = [], []
    for idx in indices:
        o = observations[idx]
        if any(
            o["image_index"] == observations[j]["image_index"]
            and intersection_over_union(o["bbox_xyxy"], observations[j]["bbox_xyxy"]) >= .98
            for j in kept
        ):
            repeats.append(idx)
        else:
            kept.append(idx)
    return kept, repeats


def review_inventory(observations: list[dict], identity_keys: list[str | None]) -> dict:
    """Return physical quantity bounds conditional on the photo detections.

    Observations are in model coordinates. Human reconciliation is always
    required before assigning a VERIFIED quantity for resale appraisal.
    """
    if not isinstance(observations, list) or not isinstance(identity_keys, list) or len(observations) != len(identity_keys):
        raise ValueError("Expected one catalog resolution per observation")
    grouped = defaultdict(list)
    for idx, (o, identity) in enumerate(zip(observations, identity_keys)):
        if not isinstance(o, dict) or not isinstance(o.get("image_index"), int):
            raise ValueError("Normalized photo observation required")
        grouped[_fingerprint(o, identity)].append(idx)
    groups = []
    min_count, max_count = 0, 0
    for key, indices in grouped.items():
        kept, detector_duplicates = _distinct_detections(observations, indices)
        visible_per_image = Counter(observations[i]["image_index"] for i in kept)
        group_min = max(visible_per_image.values(), default=0)
        group_max = len(kept)
        min_count += group_min
        max_count += group_max
        cross_photo_ambiguity = len(visible_per_image) > 1
        groups.append({
            "identity_group": key,
            "observation_indices": indices,
            "image_indices": sorted(visible_per_image),
            "visible_per_image": {str(k): v for k, v in sorted(visible_per_image.items())},
            "possible_distinct_copies_min": group_min,
            "possible_distinct_copies_max": group_max,
            "same_photo_duplicate_detections": detector_duplicates,
            "cross_photo_quantity_ambiguous": cross_photo_ambiguity,
            "resolved_catalog_identity": key.startswith("catalog:"),
            "review_required": cross_photo_ambiguity or bool(detector_duplicates) or not key.startswith("catalog:"),
        })
    flagged = [g for g in groups if g["review_required"]]
    return {
        "total_model_observations": len(observations),
        "quantity_lower_bound_if_detections_correct": min_count,
        "quantity_upper_bound_if_detections_correct": max_count,
        "quantity_verified": False,
        "requires_human_reconciliation": True,
        "groups_requiring_review": len(flagged),
        "groups": groups,
        "notes": [
            "Counts are conditional estimates from model detections, not confirmed physical inventory",
            "Identical catalog cards in multiple photos could be the same copy or several copies",
            "Unresolved cards can be grouped only for conservative range estimation",
            "Never multiply a sale price by an unverified count",
        ],
    }
