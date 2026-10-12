"""BIGSTEN local reference retrieval benchmark — independent held-out photos.

No paid API, no network access. To avoid misleading accuracy claims:
- query photos must be genuinely separate from reference-index source photos
- identical-bytes queries are rejected (train/test leakage)
- all expected identities are human-attested, not model-generated
- unrecognized and non-catalog photos must also be represented
- metrics count ABSTAIN and AMBIGUOUS instead of silently discarding them

Reference matcher image similarity is NOT evidence of item authenticity/grade.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from reference_matcher import ReferenceMatcher, ReferenceMatchError, _safe_reference
from local_cv import _checked_image
from dataset_review import _iou


class ReferenceBenchmarkError(ValueError):
    pass


TYPES = {"single", "binder", "lot", "graded", "sealed", "negative"}


def _fraction(n, d):
    return round(n/d, 4) if d else None


def _load_manifest_hashes(document: dict, image_root: str | Path):
    if not isinstance(document, dict) or not isinstance(document.get("references"), list):
        raise ReferenceBenchmarkError("Reference manifest must have references array")
    hashes = set()
    for ref in document["references"]:
        if not isinstance(ref, dict):
            raise ReferenceBenchmarkError("Invalid reference manifest record")
        path = _safe_reference(Path(image_root), ref.get("image_file"))
        if path.stat().st_size > 5 * 1024 * 1024:
            raise ReferenceBenchmarkError("Reference file too large")
        hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    if not hashes:
        raise ReferenceBenchmarkError("No source reference images were supplied")
    return hashes


def _evaluate_photo(matcher: ReferenceMatcher, raw: bytes, box: list[float] | None):
    if box is None:
        return matcher.match_entire_photo(raw)
    if (not isinstance(box,list) or len(box)!=4 or
        any(isinstance(v,bool) or not isinstance(v,(float,int)) or not 0<=v<=1 for v in box)
        or not box[0]<box[2] or not box[1]<box[3]):
        raise ReferenceBenchmarkError("Invalid normalized bbox_xyxy")
    _, mat = _checked_image(raw)
    h,w=mat.shape[:2]
    x1,y1,x2,y2=(int(box[0]*w),int(box[1]*h),int(box[2]*w),int(box[3]*h))
    crop=mat[y1:y2,x1:x2]
    if crop.size==0 or min(crop.shape[:2])<48:
        return {"status":"ABSTAIN", "matched_identity_key":None,
                "reason":"Small or empty crop", "candidates":[]}
    return matcher.match_bgr(crop)


def audit_references(matcher: ReferenceMatcher, test_data: dict,
                     query_root: str | Path, reference_manifest: dict,
                     reference_image_root: str | Path) -> dict:
    if not isinstance(test_data,dict) or not isinstance(test_data.get("cases"),list):
        raise ReferenceBenchmarkError("Expected JSON object with cases array")
    cases=test_data["cases"]
    if not 1<=len(cases)<=500:
        raise ReferenceBenchmarkError("Expected 1..500 held-out cases")
    ref_hashes=_load_manifest_hashes(reference_manifest,reference_image_root)
    seen_ids,seen_query_regions=set(),defaultdict(list)
    real_photo_digests=set()
    synthetic_photo_digests=set()
    unknown_origin_digests=set()
    seen_kinds=set()
    indexed_identities = {row[1] for row in getattr(matcher,"records",[])} if hasattr(matcher,"records") else None
    row_results=[]
    counts=defaultdict(int)
    by_kind=defaultdict(lambda:defaultdict(int))
    for record in cases:
        if not isinstance(record,dict):
            raise ReferenceBenchmarkError("Benchmark case must be an object")
        case_id=record.get("case_id")
        if not isinstance(case_id,str) or not case_id.strip() or len(case_id)>100 or case_id in seen_ids:
            raise ReferenceBenchmarkError("Each case needs unique nonempty case_id")
        seen_ids.add(case_id)
        kind=record.get("kind")
        if kind not in TYPES:
            raise ReferenceBenchmarkError("Invalid test case category")
        if record.get("split")!="holdout":
            raise ReferenceBenchmarkError("Only independent held-out cases can count toward benchmark")
        if record.get("annotation_verified") is not True:
            raise ReferenceBenchmarkError("Human-attested ground-truth labels required")
        proof=record.get("annotation_reference")
        if not isinstance(proof,str) or not proof.strip():
            raise ReferenceBenchmarkError("Missing independent ground-truth reference")
        if "expected_identity_key" not in record:
            raise ReferenceBenchmarkError("Expected identity_key field (null for negatives)")
        expected=record["expected_identity_key"]
        if expected is not None and (not isinstance(expected,str) or not expected.strip()):
            raise ReferenceBenchmarkError("expected_identity_key must be exact text or null")
        if kind=="negative" and expected is not None:
            raise ReferenceBenchmarkError("Negative case cannot have a known positive identity")
        if expected is not None and indexed_identities is not None and expected not in indexed_identities:
            raise ReferenceBenchmarkError("Positive ground-truth identity is missing from the reference index; classify as negative if out of scope")
        path=_safe_reference(Path(query_root),record.get("image_file"))
        if path.stat().st_size>5*1024*1024:
            raise ReferenceBenchmarkError("Query photo exceeds 5 MiB")
        raw=path.read_bytes()
        digest=hashlib.sha256(raw).hexdigest()
        if digest in ref_hashes:
            raise ReferenceBenchmarkError(
                f"Reference leakage: {case_id} is byte-identical to an indexed reference"
            )
        # Labeling multiple DIFFERENT card boxes in one binder photo is valid.
        # Repeated full-frame samples or overlapping boxes inflate metrics.
        box=record.get("bbox_xyxy")
        prior=seen_query_regions[digest]
        if prior and (box is None or any(p is None or _iou(p,box)>.80 for p in prior)):
            raise ReferenceBenchmarkError("Repeated query region would inflate test sample")
        prior.append(box)
        provided_hash=record.get("photo_sha256")
        if provided_hash is not None and provided_hash!=digest:
            raise ReferenceBenchmarkError("Photo bytes changed after annotation (photo_sha256 mismatch)")
        origin=record.get("photo_origin","unknown")
        if origin=="real_photo":
            real_photo_digests.add(digest)
        elif origin=="synthetic_demo":
            synthetic_photo_digests.add(digest)
        else:
            unknown_origin_digests.add(digest)
        seen_kinds.add(kind)
        result=_evaluate_photo(matcher,raw,box)
        status=result.get("status")
        if status not in {"ABSTAIN","AMBIGUOUS","VISUAL_CANDIDATE"}:
            raise ReferenceBenchmarkError("Unexpected matcher status")
        candidate=result.get("matched_identity_key") if status=="VISUAL_CANDIDATE" else None
        if expected is None:
            outcome="false_match" if candidate else "correct_rejection"
            counts["negative_cases"]+=1
            by_kind[kind]["negative_cases"]+=1
        elif candidate==expected:
            outcome="correct"
            counts["positive_cases"]+=1
            by_kind[kind]["positive_cases"]+=1
        elif candidate:
            outcome="wrong_identity"
            counts["positive_cases"]+=1
            by_kind[kind]["positive_cases"]+=1
        else:
            outcome="no_identity"
            counts["positive_cases"]+=1
            by_kind[kind]["positive_cases"]+=1
        counts[outcome]+=1
        counts[status]+=1
        by_kind[kind][outcome]+=1
        by_kind[kind][status]+=1
        row_results.append({
            "case_id":case_id,"kind":kind,"outcome":outcome,
            "matcher_status":status,"expected_identity_key":expected,
            "candidate_identity_key":candidate,
            "top_candidates":[
                {"identity_key":c.get("identity_key"),
                 "phash_distance":c.get("phash_distance"),
                 "orb_good_matches":c.get("orb_good_matches")}
                for c in (result.get("candidates") or [])[:3]
                if isinstance(c,dict)
            ],
        })
    def metrics(c):
        positives=c["positive_cases"]
        negatives=c["negative_cases"]
        accepted=c["correct"]+c["wrong_identity"]+c["false_match"]
        return {
            "cases":positives+negatives,
            "known_card_recall":_fraction(c["correct"],positives),
            "wrong_identity_rate_on_positives":_fraction(c["wrong_identity"],positives),
            "false_match_rate_on_negatives":_fraction(c["false_match"],negatives),
            "accepted_candidate_precision_on_labeled_cases":_fraction(c["correct"],accepted),
            "abstain_rate":_fraction(c["ABSTAIN"],positives+negatives),
            "ambiguous_rate":_fraction(c["AMBIGUOUS"],positives+negatives),
            "counts":dict(c),
        }
    return {
        "status":"HUMAN_ATTESTED_HELDOUT_REFERENCE_BENCHMARK",
        "evaluated_at":dt.datetime.now(dt.timezone.utc).isoformat(),
        "metrics":{**metrics(counts),
                   "distinct_test_photos":len(seen_query_regions),
                   "distinct_real_photos":len(real_photo_digests),
                   "distinct_synthetic_photos":len(synthetic_photo_digests),
                   "distinct_unclassified_photos":len(unknown_origin_digests)},
        "pilot_sample_gate":{
            "fifty_distinct_real_photos":len(real_photo_digests)>=50,
            "at_least_five_negative_cases":counts["negative_cases"]>=5,
            "at_least_three_evaluation_categories":len(seen_kinds)>=3,
            "all_photo_origins_reviewed":len(unknown_origin_digests)==0,
            "accuracy_certified":False,
            "status":"SAMPLE_READY_FOR_MANUAL_REVIEW" if (
                len(real_photo_digests)>=50 and counts["negative_cases"]>=5
                and len(seen_kinds)>=3 and not unknown_origin_digests
            ) else "INSUFFICIENT_REAL_PHOTO_VALIDATION",
        },
        "by_kind":{k:metrics(v) for k,v in sorted(by_kind.items())},
        "cases":row_results,
        "limitations":[
            "Independent handwritten labels are human attestations, not guaranteed truth",
            "Byte-exact train/test duplicates and overlapping same-photo regions are rejected; resized/near-duplicate leakage still needs human review",
            "Self-reported real-photo provenance is not independently verified; 50 real photos is a sampling gate, not a product-grade accuracy certification",
            "A high image match does not prove foil, authenticity, grade, stamp or original card identity",
            "This dataset may be biased and cannot support population-wide accuracy claims without representative sampling",
            "No financial outcome or resale performance is measured by this benchmark",
        ],
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Benchmark private pHash/ORB index on distinct held-out photos")
    p.add_argument("dataset",help="Private JSON cases with human-attested labels")
    p.add_argument("--index",required=True,help="Local SQLite image feature index")
    p.add_argument("--query-root",required=True)
    p.add_argument("--reference-manifest",required=True)
    p.add_argument("--reference-image-root",required=True)
    p.add_argument("--out",default="private/reference_accuracy.json")
    args=p.parse_args(argv)
    matcher=ReferenceMatcher(args.index)
    cases=json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    manifest=json.loads(Path(args.reference_manifest).read_text(encoding="utf-8"))
    report=audit_references(matcher,cases,args.query_root,manifest,args.reference_image_root)
    target=Path(args.out)
    target.parent.mkdir(exist_ok=True,parents=True)
    target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"Evaluated {report['metrics']['cases']} held-out photos; result {target}")


if __name__=="__main__":
    main()
