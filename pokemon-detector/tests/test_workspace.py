"""End-to-end single-user local opportunity workflow (never a public SaaS test)."""
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workspace import WorkspaceStore, WorkspaceError, scenario


def lead(**overrides):
    payload={"title":"Synthetic Charizard seller claim PSA 10",
             "description":"no independent certificate", "kind":"single",
             "source":"manual","asking_eur":100, "source_url":"",
             "note":"Check photo carefully"}
    payload.update(overrides)
    return payload


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"private"/"workbench.sqlite"
        self.workspace=WorkspaceStore(self.path)
        self.today=dt.datetime.now(dt.timezone.utc).date().isoformat()

    def test_database_created_private_and_reopens(self):
        self.assertTrue(self.path.is_file())
        self.assertEqual(self.workspace.dashboard()["listings_total"],0)
        created=self.workspace.create_listing(lead())
        again=WorkspaceStore(self.path)
        self.assertEqual(again.get_listing(created["id"])["title"],lead()["title"])
        self.assertEqual(again.dashboard()["listings_total"],1)

    def test_manual_lead_persistent_event_statuses(self):
        item=self.workspace.create_listing(lead())
        self.assertEqual(item["status"],"INBOX")
        self.assertEqual(item["events"][0]["action"],"CREATED")
        item=self.workspace.set_status(item["id"],"REVIEW")
        self.assertEqual(item["status"],"REVIEW")
        item=self.workspace.set_status(item["id"],"WATCHLIST")
        self.assertEqual(item["status"],"WATCHLIST")
        self.assertEqual(item["events"][0]["action"],"STATUS_CHANGED")
        with self.assertRaisesRegex(WorkspaceError,"not allowed"):
            self.workspace.set_status(item["id"],"SOLD")
        summary=self.workspace.dashboard()
        self.assertEqual(summary["counts"]["WATCHLIST"],1)
        self.assertEqual(summary["positions_open"],0)

    def test_scenario_hypothetical_never_real_sale_evidence(self):
        item=self.workspace.create_listing(lead())
        assumptions={
            "target_resale_eur":200,"inbound_shipping_eur":5,
            "purchase_taxes_eur":0,"customs_eur":0,"buyer_fees_eur":0,
            "selling_fee_pct":10,"outbound_shipping_eur":5,
            "packaging_eur":2,"other_selling_eur":0}
        result=self.workspace.save_scenario(item["id"],assumptions)
        calculation=result["scenario"]["result"]
        self.assertEqual(calculation["status"],"HYPOTHETICAL_ONLY")
        self.assertEqual(calculation["net_profit_eur"],68)
        self.assertAlmostEqual(calculation["roi"],.6476,places=4)
        self.assertEqual(calculation["max_item_bid_for_25pct_roi_eur"],133.4)
        self.assertTrue(calculation["assumptions_not_verified"])
        self.assertEqual(result["status"],"INBOX")

    def test_missing_fees_are_unknown_not_silently_zero(self):
        item=self.workspace.create_listing(lead())
        with self.assertRaisesRegex(WorkspaceError,"Specify all costs"):
            self.workspace.save_scenario(item["id"],{
                "target_resale_eur":200,"selling_fee_pct":10})
        no_model=scenario({"asking_eur":100})
        self.assertIsNone(no_model["roi"])
        self.assertEqual(no_model["status"],"UNKNOWN_NO_USER_TARGET")
        incomplete=scenario({"asking_eur":100,"target_resale_eur":200})
        self.assertEqual(incomplete["status"],"UNKNOWN_FEE_UNSPECIFIED")

    def test_track_actual_purchase_sale_and_net_results(self):
        item=self.workspace.create_listing(lead())
        id=item["id"]
        with self.assertRaisesRegex(WorkspaceError,"WATCHLIST"):
            self.workspace.purchase(id,{
                "purchased_at":self.today,"price_eur":100,"acquisition_extras_eur":5})
        self.workspace.set_status(id,"WATCHLIST")
        bought=self.workspace.purchase(id,{
            "purchased_at":self.today,"price_eur":100,"acquisition_extras_eur":5})
        self.assertEqual(bought["status"],"PURCHASED")
        self.assertEqual(bought["trade"]["total_acquisition_eur"],105)
        self.assertIsNone(bought["trade"]["net_profit_eur"])
        with self.assertRaisesRegex(WorkspaceError,"not allowed"):
            self.workspace.set_status(id,"SOLD")
        sold=self.workspace.sale(id,{
            "sold_at":self.today,"sale_gross_eur":200,
            "selling_extras_eur":20,"proof_reference":"private receipt 001"})
        self.assertEqual(sold["status"],"SOLD")
        self.assertEqual(sold["trade"]["net_profit_eur"],75)
        self.assertAlmostEqual(sold["trade"]["realized_roi"],.7143,places=4)
        self.assertEqual(sold["trade"]["holding_days"],0)
        self.assertEqual(sold["trade"]["evidence_status"],"USER_REPORTED_WITH_REFERENCE")
        self.assertTrue(sold["trade"]["within_14_days"])
        dashboard=self.workspace.dashboard()
        self.assertEqual(dashboard["self_reported_sales"],1)
        self.assertEqual(dashboard["self_reported_realized_profit_eur"],75)
        self.assertTrue(dashboard["all_results_user_reported"])
        self.assertEqual(dashboard["position_cost_eur"],0)

    def test_impossible_and_future_trades_rejected(self):
        id=self.workspace.create_listing(lead())["id"]
        self.workspace.set_status(id,"WATCHLIST")
        future=(dt.datetime.now(dt.timezone.utc).date()+dt.timedelta(days=2)).isoformat()
        with self.assertRaisesRegex(WorkspaceError,"future"):
            self.workspace.purchase(id,{
                "purchased_at":future,"price_eur":100,"acquisition_extras_eur":0})
        with self.assertRaisesRegex(WorkspaceError,"extras"):
            self.workspace.purchase(id,{
                "purchased_at":self.today,"price_eur":100})
        self.assertEqual(self.workspace.get_listing(id)["status"],"WATCHLIST")

    def test_duplicated_listing_source_and_link_guard(self):
        data=lead(source="ebay",external_id="123",
                  source_url="https://www.ebay.com/itm/123")
        self.workspace.create_listing(data)
        with self.assertRaisesRegex(WorkspaceError,"already tracked"):
            self.workspace.create_listing(data)
        for u in ["http://example.com/item","file:///etc/passwd",
                  "https://a.test/item","https://name:secret@example.com/x"]:
            with self.subTest(url=u),self.assertRaises(WorkspaceError):
                self.workspace.create_listing(lead(source_url=u))

    def test_reject_price_injection_nan_and_invalid_states(self):
        for price in [float("nan"),float("inf"),-10,0,True,10000000]:
            with self.subTest(price=price),self.assertRaises(WorkspaceError):
                self.workspace.create_listing(lead(asking_eur=price))
        id=self.workspace.create_listing(lead())["id"]
        with self.assertRaises(WorkspaceError):
            self.workspace.set_status(id,"BUY_APPROVED")
        with self.assertRaises(WorkspaceError):
            self.workspace.get_listing("not-a-uuid")

    def test_no_photo_bytes_in_persisted_analysis(self):
        data={"status":"REVIEW","listing_truth":{"status":"REVIEW_REQUIRED"}}
        item=self.workspace.create_listing(lead(),analysis=data)
        self.assertEqual(item["analysis"]["status"],"REVIEW")
        self.assertEqual(item["status"],"REVIEW")
        with self.assertRaisesRegex(WorkspaceError,"Raw image"):
            self.workspace.create_listing(lead(title="Different"),analysis={"base64":"evil"})

    def test_radars_are_not_real_listings_and_deduplicated(self):
        row={"card_key":"1","card_name":"Demo",
             "card_set":"set","card_number":"1/2","variant":"holo",
             "lowest_ask_eur":30,"guide_reference_eur":50,"guide_discount_pct":40}
        stats=self.workspace.store_signals("OWN_FEED","hash123","2026-10-12T09:00Z",[row])
        self.assertEqual(stats["accepted"],1)
        twice=self.workspace.store_signals("OWN_FEED","hash123","2026-10-12T09:00Z",[row])
        self.assertEqual(twice["status"],"UNCHANGED")
        self.assertEqual(self.workspace.dashboard()["listings_total"],0)
        self.assertEqual(self.workspace.dashboard()["signals_total"],1)
        self.assertEqual(len(self.workspace.radar()),1)

    def test_export_only_local_data_and_auditable_events(self):
        item=self.workspace.create_listing(lead())
        exported=self.workspace.export()
        self.assertTrue(exported["private_local_workspace"])
        self.assertEqual(exported["listings"][0]["id"],item["id"])
        self.assertEqual(exported["listings"][0]["events"][0]["action"],"CREATED")


if __name__=="__main__":
    unittest.main()
