"""RF-DETR card-only adapter and paired benchmark tests, NO torch or paid model.

All simulated detections and card images are synthetic. This tests failure
guards and paired scoring logic, not actual RF-DETR performance.
"""
from __future__ import annotations

import io
import json
import copy
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rfdetr_card_detector import (
    RFDETRCardDetector,RFDETRCardError,_class_positions,_normalized_boxes,
)
from compare_rfdetr import (
    CompareError,compare_reports,report_html,run_paired_benchmark,
)
from external_detection_benchmark import benchmark_yolo,DetectionBenchmarkError

try:
    import cv2
    import numpy as np
    from PIL import Image
    HAS_CV=True
except ImportError:
    HAS_CV=False


class TestCardClasses(unittest.TestCase):
    def test_must_be_specific_dedicated_card_class(self):
        self.assertEqual(_class_positions(["background","card"]),frozenset((1,)))
        self.assertEqual(_class_positions({0:"Pokemon-card",1:"background"}),frozenset((0,)))
        self.assertEqual(_class_positions(["trading_card"]),frozenset((0,)))

    def test_coco_classes_and_lookalikes_fail_closed(self):
        for labels in (["person","book","cell phone","sports ball"],
                       ["book"],[],["credit card"],["playing card"],
                       ["card","Pokemon card"]):
            with self.subTest(labels=labels),self.assertRaisesRegex(RFDETRCardError,"class"):
                _class_positions(labels)

    def test_bad_class_maps_cannot_be_passed(self):
        for classes in ({-1:"card"},{0:True},"card",None):
            with self.subTest(classes=classes),self.assertRaises(RFDETRCardError):
                _class_positions(classes)


class TestBoxConversion(unittest.TestCase):
    def test_pixel_space_xyxy_is_normalized_and_filtered_by_card_class(self):
        d=SimpleNamespace(
            xyxy=[[20,10,150,80],[0,0,200,100],[-2,-3,210,110]],
            class_id=[1,0,1])
        normalized=_normalized_boxes(d,class_id=1,width=200,height=100)
        self.assertEqual(len(normalized),2)
        self.assertEqual(normalized[0],[.1,.1,.75,.8])
        self.assertEqual(normalized[1],[0,0,1,1])

    def test_invalid_prediction_values_and_limits_fail_closed(self):
        for xyxy,ids in [
            ([[float("nan"),0,200,100]],[0]),
            ([[0,0,200,100]],[0,1]),
            ([[0,0]],[0]),
        ]:
            with self.subTest(xyxy=xyxy),self.assertRaises(RFDETRCardError):
                _normalized_boxes(SimpleNamespace(xyxy=xyxy,class_id=ids),
                                  class_id=0,width=200,height=100)
        many=SimpleNamespace(xyxy=[[0,0,100,100]]*3,class_id=[0]*3)
        with self.assertRaisesRegex(RFDETRCardError,"More trading"):
            _normalized_boxes(many,class_id=0,width=200,height=100,max_boxes=2)


