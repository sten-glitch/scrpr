"""Synthetic Roboflow-style YOLO export benchmark tests.

No marketplace data or actual Pokémon images; physical card identities are
not labeled, and these tests do not count toward the real-photo milestone.
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from external_detection_benchmark import (
    DetectionBenchmarkError, read_yolo_names, _parse_boxes,
    match_rectangles, benchmark_yolo, report_html,
)

try:
    from PIL import Image
    HAS_PIL=True
except ImportError:
    HAS_PIL=False


def synthetic_photo():
    im=Image.new("RGB",(420,600),"white")
    b=io.BytesIO()
    im.save(b,format="PNG")
    return b.getvalue()


@unittest.skipUnless(HAS_PIL,"Pillow required for synthetic image tests")
class TestYOLODetectionBenchmark(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/"test"/"images").mkdir(parents=True)
        (self.root/"test"/"labels").mkdir()
        (self.root/"train"/"images").mkdir(parents=True)
        (self.root/"data.yaml").write_text("names: ['card', 'background', 'unknown']\n")

    def add(self, name, label, contents=None):
        (self.root/"test"/"images"/(name+".png")).write_bytes(
            synthetic_photo() if contents is None else contents)
        (self.root/"test"/"labels"/(name+".txt")).write_text(label)

    def test_parse_yolo_class_names_and_require_card_label(self):
        self.assertEqual(read_yolo_names(self.root/"data.yaml")[0],"card")
        self.assertEqual(_parse_boxes("0 0.50 0.50 0.50 0.50",0),[[.25,.25,.75,.75]])
        self.assertEqual(_parse_boxes("1 0.50 0.50 0.50 0.50",0),[])
        for invalid in ("0 0.5 0.5 1.5 0.5","0 nan 0.5 0.2 0.2",
                        "0 0.5 0.5 0.2","a 0.5 0.5 0.2 0.2"):
            with self.subTest(label=invalid),self.assertRaises(DetectionBenchmarkError):
                _parse_boxes(invalid,0)

    def test_bipartite_matching_does_not_count_duplicate_box_twice(self):
        exact=[.2,.2,.8,.8]
        results=match_rectangles([exact,exact],[exact])
        self.assertEqual(results["true_positives"],1)
        self.assertEqual(results["false_positives"],1)
        self.assertEqual(results["false_negatives"],0)
        missed=match_rectangles([[0,0,.2,.2]],[[.5,.5,.9,.9]])
        self.assertEqual(missed["false_negatives"],1)

    def test_external_detection_only_and_no_identity_conclusion(self):
        self.add("card_A","0 0.5 0.5 0.5 0.5")
        self.add("negative_B","")
        # Two different valid PNGs, generated independently to avoid duplicate hash.
        from PIL import ImageDraw
        im=Image.open(io.BytesIO(synthetic_photo())).convert("RGB")
        ImageDraw.Draw(im).rectangle([20,25,70,80],fill="red")
        b=io.BytesIO()
        im.save(b,format="PNG")
        (self.root/"test"/"images"/"negative_B.png").write_bytes(b.getvalue())
        fake_predictions=[[[.25,.25,.75,.75]],[]]
        with patch("external_detection_benchmark.detect_card_boxes",side_effect=fake_predictions):
            r=benchmark_yolo(self.root,source="detector",max_images=10)
        self.assertEqual(r["metrics"]["true_positives"],1)
        self.assertEqual(r["metrics"]["false_positives"],0)
        self.assertEqual(r["metrics"]["false_negatives"],0)
        self.assertEqual(r["metrics"]["precision"],1.0)
        self.assertEqual(r["samples"]["evaluated"],2)
        self.assertFalse(r["human_exact_card_id_labels"])
        self.assertFalse(r["commercial_rights_cleared"])
        self.assertFalse(r["card_identity_accuracy_measured"])
        self.assertEqual(r["status"],"DETECTION_ONLY_ON_EXTERNAL_PUBLISHED_ANNOTATIONS")
        report=report_html(r)
        self.assertIn("NOT A POKÉMON CARD ID ACCURACY TEST.",report)
        self.assertIn("100.0%",report)

    def test_empty_split_and_train_split_never_evaluated(self):
        with self.assertRaisesRegex(DetectionBenchmarkError,"train"):
            benchmark_yolo(self.root,source="binder",split="train")
        with self.assertRaisesRegex(DetectionBenchmarkError,"No evaluation photos"):
            benchmark_yolo(self.root,source="detector")

    def test_reject_byte_identical_train_copy(self):
        self.add("same_photo","0 0.5 0.5 0.5 0.5")
        (self.root/"train"/"images"/"train_copy.png").write_bytes(
            (self.root/"test"/"images"/"same_photo.png").read_bytes()
        )
        with self.assertRaisesRegex(DetectionBenchmarkError,"No valid independent"):
            benchmark_yolo(self.root,source="detector")

    def test_unmapped_class_fails_closed(self):
        (self.root/"data.yaml").write_text("names: ['background', 'other']\n")
        self.add("testme","0 0.5 0.5 0.5 0.5")
        with self.assertRaisesRegex(DetectionBenchmarkError,"class 'card'"):
            benchmark_yolo(self.root,source="detector")
        with patch("external_detection_benchmark.detect_card_boxes",
                   return_value=[[.25,.25,.75,.75]]):
            x=benchmark_yolo(self.root,source="detector",card_class_id=0)
        self.assertEqual(x["metrics"]["true_positives"],1)
        self.assertEqual(x["class_names"][0],"background")

    def test_segmentation_polygon_to_box_is_only_geometry(self):
        boxes=_parse_boxes("0 0.20 0.20 0.80 0.20 0.80 0.90 0.20 0.90",0)
        self.assertEqual(len(boxes),1)
        self.assertAlmostEqual(boxes[0][0],.2)
        self.assertAlmostEqual(boxes[0][3],.9)
        with self.assertRaises(DetectionBenchmarkError):
            _parse_boxes("0 0.20 0.20 0.80 0.20 0.80 1.5",0)

    def test_scanner_polygon_source_reports_segmentation_as_box(self):
        self.add("segmented_card","0 0.25 0.25 0.75 0.25 0.75 0.75 0.25 0.75")
        with patch("external_detection_benchmark.detect_card_boxes",
                   return_value=[[.25,.25,.75,.75]]):
            result=benchmark_yolo(self.root,source="scanner")
        self.assertTrue(result["segmentation_polygons_evaluated_as_boxes"])
        self.assertEqual(result["metrics"]["true_positives"],1)
        self.assertFalse(result["card_identity_accuracy_measured"])

    def test_html_does_not_render_untrusted_source_name_as_markup(self):
        self.add("safephoto","")
        with patch("external_detection_benchmark.detect_card_boxes",return_value=[]):
            r=benchmark_yolo(self.root,source="binder")
        r["cases"][0]["image"]="<script>alert('x')</script>"
        text=report_html(r)
        self.assertNotIn("<script>alert",text)
        self.assertIn("&lt;script&gt;",text)


if __name__=="__main__":
    unittest.main()
