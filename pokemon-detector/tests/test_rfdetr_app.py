"""Synthetic HTTP integration tests; the detector is a stub, not real weights."""
import base64
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_app import AlphaServer
from rfdetr_card_detector import RFDETRCardError

try:
    import cv2
    from PIL import Image
    HAS_CV=True
except ImportError:
    HAS_CV=False


@unittest.skipUnless(HAS_CV,"Optional image dependencies unavailable")
class TestRFDETRWebIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        class Detector:
            checkpoint_sha256="a"*64
            threshold=.6
            calls=0
            fail=False
            def __call__(self,image):
                self.calls+=1
                if self.fail:
                    raise RFDETRCardError("RF-DETR local inference failed")
                return [[.1,.1,.9,.9]]
        self.detector=Detector()
        self.server=AlphaServer(0,[],workspace_path=Path(self.temp.name)/"private/app.sqlite",
                                card_detector=self.detector)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.url=f"http://127.0.0.1:{self.server.server_address[1]}"
        buffer=io.BytesIO()
        Image.new("RGB",(200,300),"gray").save(buffer,format="PNG")
        self.payload={"title":"Synthetic RF-DETR integration test","asking_eur":10,
                      "kind":"single","source":"manual",
                      "images":[{"mime":"image/png","base64":base64.b64encode(buffer.getvalue()).decode()}]}

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self,path,payload=None):
        req=urllib.request.Request(self.url+path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type":"application/json","Origin":self.url})
        try:
            response=urllib.request.urlopen(req,timeout=10)
        except urllib.error.HTTPError as exc:
            response=exc
        with response:
            return response.status,json.load(response)

    def test_upload_save_and_read_keep_detector_provenance(self):
        code,health=self.request("/api/health")
        self.assertEqual(health["capabilities"]["photo_detector"],"rfdetr_nano")
        self.assertTrue(health["capabilities"]["rfdetr_enabled"])
        code,report=self.request("/api/analyze",self.payload)
        self.assertEqual(code,200)
        self.assertEqual(report["image_analysis"]["mode"],"rfdetr_offline")
        self.assertEqual(report["image_analysis"]["observations"],1)
        code,lead=self.request("/api/workspace/analyze",self.payload)
        self.assertEqual(code,201)
        code,saved=self.request("/api/workspace/listing?id="+lead["id"])
        self.assertEqual(saved["analysis"]["image_analysis"]["checkpoint_sha256"],"a"*64)
        self.assertEqual(saved["analysis"]["image_analysis"]["confidence_threshold"],.6)
        self.assertEqual(self.detector.calls,2)
        self.assertNotIn("base64",json.dumps(saved))

    def test_failed_inference_does_not_fall_back_or_save_a_record(self):
        self.detector.fail=True
        code,error=self.request("/api/workspace/analyze",self.payload)
        self.assertEqual(code,422)
        self.assertIn("RF-DETR",error["error"])
        _,dashboard=self.request("/api/workspace/dashboard")
        self.assertEqual(dashboard["listings_total"],0)

    def test_manual_observations_bypass_detector_without_claiming_model_use(self):
        self.detector.fail=True
        self.payload["observation"]={"kind":"single","observations":[],"inventory_complete":False}
        code,report=self.request("/api/analyze",self.payload)
        self.assertEqual(code,200)
        self.assertEqual(report["image_analysis"]["mode"],"manual_observations")
        self.assertNotIn("checkpoint_sha256",report["image_analysis"])
        self.assertEqual(self.detector.calls,0)
