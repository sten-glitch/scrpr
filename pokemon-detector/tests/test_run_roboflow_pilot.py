"""Roboflow full pilot orchestration smoke — no account, download or network."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_roboflow_pilot import run_pilot, FullPilotError, _choose_split


class TestOneCommandRoboflowPilot(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.dataset=self.root/"pilot"/"datasets"/"roboflow-detector"
        for a in ("test/images","test/labels","valid/images","valid/labels"):
            (self.dataset/a).mkdir(parents=True,exist_ok=True)
        self.calls=[]

    def fake_download(self,source,root):
        self.calls.append(("download",source,str(root)))
        return {"dataset_directory":str(self.dataset)}

    def fake_benchmark(self,path,**kwargs):
        self.calls.append(("benchmark",kwargs["split"],kwargs["source"]))
        return {
            "card_identity_accuracy_measured":False,
            "samples":{"evaluated":23},
            "metrics":{"precision":.63,"recall":.57,"f1":.6},
            "cases":[],"by_kind":{},
        }

    def fake_review(self,path,out,**kwargs):
        self.calls.append(("stage_review",kwargs["split"],kwargs["max_photos"]))
        return {"photo_count":19}

    def test_complete_pilot_writes_private_geometry_reports_not_identity_accuracy(self):
        with patch.dict(os.environ,{"ROBOFLOW_API_KEY":"MOCK_DO_NOT_PERSIST"}):
            with patch("run_roboflow_pilot.report_html",return_value="<html>boxes only</html>"):
                result=run_pilot(
                    root=self.root/"pilot",
                    download=self.fake_download,
                    benchmark=self.fake_benchmark,
                    stage_review=self.fake_review)
        self.assertEqual(result["photos_evaluated"],23)
        self.assertEqual(result["staged_for_human_review"],19)
        self.assertEqual(result["card_box_precision_vs_publisher_annotations"],.63)
        self.assertIsNone(result["exact_identity_accuracy"])
        self.assertEqual(self.calls[1],("benchmark","test","detector"))
        reports=self.root/"pilot"/"reports"
        self.assertTrue((reports/"detection.html").exists())
        content=(reports/"pilot-summary.json").read_text()
        self.assertNotIn("MOCK_DO_NOT_PERSIST",content)
        self.assertFalse(json.loads(content)["provider_data_rights_and_artwork_verified"])

    def test_no_key_fails_without_attempting_external_action(self):
        with patch.dict(os.environ,{"ROBOFLOW_API_KEY":""}):
            with self.assertRaisesRegex(FullPilotError,"ROBOFLOW_API_KEY"):
                run_pilot(root=self.root/"pilot",download=self.fake_download)
        self.assertEqual(self.calls,[])

    def test_reject_untrusted_split_and_bad_inputs(self):
        for args in ({"source":"unknown"},{"max_images":0},
                     {"review_count":201},{"max_images":True},{"review_count":False}):
            with self.subTest(args=args),self.assertRaises(FullPilotError):
                run_pilot(**args)
        with self.assertRaises(FullPilotError):
            _choose_split(self.dataset,"train")

    def test_refuse_provider_path_outside_selected_private_root(self):
        def escape(_source,root):
            return {"dataset_directory":str(self.root)}
        with patch.dict(os.environ,{"ROBOFLOW_API_KEY":"FAKE"}):
            with self.assertRaisesRegex(FullPilotError,"escaped"):
                run_pilot(root=self.root/"pilot",download=escape)

    def test_report_identity_claim_cannot_be_raised_from_yolo_boxes(self):
        def fake_bad(path,**kwargs):
            out=self.fake_benchmark(path,**kwargs)
            out["card_identity_accuracy_measured"]=True
            return out
        with patch.dict(os.environ,{"ROBOFLOW_API_KEY":"FAKE"}):
            with self.assertRaisesRegex(FullPilotError,"cannot claim"):
                run_pilot(root=self.root/"pilot",download=self.fake_download,
                          benchmark=fake_bad)

    def test_report_destination_is_not_silently_overwritten(self):
        (self.root/"pilot"/"reports").mkdir(parents=True)
        (self.root/"pilot"/"reports"/"old.json").write_text("{}")
        with patch.dict(os.environ,{"ROBOFLOW_API_KEY":"FAKE"}):
            with self.assertRaisesRegex(FullPilotError,"overwrite"):
                run_pilot(root=self.root/"pilot",download=self.fake_download)
        self.assertEqual(self.calls,[])


if __name__=="__main__":
    unittest.main()