@unittest.skipUnless(HAS_CV,"Optional image libraries unavailable")
class TestOptionalRFDETRCardDetector(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.ckpt=self.root/"fine_tuned.pth"
        self.ckpt.write_bytes(b"SYNTHETIC_TEST_NOT_TORCH_CHECKPOINT")

    def test_card_detector_calls_fake_checkpoint_and_filters_classes(self):
        prediction=SimpleNamespace(
            xyxy=np.asarray([[10,20,100,120],[0,0,50,50]]),
            class_id=np.asarray([1,0]))
        model=SimpleNamespace(
            class_names=["background","card"],
            predict=lambda frame,threshold: prediction)
        adapter=RFDETRCardDetector(self.ckpt,loader=lambda path:model)
        self.assertEqual(adapter.card_class_id,1)
        self.assertEqual(len(adapter.checkpoint_sha256),64)
        photo=np.full((200,200,3),150,dtype=np.uint8)
        boxes=adapter(photo)
        self.assertEqual(boxes,[[.05,.1,.5,.6]])

    def test_pretrained_coco_detector_is_rejected(self):
        model=SimpleNamespace(
            class_names=["person","bicycle","book","cell phone"],
            predict=lambda *_args,**_kwargs:None)
        with self.assertRaisesRegex(RFDETRCardError,"COCO"):
            RFDETRCardDetector(self.ckpt,loader=lambda path:model)

    def test_missing_checkpoint_not_downloaded(self):
        with self.assertRaisesRegex(RFDETRCardError,"trusted"):
            RFDETRCardDetector(self.root/"missing.pth",
                               loader=lambda path:None)
        with self.assertRaises(RFDETRCardError):
            RFDETRCardDetector(self.ckpt,threshold=0,loader=lambda path:None)
        with self.assertRaises(RFDETRCardError):
            RFDETRCardDetector(self.ckpt,threshold=float("nan"),
                               loader=lambda path:None)

    def test_checkpoint_symlink_is_rejected(self):
        link=self.root/"linked.pth"
        try:
            link.symlink_to(self.ckpt)
        except (OSError,NotImplementedError):
            self.skipTest("OS does not allow symlinks")
        with self.assertRaisesRegex(RFDETRCardError,"symlinks"):
            RFDETRCardDetector(link,loader=lambda path:None)


@unittest.skipUnless(HAS_CV,"Optional image libraries unavailable")
class TestPairedComparison(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for path in ("test/images","test/labels","train/images"):
            (self.root/path).mkdir(parents=True)
        (self.root/"data.yaml").write_text("names: ['card','background']\n")
        self.ckpt=self.root/"model.pth"
        self.ckpt.write_bytes(b"SYNTHETIC_NOT_A_REAL_MODEL")

    def photo(self,name,label,tone):
        img=np.full((350,250,3),tone,dtype=np.uint8)
        ok,buf=cv2.imencode(".png",img)
        self.assertTrue(ok)
        (self.root/"test/images"/f"{name}.png").write_bytes(buf.tobytes())
        (self.root/"test/labels"/f"{name}.txt").write_text(label)

    def test_same_test_split_and_traces(self):
        self.photo("case01","0 0.5 0.5 0.5 0.5",100)
        self.photo("case02","",170)
        # OpenCV predicts 1 true card plus 1 false positive.
        mock_cv=[[[.25,.25,.75,.75]],[[.1,.1,.7,.7]]]
        rf_rows=[
            SimpleNamespace(xyxy=np.array([[62.5,87.5,187.5,262.5]]),class_id=np.array([0])),
            SimpleNamespace(xyxy=np.zeros((0,4)),class_id=np.zeros((0,))),
        ]
        idx=[0]
        def predict(_image,threshold):
            item=rf_rows[idx[0]]
            idx[0]+=1
            return item
        model=SimpleNamespace(class_names=["card","background"],predict=predict)
        with patch("external_detection_benchmark.detect_card_boxes",side_effect=mock_cv):
            report=run_paired_benchmark(
                self.root,self.ckpt,source="detector",max_images=2,
                loader=lambda _path:model)
        self.assertEqual(report["evaluated_photos"],2)
        self.assertEqual(report["opencv"]["tp"],1)
        self.assertEqual(report["opencv"]["fp"],1)
        self.assertEqual(report["rfdetr_nano"]["tp"],1)
        self.assertEqual(report["rfdetr_nano"]["fp"],0)
        self.assertTrue(report["same_evaluated_photos"])
        self.assertIsNone(report["actual_exact_card_identity_accuracy"])
        html_report=report_html(report)
        self.assertIn("Paired metrics",html_report)
        self.assertIn("Mean detector time",html_report)
        self.assertIn("NOT exact Pokémon identity accuracy",html_report)

    def test_detector_inference_failure_fails_whole_benchmark(self):
        self.photo("case01","0 0.5 0.5 0.5 0.5",100)
        with self.assertRaisesRegex(DetectionBenchmarkError,"benchmark incomplete"):
            benchmark_yolo(self.root,source="detector",
                           detector=lambda _img:(_ for _ in ()).throw(RuntimeError("GPU fail")),
                           detector_name="broken-rfdetr")

    def test_invalid_predictions_cannot_be_silently_skipped(self):
        self.photo("case01","0 0.5 0.5 0.5 0.5",100)
        with self.assertRaisesRegex(DetectionBenchmarkError,"malformed"):
            benchmark_yolo(self.root,source="detector",
                           detector=lambda _img:[[float("nan"),0,1,1]],
                           detector_name="bad-model")

    def test_unpaired_photos_are_not_reported_as_fair_comparison(self):
        self.photo("case01","0 0.5 0.5 0.5 0.5",100)
        self.photo("case02","",170)
        with patch("external_detection_benchmark.detect_card_boxes",return_value=[]):
            baseline=benchmark_yolo(self.root,source="detector")
        model_report=copy.deepcopy(baseline)
        model_report["cases"][0]["image"]="not-the-same-photo.jpg"
        with self.assertRaisesRegex(CompareError,"Different photos"):
            compare_reports(baseline,model_report)

    def test_photo_content_sha_mismatch_rejects_paired_claim(self):
        self.photo("case01","0 0.5 0.5 0.5 0.5",100)
        with patch("external_detection_benchmark.detect_card_boxes",return_value=[]):
            baseline=benchmark_yolo(self.root,source="detector")
        self.assertEqual(len(baseline["cases"][0]["image_sha256"]),64)
        self.assertGreaterEqual(baseline["inference_measurement"]["mean_ms_per_image"],0)
        alternate=copy.deepcopy(baseline)
        alternate["cases"][0]["image_sha256"]="0"*64
        with self.assertRaisesRegex(CompareError,"bytes"):
            compare_reports(baseline,alternate)

    def test_html_escapes_unsafe_image_names(self):
        self.photo("case01","",100)
        with patch("external_detection_benchmark.detect_card_boxes",return_value=[]):
            baseline=benchmark_yolo(self.root,source="detector")
        report=compare_reports(baseline,baseline)
        report["per_photo"][0]["image"]="<script>alert(1)</script>"
        text=report_html(report)
        self.assertIn("&lt;script&gt;",text)
        self.assertNotIn("<script>alert",text)


if __name__=="__main__":
    unittest.main()
