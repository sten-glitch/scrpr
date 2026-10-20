"""Offline, safe HTML report for BIGSTEN real-photo validation."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reference_report import BenchmarkReportError, render_benchmark_report


def fixture():
    return {
        "status":"HUMAN_ATTESTED_HELDOUT_REFERENCE_BENCHMARK",
        "metrics":{
            "cases":3, "distinct_test_photos":3,
            "distinct_real_photos":2, "distinct_synthetic_photos":1,
            "known_card_recall":.5, "wrong_identity_rate_on_positives":.5,
            "false_match_rate_on_negatives":0., "abstain_rate":1/3,
            "ambiguous_rate":0., "accepted_candidate_precision_on_labeled_cases":.5,
            "counts":{"negative_cases":1,"positive_cases":2}},
        "pilot_sample_gate":{
            "status":"INSUFFICIENT_REAL_PHOTO_VALIDATION",
            "fifty_distinct_real_photos":False,
            "at_least_five_negative_cases":False,
            "at_least_three_evaluation_categories":True,
            "all_photo_origins_reviewed":True,
            "accuracy_certified":False},
        "by_kind":{
            "single":{"cases":2,"known_card_recall":.5,
                      "wrong_identity_rate_on_positives":.5,
                      "false_match_rate_on_negatives":None,"abstain_rate":.5},
            "negative":{"cases":1,"known_card_recall":None,
                        "wrong_identity_rate_on_positives":None,
                        "false_match_rate_on_negatives":0.,"abstain_rate":0.}},
        "cases":[
            {"case_id":"case<script>alert('x')</script>","kind":"single",
             "outcome":"wrong_identity","matcher_status":"VISUAL_CANDIDATE",
             "expected_identity_key":"tcgdex:some&id",
             "candidate_identity_key":"tcgdex:other"},
            {"case_id":"case_002","kind":"single","outcome":"correct",
             "matcher_status":"VISUAL_CANDIDATE","expected_identity_key":"demo:A",
             "candidate_identity_key":"demo:A"},
            {"case_id":"negative_001","kind":"negative","outcome":"correct_rejection",
             "matcher_status":"ABSTAIN","expected_identity_key":None,
             "candidate_identity_key":None},
        ],
        "limitations":["Not validated <img src=x onerror=alert(1)>"]
    }


class TestReferenceReport(unittest.TestCase):
    def test_render_stats_case_outcomes_and_no_external_assets(self):
        result=render_benchmark_report(fixture())
        self.assertIn("Real-photo validation is incomplete",result)
        self.assertIn("Known card recall",result)
        self.assertIn("50.0%",result)
        self.assertIn("False-match on negatives",result)
        self.assertIn("wrong_identity",result)
        self.assertIn("correct_rejection",result)
        self.assertIn("case&lt;script&gt;",result)
        self.assertNotIn("<script>alert(",result)
        self.assertNotIn("onerror=alert(1)>",result)
        self.assertNotIn("http://",result)
        self.assertNotIn("https://",result)
        self.assertNotIn("<img",result)

    def test_no_certified_accuracy_even_if_report_claims_ready_without_count(self):
        value=fixture()
        value["pilot_sample_gate"]["status"]="SAMPLE_READY_FOR_MANUAL_REVIEW"
        output=render_benchmark_report(value)
        self.assertIn("validation is incomplete",output)
        self.assertNotIn("Minimum sampling gate reached",output)
        value["pilot_sample_gate"]["accuracy_certified"]=True
        with self.assertRaisesRegex(BenchmarkReportError,"certified"):
            render_benchmark_report(value)

    def test_none_metrics_display_missing_samples_not_zero(self):
        report=render_benchmark_report(fixture())
        self.assertIn("N/A — missing samples",report)

    def test_reject_missing_or_invalid_benchmark_data(self):
        with self.assertRaises(BenchmarkReportError):
            render_benchmark_report({})
        with self.assertRaises(BenchmarkReportError):
            render_benchmark_report({"metrics":{},"pilot_sample_gate":{},"cases":[]})
        report=fixture()
        report["metrics"]["abstain_rate"]=2.0
        with self.assertRaisesRegex(BenchmarkReportError,"percentage"):
            render_benchmark_report(report)
        report=fixture()
        report["metrics"]["cases"]=-1
        with self.assertRaisesRegex(BenchmarkReportError,"count"):
            render_benchmark_report(report)


if __name__=="__main__":
    unittest.main()
