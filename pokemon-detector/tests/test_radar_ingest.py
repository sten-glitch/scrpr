"""Offline tests: owned radar import stays guide-only and auditable."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar_ingest import import_feed, parse_detector_feed, fetch_own_detector_feed
from workspace import WorkspaceStore, WorkspaceError

COLS=["k","id","kind","n","s","no","v","low","a30","tr"]


def feed(rows=None, *, timestamp=None):
    when=timestamp or dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    data={"generatedAt":when,"cols":COLS,"rows":rows if rows is not None else [
        ["demo_A",1,"single","Charizard ex","151","199/165","holo",20,50,43],
        ["demo_B",2,"single","Pikachu","Base","10/100","normal",60,65,62],
        ["demo_C",3,"sealed","Booster Box","151","NA","normal",20,100,80],
        ["demo_D",4,"single","Mew ex","151","198/165","holo",20,40,37],
        ["demo_E",5,"single","Odd card","X","2/30","holo",2,40,32],
    ]}
    return json.dumps(data,separators=(",",":"),ensure_ascii=False).encode()


class TestOwnedRadar(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=WorkspaceStore(Path(self.temp.name)/"private"/"store.sqlite")

    def test_parse_only_lowest_ask_vs_guide(self):
        result=parse_detector_feed(feed())
        self.assertEqual(result["eligible_signals"],2)
        self.assertEqual(result["signals"][0]["card_key"],"demo_A")
        self.assertEqual(result["signals"][0]["guide_discount_pct"],60)
        self.assertEqual(result["signals"][1]["guide_discount_pct"],50)
        self.assertEqual(result["proof"],"ASKING_VS_GUIDE_NOT_SOLD_COMPS")
        self.assertFalse(result["snapshot_stale"])

    def test_feed_import_never_creates_executable_listing(self):
        result=import_feed(self.store,feed())
        self.assertEqual(result["status"],"IMPORTED_GUIDE_ONLY")
        self.assertEqual(result["accepted"],2)
        self.assertTrue(result["commercial_data_rights_not_established"])
        self.assertEqual(self.store.dashboard()["listings_total"],0)
        self.assertEqual(self.store.dashboard()["signals_total"],2)
        unchanged=import_feed(self.store,feed())
        self.assertEqual(unchanged["status"],"UNCHANGED")
        self.assertEqual(self.store.dashboard()["signals_total"],2)

    def test_stale_feed_marked_not_real_time(self):
        older=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=10)).isoformat(timespec="minutes")
        report=parse_detector_feed(feed(timestamp=older))
        self.assertTrue(report["snapshot_stale"])
        self.assertGreater(report["feed_age_hours"],200)

    def test_invalid_feeds_fail(self):
        for raw in [b"",b"[]",b"{}",b"not json",
                    json.dumps({"generatedAt":"x","cols":COLS,"rows":[]}).encode(),
                    json.dumps({"generatedAt":"2026-10-12","cols":COLS,"rows":[]}).encode()]:
            with self.subTest(raw=raw[:30]),self.assertRaises(WorkspaceError):
                parse_detector_feed(raw)

    def test_future_feed_refused(self):
        future=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=10)).isoformat()
        with self.assertRaisesRegex(WorkspaceError,"future"):
            parse_detector_feed(feed(timestamp=future))

    def test_bad_rows_and_negative_prices_not_imported(self):
        rows=[
            ["id",1,"single","Fake card","X","1/1","normal",True,100,50],
            ["id_2",2,"single","Fake card","X","1/1","normal",100,0,50],
            ["id_3",3,"single","Good","X","1/1","normal",10,100,50],
            ["truncated",4,"single"]
        ]
        result=parse_detector_feed(feed(rows),limit=25)
        self.assertEqual(result["eligible_signals"],1)
        self.assertEqual(result["discarded_malformed_rows"],1)

    def test_network_fetch_is_explicit_and_fixed_pinned_host(self):
        from radar_ingest import OWN_RADAR_URL
        self.assertEqual(OWN_RADAR_URL,"https://sten-glitch.github.io/scrpr/data/latest.json")
        # This test has no live network calls; the HTTP is only attempted
        # when a user explicitly clicks import in the local dashboard.
        with patch("radar_ingest.urllib.request.build_opener") as opener:
            response=opener.return_value.open.return_value.__enter__.return_value
            response.status=200
            response.headers.get.return_value=str(len(feed()))
            response.read.return_value=feed()
            self.assertEqual(fetch_own_detector_feed(),feed())
            opener.return_value.open.assert_called_once()
            request=opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url,OWN_RADAR_URL)


if __name__=="__main__":
    unittest.main()
