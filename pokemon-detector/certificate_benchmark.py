"""Repeatable local certificate OCR benchmark; no downloads or generated truth.

Manifest: {"version": 1, "cases": [{"case_id": "...", "image": "a.jpg",
"sha256": "...", "grader": "PSA", "certificate_number": "00123456",
"clear_label": true, "is_real": true, "used_for_training": false,
"independent_group_id": "physical-slab-1", "rights_basis": "owned photo",
"reviewer": "human", "truth_source": "manual transcription of original"}]}.
Independence and rights are human attestations. Hash checks cannot prove them or
detect transformed copies from training; those require an external dataset audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import statistics
import time
import tracemalloc

from certificate_reader import read_slab_certificate


def _image_path(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Use a relative POSIX image path")
    relative = Path(name)
    if relative.is_absolute() or PureWindowsPath(name).is_absolute() or ".." in relative.parts:
        raise ValueError("Image path escapes dataset")
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Symlink image paths are not permitted")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Image must be a regular file inside dataset")
    if not 0 < path.stat().st_size <= 5 * 1024 * 1024:
        raise ValueError("Image must be at most 5 MiB")
    return path


def benchmark_certificates(manifest: dict, image_root: str | Path, *, reader=None) -> dict:
    """Evaluate all rows, keeping failures in denominators. Injected engines are tests.

    A real-data eligibility gate needs >=50 distinct, clear, real photo groups.
    It is separate from accuracy and does not assert commercial readiness.
    """
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("Expected certificate benchmark manifest version 1")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 10000:
        raise ValueError("Expected 1..10000 benchmark cases")
    root = Path(image_root).absolute()
    hashes, ids, prepared = set(), set(), []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Invalid benchmark case")
        for key in ("case_id", "rights_basis", "reviewer", "truth_source", "independent_group_id"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f"Missing human provenance: {key}")
        for key in ("is_real", "clear_label", "used_for_training"):
            if not isinstance(case.get(key), bool):
                raise ValueError(f"Expected boolean {key}")
        if case["used_for_training"]:
            raise ValueError("Training images cannot be benchmark holdout")
        cert = case.get("certificate_number")
        if case.get("grader") not in {"PSA", "BGS", "CGC"} or not isinstance(cert, str) or not cert or not cert.isascii() or not cert.isdigit():
            raise ValueError("Human truth needs supported grader and literal numeric certificate")
        path = _image_path(root, case.get("image"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if case.get("sha256") != digest:
            raise ValueError("Image SHA256 differs from reviewed manifest")
        if digest in hashes or case["case_id"] in ids:
            raise ValueError("Duplicate image or case ID")
        hashes.add(digest)
        ids.add(case["case_id"])
        prepared.append((case, path))
    rows, latencies = [], []
    engine = reader or read_slab_certificate
    owns_trace = not tracemalloc.is_tracing()
    if owns_trace:
        tracemalloc.start()
    try:
        for case, path in prepared:
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != case["sha256"]:
                raise ValueError("Image changed after preflight")
            start = time.perf_counter()
            result = {}
            try:
                result = engine(data)  # Never supply the expected grader as a hint.
                if not isinstance(result, dict):
                    raise ValueError("Malformed reader response")
                errors = result.get("errors", [])
                unavailable = result.get("status") == "unavailable" or "ocr_unavailable" in errors
                failed = unavailable or "ocr_failed" in errors
                match = not failed and result.get("grader") == case["grader"] and result.get("certificate_number") == case["certificate_number"]
                error = "reader_unavailable" if unavailable else ("reader_failed" if failed else None)
            except Exception as exc:
                result = {}
                match, unavailable, failed, error = False, False, True, type(exc).__name__
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            rows.append({"case_id": case["case_id"], "sha256": case["sha256"],
                         "clear_label": case["clear_label"], "exact_match": bool(match),
                         "expected_grader": case["grader"],
                         "grader_match": not failed and result.get("grader") == case["grader"],
                         "grade_match": (not failed and result.get("grade") == case["grade"]) if case.get("grade") else None,
                         "engine_unavailable": unavailable, "failed": failed,
                         "error": error, "latency_ms": round(elapsed, 3)})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        if owns_trace:
            tracemalloc.stop()
    clear = [row for row in rows if row["clear_label"]]
    eligible_groups = {c["independent_group_id"] for c in cases if c["is_real"] and c["clear_label"]}
    measurable = any(not row["failed"] for row in rows)
    graded_rows = [r for r in rows if r["grade_match"] is not None]
    per_grader = {}
    for grader in ("PSA", "BGS", "CGC"):
        subset = [r for r in rows if r["expected_grader"] == grader]
        per_grader[grader] = {"count": len(subset), "exact_match_rate": sum(r["exact_match"] for r in subset)/len(subset) if subset else None}
    return {"schema_version": 1,
            "per_grader": per_grader,
            "grader_recognition_rate": sum(r["grader_match"] for r in rows)/len(rows),
            "grade_recognition_rate": sum(r["grade_match"] for r in graded_rows)/len(graded_rows) if graded_rows else None,
            "grade_labeled_count": len(graded_rows), "case_count": len(rows), "clear_label_count": len(clear),
            "exact_match_rate": sum(row["exact_match"] for row in rows) / len(rows),
            "clear_label_exact_match_rate": sum(row["exact_match"] for row in clear) / len(clear) if clear else None,
            "accuracy_measurable": measurable, "engine_unavailable_count": sum(row["engine_unavailable"] for row in rows),
            "failure_count": sum(row["failed"] for row in rows),
            "latency_ms": {"median": statistics.median(latencies), "p95": sorted(latencies)[math.ceil(.95*len(latencies))-1]},
            "peak_python_traced_bytes": peak, "memory_scope": "tracemalloc Python allocations; excludes native OCR/OpenCV/GPU memory",
            "memory_isolated": owns_trace, "engine": "injected_test_reader" if reader else "local_certificate_reader",
            "independent_real_clear_groups": len(eligible_groups),
            "real_data_gate_passed": len(eligible_groups) >= 50 and all(c["is_real"] for c in cases) and reader is None and measurable,
            "independence_basis": "human attestation; no perceptual training-overlap audit",
            "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--image-root", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("private/certificate-benchmark.json"))
    args = parser.parse_args()
    report = benchmark_certificates(json.loads(args.manifest.read_text(encoding="utf-8")), args.image_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {report['case_count']} cases; measurable={report['accuracy_measurable']}; real-data gate={report['real_data_gate_passed']}")


if __name__ == "__main__":
    main()
