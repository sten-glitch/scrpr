"""Localhost-only human annotation server API, no cloud data or real photos."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dataset_review import PhotoReviewStore
from photo_review_server import ReviewServer

PNG=b"\x89PNG\r\n\x1a\nsynthetic-photo-review-server"
CAT=[{"identity_key":"demo:one","name":"Synthetic Card One",
      "number":"1/1","finish":"normal","language":"en"}]


class TestReviewServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        (cls.root/"photos").mkdir()
        (cls.root/"photos"/"image.png").write_bytes(PNG)
        store=PhotoReviewStore(cls.root/"photos",cls.root/"private"/"reviewed.json",CAT)
        cls.server=ReviewServer(store,0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url="http://127.0.0.1:"+str(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.tmp.cleanup()

    def request(self,path,method="GET",body=None,headers=None):
        payload=None if body is None else json.dumps(body).encode("utf-8")
        req=urllib.request.Request(self.url+path,data=payload,method=method,
                                   headers=headers or {})
        try:
            with urllib.request.urlopen(req,timeout=4) as resp:
                return resp.status,resp.read(),resp.headers
        except urllib.error.HTTPError as exc:
            return exc.code,exc.read(),exc.headers

    def data(self):
        return {
            "case_id":"case_http_001",
            "kind":"single", "split":"holdout", "image_file":"image.png",
            "expected_identity_key":"demo:one",
            "annotation_verified":True,
            "reviewer":"test-reviewer",
            "annotation_reference":"manual-test-001",
        }

    def test_local_health_and_content_security(self):
        code,binary,headers=self.request("/")
        self.assertEqual(code,200)
        self.assertIn(b"BIGSTEN",binary)
        self.assertIn("Content-Security-Policy",headers)
        code,script,_=self.request("/app.js")
        self.assertEqual(code,200)
        self.assertIn(b"/api/label",script)
        code,binary,_=self.request("/api/summary")
        self.assertEqual(code,200)
        self.assertEqual(json.loads(binary)["photo_count"],1)

    def test_source_image_endpoint_restricted_to_allowlist(self):
        code,binary,headers=self.request("/api/photo/image.png")
        self.assertEqual(code,200)
        self.assertEqual(binary,PNG)
        self.assertEqual(headers.get("Content-Type"),"image/png")
        for bad in ("/api/photo/../secret.json","/api/photo/%2e%2e%2fpasswd",
                    "/api/photo/unknown.jpg","/api/photo/%2Fetc%2Fpasswd"):
            with self.subTest(path=bad):
                code,_,_=self.request(bad)
                self.assertIn(code,{404,403})

    def test_catalog_search_is_local_and_small(self):
        code,data,_=self.request("/api/catalog?q=Synthetic")
        self.assertEqual(code,200)
        found=json.loads(data)["candidates"]
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["identity_key"],"demo:one")
        code,data,_=self.request("/api/catalog?q=x")
        self.assertEqual(code,200)
        self.assertFalse(json.loads(data)["candidates"])

    def test_cross_origin_post_rejected(self):
        body=self.data()
        code,_,_=self.request("/api/label","POST",body,
            {"Content-Type":"application/json","Origin":"https://malicious.example"})
        self.assertEqual(code,403)
        code,_,_=self.request("/api/label","POST",body,
            {"Content-Type":"application/json"})
        self.assertEqual(code,403)
        code,_,_=self.request("/","GET",headers={"Host":"evil.example"})
        self.assertEqual(code,403)

    def test_invalid_and_valid_human_label(self):
        body=self.data()
        headers={"Content-Type":"application/json","Origin":self.url}
        code,_,_=self.request("/api/label","POST",{**body,"annotation_verified":False},headers)
        self.assertEqual(code,422)
        code,content,_=self.request("/api/label","POST",body,headers)
        self.assertEqual(code,200)
        self.assertTrue(json.loads(content)["saved"]["photo_sha256"])
        code,content,headers=self.request("/api/export")
        self.assertEqual(code,200)
        self.assertIn("attachment",headers["Content-Disposition"])
        report=json.loads(content)
        self.assertEqual(report["dataset_type"],"PRIVATE_HUMAN_ATTESTED_HOLDOUT")
        self.assertEqual(len(report["cases"]),1)
        self.assertEqual(report["cases"][0]["expected_identity_key"],"demo:one")

    def test_no_arbitrary_file_serve(self):
        for endpoint in ("/favicon.ico","/.git/config","/api/secret","/data/private.json"):
            code,_,_=self.request(endpoint)
            self.assertEqual(code,404)


if __name__=="__main__":
    unittest.main()
