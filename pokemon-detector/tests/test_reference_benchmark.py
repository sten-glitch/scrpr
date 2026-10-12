"""Test benchmark discipline with synthetic byte fixtures, not real card photos."""
import sys
import tempfile
import unittest
import hashlib
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reference_benchmark import ReferenceBenchmarkError, audit_references


class FakeMatcher:
    def match_entire_photo(self, raw):
        expected={
            b"positive-A":("VISUAL_CANDIDATE","demo:A"),
            b"positive-B":("ABSTAIN",None),
            b"positive-C":("VISUAL_CANDIDATE","demo:B"),
            b"negative-D":("ABSTAIN",None),
            b"negative-E":("VISUAL_CANDIDATE","demo:A"),
        }
        status,identity=expected[raw]
        return {
            "status":status,"matched_identity_key":identity,
            "candidates":[{"identity_key":identity,"phash_distance":7,"orb_good_matches":19}]
             if identity else [],
        }


class TestReferenceBenchmark(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.refs=self.root/"refs"
        self.queries=self.root/"queries"
        self.refs.mkdir()
        self.queries.mkdir()
        (self.refs/"a.png").write_bytes(b"source-reference-A")
        (self.refs/"b.png").write_bytes(b"source-reference-B")
        self.manifest={"references":[
            {"image_file":"a.png"}, {"image_file":"b.png"}
        ]}

    def case(self, id, photo, expected=None, kind="single", **kw):
        p=self.queries/f"{id}.png"
        p.write_bytes(photo)
        return {"case_id":id,"kind":kind,"split":"holdout",
                "image_file":p.name,"expected_identity_key":expected,
                "annotation_verified":True,
                "annotation_reference":"human_verified_test",**kw}

    def run_benchmark(self, records):
        return audit_references(FakeMatcher(),{"cases":records},self.queries,
                                self.manifest,self.refs)

    def test_metrics_count_false_positives_and_missed_positives(self):
        samples=[
            self.case("pA",b"positive-A","demo:A"),
            self.case("pB",b"positive-B","demo:B"),
            self.case("pC",b"positive-C","demo:C"),
            self.case("nD",b"negative-D",kind="negative"),
            self.case("nE",b"negative-E",kind="negative"),
        ]
        result=self.run_benchmark(samples)
        summary=result["metrics"]
        self.assertEqual(summary["cases"],5)
        self.assertEqual(summary["known_card_recall"],.3333)
        self.assertEqual(summary["wrong_identity_rate_on_positives"],.3333)
        self.assertEqual(summary["false_match_rate_on_negatives"],.5)
        self.assertEqual(summary["accepted_candidate_precision_on_labeled_cases"],.3333)
        self.assertEqual(summary["counts"]["wrong_identity"],1)
        self.assertEqual(summary["counts"]["no_identity"],1)
        self.assertEqual(summary["counts"]["false_match"],1)
        self.assertEqual(result["status"],"HUMAN_ATTESTED_HELDOUT_REFERENCE_BENCHMARK")

    def test_identical_reference_image_for_query_is_rejected_as_leakage(self):
        sample=self.case("leak",b"source-reference-A","demo:A")
        with self.assertRaisesRegex(ReferenceBenchmarkError,"leakage"):
            self.run_benchmark([sample])

    def test_duplicate_query_bytes_not_double_counted(self):
        q1=self.case("pos1",b"positive-A","demo:A")
        q2=self.case("pos2",b"positive-A","demo:A")
        with self.assertRaisesRegex(ReferenceBenchmarkError,"Repeated query"):
            self.run_benchmark([q1,q2])

    def test_ground_truth_attestation_required(self):
        q=self.case("pA",b"positive-A","demo:A")
        q["annotation_verified"]=False
        with self.assertRaisesRegex(ReferenceBenchmarkError,"Human-attested"):
            self.run_benchmark([q])
        q["annotation_verified"]=True
        q["annotation_reference"]=""
        with self.assertRaisesRegex(ReferenceBenchmarkError,"ground-truth"):
            self.run_benchmark([q])

    def test_holdout_only_not_training_or_same_sample(self):
        q=self.case("pA",b"positive-A","demo:A")
        q["split"]="training"
        with self.assertRaisesRegex(ReferenceBenchmarkError,"held-out"):
            self.run_benchmark([q])
        q["split"]="holdout"
        with self.assertRaisesRegex(ReferenceBenchmarkError,"unique"):
            self.run_benchmark([q,q])

    def test_malformed_negative_and_bbox_rejected(self):
        case=self.case("nD",b"negative-D","demo:A",kind="negative")
        with self.assertRaisesRegex(ReferenceBenchmarkError,"Negative"):
            self.run_benchmark([case])
        p=self.case("pB",b"positive-B","demo:B",bbox_xyxy=[1,0,0,1])
        with self.assertRaisesRegex(ReferenceBenchmarkError,"bbox"):
            self.run_benchmark([p])

    def test_distinct_binder_crops_same_photo_are_independent_cases_not_photos(self):
        one=self.case("region01",b"test-binder-photo","demo:A",
                      kind="binder",bbox_xyxy=[.05,.06,.43,.45],
                      photo_origin="real_photo")
        two=self.case("region02",b"test-binder-photo","demo:A",
                      kind="binder",bbox_xyxy=[.55,.50,.94,.96],
                      photo_origin="real_photo")
        two["image_file"]=one["image_file"]
        matched={"status":"VISUAL_CANDIDATE","matched_identity_key":"demo:A","candidates":[]}
        with patch("reference_benchmark._evaluate_photo",return_value=matched):
            output=self.run_benchmark([one,two])
        self.assertEqual(output["metrics"]["cases"],2)
        self.assertEqual(output["metrics"]["distinct_test_photos"],1)
        self.assertEqual(output["metrics"]["distinct_real_photos"],1)
        self.assertEqual(output["pilot_sample_gate"]["status"],"INSUFFICIENT_REAL_PHOTO_VALIDATION")

    def test_overlapping_regions_on_one_photo_rejected(self):
        one=self.case("region01",b"test-binder-photo","demo:A",
                      kind="binder",bbox_xyxy=[.05,.05,.43,.45])
        two=self.case("region02",b"test-binder-photo","demo:A",
                      kind="binder",bbox_xyxy=[.06,.06,.43,.46])
        two["image_file"]=one["image_file"]
        matched={"status":"VISUAL_CANDIDATE","matched_identity_key":"demo:A","candidates":[]}
        with patch("reference_benchmark._evaluate_photo",return_value=matched):
            with self.assertRaisesRegex(ReferenceBenchmarkError,"Repeated query region"):
                self.run_benchmark([one,two])

    def test_photo_changed_since_human_label_is_rejected(self):
        case=self.case("case_change",b"positive-A","demo:A",
                       photo_sha256="0"*64,photo_origin="real_photo")
        with self.assertRaisesRegex(ReferenceBenchmarkError,"changed after annotation"):
            self.run_benchmark([case])

    def test_real_photo_and_synthetic_provenance_never_claims_certified_accuracy(self):
        case=self.case("positive",b"positive-A","demo:A",photo_origin="real_photo")
        result=self.run_benchmark([case])
        self.assertEqual(result["metrics"]["distinct_real_photos"],1)
        self.assertFalse(result["pilot_sample_gate"]["accuracy_certified"])
        self.assertFalse(result["pilot_sample_gate"]["fifty_distinct_real_photos"])
        case2=self.case("synthetic",b"positive-B","demo:B",
                        photo_origin="synthetic_demo")
        result2=self.run_benchmark([case,case2])
        self.assertEqual(result2["metrics"]["distinct_synthetic_photos"],1)
        self.assertEqual(result2["metrics"]["distinct_real_photos"],1)

    def test_safe_relative_query_file_only(self):
        q=self.case("pA",b"positive-A","demo:A")
        q["image_file"]="../refs/a.png"
        with self.assertRaises(ValueError):
            self.run_benchmark([q])


if __name__=="__main__":
    unittest.main()
