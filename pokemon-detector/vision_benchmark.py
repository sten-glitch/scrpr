"""BIGSTEN visual identification benchmark (no API/network required).

Compares manually labeled photo objects with independently generated AI
observations. Geometry is matched BEFORE comparing edition/variant, so a model
does not get accuracy credit simply for outputting common card names.
The dataset must contain independently human-reviewed real images before its
metrics are used as evidence of production accuracy.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from vision import normalize_analysis

FIELDS = ("name", "set", "number", "language", "finish", "condition", "grade_company", "grade_number")
UNKNOWN = {"", "unknown", None}
RISK_FLAGS = {"possible_counterfeit", "possible_reseal", "possible_stock_photo"}


def _norm(text):
    if text is None:
        return ""
    return "".join(c.lower() for c in str(text) if c.isalnum())


def intersection_over_union(a, b):
    if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)) or len(a) != 4 or len(b) != 4:
        raise ValueError("Bounding boxes must each have four coordinates")
    if not all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in list(a) + list(b)):
        raise ValueError("Boxes must be normalized")
    aw = max(0, a[2] - a[0])
    ah = max(0, a[3] - a[1])
    bw = max(0, b[2] - b[0])
    bh = max(0, b[3] - b[1])
    if not (aw and ah and bw and bh):
        return 0
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = w * h
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0


def _ratio(n, d):
    return round(n / d, 4) if d else None


def _identity(gold: dict, pred: dict) -> tuple[bool | None, list[str]]:
    """Compare only identity labels meaningfully established in gold standard."""
    checked = [field for field in FIELDS if gold.get(field) not in UNKNOWN]
    if not checked:
        return None, []
    errors = [field for field in checked if _norm(gold[field]) != _norm(pred.get(field))]
    return not bool(errors), errors


def benchmark(cases: list[dict], *, iou_threshold: float = .5) -> dict:
    """Return stratified detection, exact-identity and risk-flag performance.

    Evaluation is by individual image/object, not inferred physical item count
    across multiple views. That requires an independently audited group ID.
    """
    if not isinstance(cases, list) or not cases or not 0 < iou_threshold <= 1:
        raise ValueError("Expected nonempty cases and IoU threshold in (0, 1]")
    ids = set()
    totals = defaultdict(int)
    kinds = defaultdict(lambda: defaultdict(int))
    details = []
    seen_groups = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"].strip():
            raise ValueError("Each case needs a stable case_id")
        if case["case_id"] in ids:
            raise ValueError("Duplicate case_id")
        ids.add(case["case_id"])
        count = case.get("image_count")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
            raise ValueError("Each case needs image_count 1..8")
        kind = case.get("kind")
        if kind not in {"single", "graded", "sealed", "binder", "lot"}:
            raise ValueError("Unknown case kind")
        truth = case.get("ground_truth")
        if not isinstance(truth, list):
            raise ValueError("ground_truth must be a reviewed JSON array")
        for g in truth:
            if not isinstance(g, dict):
                raise ValueError("Invalid ground_truth annotation")
            ix = g.get("image_index")
            if isinstance(ix, bool) or not isinstance(ix, int) or not 0 <= ix < count:
                raise ValueError("Invalid ground_truth image index")
            if intersection_over_union(g.get("bbox_xyxy"), g.get("bbox_xyxy")) <= 0:
                raise ValueError("Invalid ground_truth box")
            if g.get("physical_object_id"):
                seen_groups.add((case["case_id"], g["physical_object_id"]))
        predicted = case.get("prediction", {})
        norm = normalize_analysis(predicted, count)
        photos = norm["observations"]
        candidate_pairs = []
        for gi, g in enumerate(truth):
            for pi, p in enumerate(photos):
                if g["image_index"] != p["image_index"]:
                    continue
                iou = intersection_over_union(g["bbox_xyxy"], p["bbox_xyxy"])
                if iou >= iou_threshold:
                    candidate_pairs.append((iou, gi, pi))
        candidate_pairs.sort(reverse=True)
        used_g, used_p, matched = set(), set(), []
        for iou, gi, pi in candidate_pairs:
            if gi in used_g or pi in used_p:
                continue
            used_g.add(gi)
            used_p.add(pi)
            matched.append((gi, pi, iou))
        counts = {
            "objects_labeled": len(truth),
            "objects_predicted": len(photos),
            "matched": len(matched),
            "false_positive": len(photos) - len(matched),
            "missed_objects": len(truth) - len(matched),
            "exact_identifications": 0,
            "identity_mismatches": 0,
            "unscored_identity": 0,
            "high_confidence_mismatches": 0,
            "risk_true_positive": 0,
            "risk_false_positive": 0,
            "risk_false_negative": 0,
        }
        mismatches = []
        for gi, pi, iou in matched:
            g, p = truth[gi], photos[pi]
            exact, wrong = _identity(g, p)
            if exact is None:
                counts["unscored_identity"] += 1
            elif exact:
                counts["exact_identifications"] += 1
            else:
                counts["identity_mismatches"] += 1
                if p["identity_confidence"] >= .9:
                    counts["high_confidence_mismatches"] += 1
                mismatches.append({
                    "ground_truth_index": gi, "prediction_index": pi, "iou": round(iou, 3),
                    "wrong_fields": wrong, "reported_confidence": p["identity_confidence"],
                })
            golden_risks = set(g.get("flags") or []) & RISK_FLAGS
            reported_risks = set(p["flags"]) & RISK_FLAGS
            counts["risk_true_positive"] += len(golden_risks & reported_risks)
            counts["risk_false_positive"] += len(reported_risks - golden_risks)
            counts["risk_false_negative"] += len(golden_risks - reported_risks)
        # Risk hallucinations on unmatched detected objects are false positives.
        for pi, p in enumerate(photos):
            if pi not in used_p:
                counts["risk_false_positive"] += len(set(p["flags"]) & RISK_FLAGS)
        # Risks on missed truth objects were never detected.
        for gi, g in enumerate(truth):
            if gi not in used_g:
                counts["risk_false_negative"] += len(set(g.get("flags") or []) & RISK_FLAGS)
        for k, v in counts.items():
            totals[k] += v
            kinds[kind][k] += v
        details.append({
            "case_id": case["case_id"], "kind": kind,
            "reported_kind": norm["kind"],
            "kind_correct": norm["kind"] == kind,
            "object_precision": _ratio(counts["matched"], len(photos)),
            "object_recall": _ratio(counts["matched"], len(truth)),
            "counts": counts, "identity_errors": mismatches,
        })
        totals["kind_correct"] += norm["kind"] == kind
    def aggregate(t):
        t = dict(t)
        scored = t.get("exact_identifications", 0) + t.get("identity_mismatches", 0)
        risk_tp = t.get("risk_true_positive", 0)
        return {
            "object_precision": _ratio(t.get("matched", 0), t.get("objects_predicted", 0)),
            "object_recall": _ratio(t.get("matched", 0), t.get("objects_labeled", 0)),
            "exact_identity_accuracy_on_matched": _ratio(t.get("exact_identifications", 0), scored),
            "high_confidence_identity_errors": t.get("high_confidence_mismatches", 0),
            "risk_precision": _ratio(risk_tp, risk_tp + t.get("risk_false_positive", 0)),
            "risk_recall": _ratio(risk_tp, risk_tp + t.get("risk_false_negative", 0)),
            "counts": t,
        }
    return {
        "status": "OFFLINE_BENCHMARK_ONLY",
        "cases": len(cases), "iou_threshold": iou_threshold,
        "metrics": aggregate(totals),
        "by_kind": {kind: aggregate(t) for kind, t in sorted(kinds.items())},
        "cases_detail": details,
        "limitations": [
            "Scores are meaningful only when cases are real, representative, independently human-labeled photos",
            "Spatial object detection is measured per image; it does not prove unique physical inventory across photos",
            "Exact identity is scored only for fields actually established in labels",
            "Condition/grade appearance does not establish authentication, PSA grade or financial profit",
            "Reported model confidence is uncalibrated and not a reliable probability",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Offline annotated vision benchmark")
    p.add_argument("dataset", help="JSON file containing a cases array")
    p.add_argument("--iou", type=float, default=.5)
    p.add_argument("--out", help="Optional JSON report file")
    p.add_argument("--min-exact-accuracy", type=float, help="Explicit project gate for exact identification")
    a = p.parse_args(argv)
    doc = json.loads(Path(a.dataset).read_text(encoding="utf-8"))
    report = benchmark(doc["cases"], iou_threshold=a.iou)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if a.min_exact_accuracy is not None:
        actual = report["metrics"]["exact_identity_accuracy_on_matched"]
        if actual is None or not 0 <= a.min_exact_accuracy <= 1 or actual < a.min_exact_accuracy:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
