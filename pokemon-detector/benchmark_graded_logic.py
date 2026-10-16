"""Reproducible synthetic CPU microbenchmark; never real-photo accuracy."""
import argparse
import json
import platform
import statistics
import time
import tracemalloc
from pathlib import Path
from certificate_reader import parse_certificate_text
from unique_supply import aggregate_supply


def run():
    records = [{"marketplace":"EBAY_US", "item_id":str(i), "identity_key":"synthetic:set:3:ja:holo",
        "grade":"10", "certificate":{"grader":"PSA", "number":str(10000000+i//3),
        "evidence_status":"human_confirmed", "source":"photographed_label", "provenance":"SYNTHETIC TEST ONLY"}}
        for i in range(300)]
    report = {"kind":"synthetic_microbenchmark_not_accuracy", "python":platform.python_version(),
              "real_photo_accuracy":None, "real_duplicate_precision":None, "paid_api_calls":0}
    for label, callback, iterations in (
        ("parse_text", lambda:parse_certificate_text("PSA GEM MINT 10\nCERT: 12345678"),1000),
        ("group_300_observations",lambda:aggregate_supply(records),100)):
        callback()
        samples=[]
        tracemalloc.start()
        for _ in range(iterations):
            start=time.perf_counter()
            callback()
            samples.append((time.perf_counter()-start)*1000)
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        report[label]={"iterations":iterations, "median_ms":statistics.median(samples),
                       "p95_ms":sorted(samples)[int(.95*(len(samples)-1))],
                       "python_peak_bytes":peak}
    report["expected_synthetic_counts"] = aggregate_supply(records)["counts"]
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="private/graded-logic-benchmark.json")
    args=parser.parse_args()
    output=Path(args.out)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(run(),indent=2),encoding="utf8")
    print(output)
