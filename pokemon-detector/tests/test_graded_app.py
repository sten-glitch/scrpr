"""Local HTTP tests; no live marketplace calls or real accuracy claims."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_app import AlphaServer
from vision import call_vision_api, VisionError


class GradedAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = AlphaServer(0, [], workspace_path=Path(cls.temp.name)/"workspace.sqlite")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def request(self, path, body=None, origin=None):
        req=urllib.request.Request(self.url+path, data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type":"application/json", "Origin":origin or self.url})
        try:
            response=urllib.request.urlopen(req,timeout=10)
        except urllib.error.HTTPError as exc:
            response=exc
        with response:
            raw=response.read()
            return response.status, json.loads(raw) if 'application/json' in response.headers.get('Content-Type','') else raw

    def test_root_is_graded_old_workspace_retained(self):
        self.assertIn(b'Graded Intelligence',self.request('/')[1])
        self.assertIn(b'Opportunity Pipeline',self.request('/workspace')[1])

    def test_offline_certificate_query_saved_and_reloaded(self):
        code,result=self.request('/api/graded/search',{'query':'PSA 12345678'})
        self.assertEqual(code,200)
        self.assertEqual(result['external_api_calls'],0)
        self.assertEqual(result['query']['status'],'CERTIFICATE_QUERY')
        self.assertEqual(self.request('/api/graded/snapshot?id='+result['snapshot_id'])[1]['query'],result['query'])

    def test_missing_production_credentials_explicit(self):
        with patch.dict('os.environ',{},clear=True):
            _,result=self.request('/api/graded/search',{'query':'PSA 12345678','live':True,'environment':'production'})
        self.assertEqual(result['status'],'CREDENTIALS_UNAVAILABLE')
        self.assertEqual(result['external_api_calls'],0)

    def test_supply_evidence_gate_persists(self):
        rows=[{'marketplace':'EBAY_US','item_id':str(i),'identity_key':'fixture','grade':'10',
               'certificate':{'grader':'PSA','number':'12345678','evidence_status':'seller_claim'}} for i in range(3)]
        code,report=self.request('/api/graded/supply',{'listings':rows})
        self.assertEqual(code,200)
        self.assertEqual(report['counts']['unresolved_listings'],3)
        self.assertEqual(report['counts']['confirmed_certificate_groups'],0)

    def test_external_origin_and_bad_data_rejected(self):
        self.assertEqual(self.request('/api/graded/search',{},'https://evil.example')[0],403)
        self.assertEqual(self.request('/api/graded/supply',{'listings':[{}]})[0],422)
        self.assertEqual(self.request('/api/graded/certificate',{'images':[]})[0],422)

    def test_paid_default_disabled_even_with_key(self):
        with patch.dict('os.environ',{'VISION_API_KEY':'test'},clear=True), patch('vision.urllib.request.urlopen',side_effect=AssertionError('network')):
            with self.assertRaisesRegex(VisionError,'Paid vision disabled'):
                call_vision_api({})


if __name__=='__main__':
    unittest.main()
