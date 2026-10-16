"""Offline tests for BIGSTEN Local Alpha, including loopback access controls.

All listing images, card labels and price figures in these fixtures are
synthetic. No external network or paid model access is exercised.
"""
import base64
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_app import AlphaInputError, AlphaServer, analyze_request, _decode_uploads
from local_cv import LocalCVError

PNG=base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+y0QcAAAAASUVORK5CYII="
)


def request_data(title="Charizard PSA 10",images=True):
    return {
        "title":title,"kind":"single","asking_eur":150,
        "description":"rare collectible",
        "images":[{"mime":"image/png","base64":base64.b64encode(PNG).decode()}] if images else [],
    }


def annotated(grade=None,company=None,slab=False):
    return {"kind":"single","observations":[{
        "image_index":0,"bbox_xyxy":[.1,.1,.8,.9],
        "name":"Charizard","set":"Base","number":"4/102",
        "language":"en","finish":"holo","condition":"unknown",
        "slab_visible":slab,"grade_company":company,"grade_number":grade,
        "photo_confidence":.95,"identity_confidence":.7,
        "condition_confidence":.3,
    }]}


class TestAlphaLogic(unittest.TestCase):
    def test_text_only_is_explicitly_not_image_analyzed(self):
        report=analyze_request(request_data(images=False))
        self.assertEqual(report["status"],"TEXT_ONLY_NO_VISUAL_PROOF")
        self.assertIsNone(report["assessment"])
        self.assertEqual(report["listing_truth"]["status"],"REVIEW_REQUIRED")

    def test_psa_claim_and_raw_visible_photo_yields_conflict(self):
        payload=request_data()
        payload["observation"]=annotated(slab=False)
        report=analyze_request(payload)
        self.assertEqual(report["listing_truth"]["status"],"CONFLICT_DETECTED")
        self.assertEqual(report["assessment"]["decision"],"REVIEW")
        self.assertIsNone(report["assessment"]["roi"])
        self.assertEqual(report["image_analysis"]["mode"],"manual_observations")
        self.assertEqual(len(report["image_manifest"]),1)
        self.assertEqual(report["image_manifest"][0]["reference"],"image_1.png")
        self.assertNotIn("base64",json.dumps(report))

    def test_consistent_psa_label_still_not_authenticated(self):
        payload=request_data()
        payload["observation"]=annotated(grade="10",company="PSA",slab=True)
        report=analyze_request(payload)
        self.assertEqual(report["listing_truth"]["status"],"VISUALLY_CONSISTENT_NOT_AUTHENTICATED")
        self.assertEqual(report["assessment"]["decision"],"REVIEW")
        self.assertIsNone(report["assessment"]["score"])

    def test_no_cv_keeps_uncertainty_not_fake_scans(self):
        payload=request_data()
        with patch("local_app.combine_local_observations",side_effect=LocalCVError("No optional CV")):
            report=analyze_request(payload)
        self.assertEqual(report["image_analysis"]["mode"],"cv_unavailable")
        self.assertEqual(report["image_analysis"]["observations"],0)
        self.assertEqual(report["listing_truth"]["status"],"REVIEW_REQUIRED")
        self.assertEqual(report["assessment"]["decision"],"REVIEW")

    def test_entire_photo_reference_fallback_never_proves_card_identity(self):
        payload=request_data(title="Charizard PSA 10")
        matcher=unittest.mock.Mock()
        matcher.match_observations.return_value=[]
        matcher.match_entire_photo.return_value={
            "status":"VISUAL_CANDIDATE",
            "matched_identity_key":"tcgdex:fictional-1",
            "reason":"Local photo resembles private reference, not proof",
            "candidates":[{"identity_key":"tcgdex:fictional-1",
                           "phash_distance":0,"orb_good_matches":25,
                           "status":"CANDIDATE_NOT_VERIFIED"}],
        }
        no_contours={"kind":"single","observations":[],"uncertainties":["No card rectangle found"]}
        with patch("local_app.combine_local_observations",return_value=no_contours):
            report=analyze_request(payload, matcher=matcher)
        self.assertEqual(report["visual_reference_matches"][0]["scope"],"whole_photo")
        self.assertEqual(report["visual_reference_matches"][0]["status"],"VISUAL_CANDIDATE")
        self.assertIsNone(report["assessment"]["roi"])
        self.assertEqual(report["assessment"]["decision"],"REVIEW")
        self.assertEqual(len(report["visual_evidence"]["observations"]),0)
        matcher.match_entire_photo.assert_called_once()

    def test_input_guards(self):
        for payload in [
            {"title":"a","asking_eur":0,"kind":"single","images":[]},
            {"title":"a","asking_eur":True,"kind":"single","images":[]},
            {"title":"a","asking_eur":12,"kind":"other","images":[]},
            {"title":"x"*301,"asking_eur":12,"kind":"single","images":[]},
            {"title":"A","asking_eur":4,"kind":"single",
             "images":[{"mime":"image/png","base64":base64.b64encode(b"not an image").decode()}]},
            {"title":"A","asking_eur":4,"kind":"single","images":[{"mime":"text/html","base64":"YQ=="}]},
            {"title":"A","asking_eur":4,"kind":"single","images":[{}]},
        ]:
            with self.subTest(payload=str(payload)[:80]), self.assertRaises(AlphaInputError):
                analyze_request(payload)

    def test_too_many_images_and_invalid_binary(self):
        with self.assertRaises(AlphaInputError):
            _decode_uploads([{"mime":"image/png","base64":base64.b64encode(PNG).decode()}]*5)
        with self.assertRaises(AlphaInputError):
            _decode_uploads([{"mime":"image/png","base64":"!!!"}])

    def test_export_has_no_local_file_path(self):
        payload=request_data()
        payload["observation"]=annotated(slab=False)
        result=analyze_request(payload)
        text=json.dumps(result)
        self.assertNotIn("bigsten-alpha-",text)
        self.assertNotIn("TemporaryDirectory",text)


class TestAlphaHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Bind to loopback only with random available port for test isolation.
        cls.server=AlphaServer(0,[])
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url="http://127.0.0.1:"+str(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _send(self,method,path,data=None,headers=None):
        raw=None if data is None else json.dumps(data).encode()
        req=urllib.request.Request(self.url+path,data=raw,method=method,
                                   headers=headers or {})
        try:
            with urllib.request.urlopen(req,timeout=5) as res:
                return res.status,res.read(),dict(res.headers)
        except urllib.error.HTTPError as ex:
            return ex.code,ex.read(),dict(ex.headers)

    def test_health_bound_local(self):
        code,body,headers=self._send("GET","/api/health")
        self.assertEqual(code,200)
        data=json.loads(body)
        self.assertFalse(data["public_deployment_allowed"])
        self.assertFalse(data["capabilities"]["rfdetr_enabled"])
        self.assertIn(data["capabilities"]["photo_detector"],{"opencv","unavailable"})
        self.assertEqual(self.server.server_address[0],"127.0.0.1")
        self.assertEqual(headers["Cache-Control"],"no-store")

    def test_static_ui_and_script_available(self):
        code,body,headers=self._send("GET","/")
        self.assertEqual(code,200)
        self.assertIn(b"BIGSTEN",body)
        self.assertIn("Content-Security-Policy",headers)
        code,js,_=self._send("GET","/app.js")
        self.assertEqual(code,200)
        self.assertIn(b"/api/analyze",js)

    def test_json_only_with_local_origin(self):
        code,body,_=self._send("POST","/api/analyze",request_data(images=False),
                               headers={"Content-Type":"application/json",
                                        "Origin":self.url})
        self.assertEqual(code,200)
        self.assertIn("TEXT_ONLY_NO_VISUAL_PROOF",body.decode())

    def test_cross_site_origin_and_host_rejected(self):
        code,_,_=self._send("POST","/api/analyze",request_data(images=False),
                            headers={"Content-Type":"application/json",
                                     "Origin":"https://evil.example"})
        self.assertEqual(code,403)
        code,_,_=self._send("GET","/",headers={"Host":"evil.example"})
        self.assertEqual(code,403)

    def test_plain_text_content_type_rejected(self):
        code,_,_=self._send("POST","/api/analyze",request_data(images=False),
                            headers={"Content-Type":"text/plain"})
        self.assertEqual(code,415)

    def test_unknown_endpoints_not_served(self):
        code,_,_=self._send("GET","/../../etc/passwd")
        self.assertEqual(code,404)


if __name__=="__main__":
    unittest.main()
