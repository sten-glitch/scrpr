"""BIGSTEN local workbench HTTP contract tests on loopback only."""
import base64
import datetime as dt
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_app import AlphaServer
from tests.test_radar_ingest import feed


class TestWorkspaceAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.db=Path(cls.temp.name)/"private"/"workspace.sqlite"
        cls.server=AlphaServer(0,[],workspace_path=str(cls.db))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base="http://127.0.0.1:"+str(cls.server.server_address[1])
        cls.day=dt.datetime.now(dt.timezone.utc).date().isoformat()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=4)
        cls.temp.cleanup()

    def query(self,verb,url,body=None,headers=None):
        data=None if body is None else json.dumps(body).encode()
        req=urllib.request.Request(self.base+url,data=data,method=verb,
                                   headers=headers or {"Content-Type":"application/json",
                                                       "Origin":self.base})
        try:
            with urllib.request.urlopen(req,timeout=7) as r:
                raw=r.read()
                return r.status,json.loads(raw) if "application/json" in r.headers.get("Content-Type","") else raw
        except urllib.error.HTTPError as exc:
            raw=exc.read()
            return exc.code,json.loads(raw) if "application/json" in exc.headers.get("Content-Type","") else raw

    def test_full_manual_lead_scenario_purchase_sale_export(self):
        status,body=self.query("POST","/api/workspace/listings",{
            "title":"Synthetic vintage sale",
            "description":"Seller says PSA 10","kind":"single",
            "source":"community","asking_eur":100,"source_url":""})
        self.assertEqual(status,201)
        self.assertEqual(body["analysis"]["status"],"TEXT_ONLY_NO_VISUAL_PROOF")
        self.assertEqual(body["status"],"REVIEW")
        id=body["id"]
        status,board=self.query("GET","/api/workspace/dashboard")
        self.assertEqual(status,200)
        self.assertGreaterEqual(board["listings_total"],1)
        status,lead=self.query("GET","/api/workspace/listing?id="+id)
        self.assertEqual(status,200)
        self.assertEqual(lead["id"],id)
        status,watch=self.query("POST","/api/workspace/status",{
            "id":id,"status":"WATCHLIST"})
        self.assertEqual(status,200)
        self.assertEqual(watch["status"],"WATCHLIST")

        assumption={"target_resale_eur":200,"selling_fee_pct":10,
                    "inbound_shipping_eur":5,"purchase_taxes_eur":0,
                    "customs_eur":0,"buyer_fees_eur":0,
                    "outbound_shipping_eur":5,"packaging_eur":2,
                    "other_selling_eur":0}
        status,out=self.query("POST","/api/workspace/scenario",{
            "id":id,"assumptions":assumption})
        self.assertEqual(status,200)
        self.assertEqual(out["scenario"]["result"]["status"],"HYPOTHETICAL_ONLY")
        self.assertEqual(out["scenario"]["result"]["net_profit_eur"],68)

        status,bought=self.query("POST","/api/workspace/purchase",{
            "id":id,"purchased_at":self.day,"price_eur":100,
            "acquisition_extras_eur":5})
        self.assertEqual(status,200)
        self.assertEqual(bought["status"],"PURCHASED")
        status,sold=self.query("POST","/api/workspace/sale",{
            "id":id,"sold_at":self.day,"sale_gross_eur":200,
            "selling_extras_eur":20,"proof_reference":"receipt A"})
        self.assertEqual(status,200)
        self.assertEqual(sold["status"],"SOLD")
        self.assertEqual(sold["trade"]["net_profit_eur"],75)
        self.assertEqual(sold["trade"]["evidence_status"],"USER_REPORTED_WITH_REFERENCE")
        status,export=self.query("GET","/api/workspace/export")
        self.assertEqual(status,200)
        self.assertTrue(export["private_local_workspace"])
        self.assertTrue(any(row["id"]==id for row in export["listings"]))
        self.assertTrue(self.db.exists())

    def test_owner_feed_adapter_never_claims_completed_sales(self):
        with patch("workspace_api.fetch_own_detector_feed",return_value=feed()):
            code,out=self.query("POST","/api/workspace/radar/refresh",{})
        self.assertEqual(code,200)
        self.assertFalse(out["stale"])
        self.assertIn("ASKING",out["warning"].upper())
        self.assertTrue(out["commercial_data_rights_not_established"])
        code,radar=self.query("GET","/api/workspace/radar")
        self.assertEqual(code,200)
        self.assertGreaterEqual(len(radar["signals"]),2)
        self.assertTrue(radar["commercial_use_rights_not_verified"])

    def test_photo_lab_analysis_saved_to_pipeline_and_images_not_stored(self):
        png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+y0QcAAAAASUVORK5CYII=")
        req={
            "title":"Synthetic 1px image test","description":"PSA 10 claim",
            "kind":"single","source":"manual","asking_eur":200,
            "images":[{"mime":"image/png","base64":base64.b64encode(png).decode()}],
        }
        code,out=self.query("POST","/api/workspace/analyze",req)
        self.assertEqual(code,201)
        self.assertEqual(out["status"],"REVIEW")
        self.assertIn("listing_truth",out["analysis"])
        self.assertIn("image_analysis",out["analysis"])
        self.assertNotIn("base64",json.dumps(out))
        self.assertEqual(out["analysis"]["assessment"]["decision"],"REVIEW")

    def test_user_selected_local_snapshot_import(self):
        snapshot=json.loads(feed())
        code,result=self.query("POST","/api/workspace/radar/import-local",{
            "snapshot":snapshot})
        self.assertEqual(code,200)
        self.assertIn(result["status"],{"IMPORTED_GUIDE_ONLY","UNCHANGED"})
        self.assertTrue(result["commercial_data_rights_not_established"])
        code,error=self.query("POST","/api/workspace/radar/import-local",{
            "source_url":"https://random.example/evil"})
        self.assertEqual(code,422)

    def test_cross_origin_requests_cannot_write(self):
        code,doc=self.query("POST","/api/workspace/listings",{
            "title":"evil","asking_eur":1,"kind":"single"
        },headers={"Content-Type":"application/json","Origin":"https://evil.example"})
        self.assertEqual(code,403)

    def test_full_browser_workspace_page_and_script(self):
        code,html=self.query("GET","/")
        self.assertEqual(code,200)
        self.assertIn(b"Opportunity Pipeline",html)
        self.assertIn(b"Market Radar",html)
        code,script=self.query("GET","/workspace.js")
        self.assertEqual(code,200)
        self.assertIn(b"/api/workspace/listings",script)
        code,old=self.query("GET","/analyze")
        self.assertEqual(code,200)
        self.assertIn(b"BIGSTEN",old)

    def test_invalid_status_or_unknown_path(self):
        code,body=self.query("GET","/api/workspace/listing?id=evil")
        self.assertEqual(code,422)
        code,body=self.query("POST","/api/workspace/status",{
            "id":"not-an-id","status":"BUY"})
        self.assertEqual(code,422)
        code,body=self.query("GET","/api/workspace/sneaky")
        self.assertEqual(code,404)


if __name__=="__main__":
    unittest.main()
