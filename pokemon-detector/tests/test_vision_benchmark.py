"""Synthetic structural checks for the benchmark, not an accuracy claim."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision_benchmark import benchmark, intersection_over_union


def label(idx=0, box=None, variant="holo", flags=None):
    return {
        "image_index": idx, "bbox_xyxy": box or [.1, .1, .4, .5],
        "name": "Charizard ex", "set": "151", "number": "199/165",
        "language": "en", "finish": variant, "condition": "NM",
        "flags": flags or [],
    }


def prediction(items, kind="binder"):
    return {"kind": kind, "summary": "Fixture", "observations": [
        {**x, "identity_confidence": x.get("identity_confidence", .95),
         "condition_confidence": .75, "photo_confidence": .95}
        for x in items]}


class TestBenchmark(unittest.TestCase):
    def test_iou(self):
        self.assertEqual(intersection_over_union([0, 0, 1, 1], [0, 0, 1, 1]), 1)
        self.assertEqual(intersection_over_union([0, 0, .2, .2], [.5, .5, 1, 1]), 0)
        self.assertAlmostEqual(intersection_over_union([0, 0, .5, .5], [.25, .25, .75, .75]), 1 / 7)

    def test_card_variant_mismatch_counted_even_when_object_detected(self):
        gold1 = label(flags=["possible_counterfeit"])
        gold2 = label(box=[.55, .1, .85, .5], variant="reverse")
        guessed = [label(flags=["possible_counterfeit"]),
                   label(box=[.55, .1, .85, .5], variant="holo"),
                   label(box=[.1, .6, .4, .9], flags=["possible_stock_photo"])]
        result = benchmark([{
            "case_id":"synthetic-binder", "kind":"binder", "image_count":1,
            "ground_truth":[gold1,gold2],
            "prediction":prediction(guessed),
        }])
        metrics = result["metrics"]
        self.assertEqual(metrics["counts"]["matched"], 2)
        self.assertEqual(metrics["counts"]["false_positive"], 1)
        self.assertEqual(metrics["counts"]["identity_mismatches"], 1)
        self.assertEqual(metrics["high_confidence_identity_errors"], 1)
        self.assertEqual(metrics["object_precision"], .6667)
        self.assertEqual(metrics["object_recall"], 1)
        self.assertEqual(metrics["exact_identity_accuracy_on_matched"], .5)
        self.assertEqual(metrics["risk_recall"], 1)
        self.assertEqual(metrics["risk_precision"], .5)
        self.assertEqual(result["cases_detail"][0]["identity_errors"][0]["wrong_fields"], ["finish"])

    def test_missed_cards_and_risk_flags_reported(self):
        expected = [label(), label(box=[.55, .1, .85, .5], flags=["possible_reseal"])]
        r = benchmark([{
            "case_id":"missing-one", "kind":"binder", "image_count":1,
            "ground_truth":expected, "prediction":prediction([label()]),
        }])
        self.assertEqual(r["metrics"]["object_recall"], .5)
        self.assertEqual(r["metrics"]["counts"]["missed_objects"], 1)
        self.assertEqual(r["metrics"]["counts"]["risk_false_negative"], 1)
        self.assertIsNone(r["metrics"]["risk_precision"])
        self.assertEqual(r["metrics"]["risk_recall"], 0)

    def test_different_images_never_spatially_matched(self):
        r = benchmark([{
            "case_id":"different-views", "kind":"single", "image_count":2,
            "ground_truth":[label(idx=0)],
            "prediction":prediction([label(idx=1)],kind="single"),
        }])
        self.assertEqual(r["metrics"]["counts"]["matched"], 0)
        self.assertEqual(r["metrics"]["counts"]["missed_objects"], 1)
        self.assertEqual(r["metrics"]["counts"]["false_positive"], 1)

    def test_empty_predictions_and_unknown_gold_fields(self):
        x = label()
        x["finish"] = "unknown"
        r = benchmark([{
            "case_id":"empty-preds", "kind":"single", "image_count":1,
            "ground_truth":[x], "prediction":prediction([], kind="single"),
        }])
        self.assertEqual(r["metrics"]["object_recall"], 0)
        self.assertIsNone(r["metrics"]["exact_identity_accuracy_on_matched"])
        r2 = benchmark([{
            "case_id":"unknown-finish", "kind":"single", "image_count":1,
            "ground_truth":[x], "prediction":prediction([label(variant="reverse")], kind="single"),
        }])
        self.assertEqual(r2["metrics"]["exact_identity_accuracy_on_matched"], 1)

    def test_invalid_dataset_cannot_produce_false_good_metrics(self):
        c = {"case_id":"x", "kind":"binder", "image_count":1,
             "ground_truth":[label()], "prediction":prediction([])}
        with self.assertRaises(ValueError):
            benchmark([c,c])
        with self.assertRaises(ValueError):
            benchmark([], iou_threshold=.5)
        with self.assertRaises(ValueError):
            benchmark([c], iou_threshold=1.5)
        with self.assertRaises(ValueError):
            benchmark([{**c, "image_count":0}])
        with self.assertRaises(ValueError):
            benchmark([{**c, "ground_truth":[label(idx=2)]}])


if __name__ == "__main__":
    unittest.main()
