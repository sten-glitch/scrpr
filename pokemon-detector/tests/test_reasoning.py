"""Offline, deterministic guards for BIGSTEN Pokémon deal decisions."""
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reasoning import evaluate_deal

DAY = dt.date(2026, 10, 12)

def card(price=100, confidence=0.95, sold=5):
    return {"identity_key": "sv03.5-199-en-holo-raw-nm", "language": "en", "condition": "NM", "quantity": 1,
            "evidence": {"identity_confidence": confidence, "condition_confidence": confidence,
                         "photo_confidence": confidence, "authenticity_confidence": confidence},
            "sold_comps": [{"identity_key": "sv03.5-199-en-holo-raw-nm", "language": "en", "condition": "NM",
                            "price_eur": price + i, "sold": True, "verified": True,
                            "source_url": f"https://example.org/sold/{i}", "sold_at": "2026-10-10", "match_confidence": 0.97,
                            "verification_method": "human_attestation", "reviewer": "fixture-reviewer",
                            "proof_reference": f"synthetic-proof-{i}", "reviewed_at": "2026-10-11"}
                           for i in range(sold)]}

def listing(items=None, kind="single", asking=45):
    return {"kind": kind, "asking_eur": asking, "currency": "EUR", "costs_verified": True, "items": items if items is not None else [card()],
            "acquisition": {"shipping_eur": 5, "taxes_eur": 2},
            "sale": {"marketplace_fee_pct": 12, "outbound_shipping_eur": 4, "packaging_eur": 1}}

class TestReasoning(unittest.TestCase):
    def test_strong_candidate_and_exact_financial_waterfall(self):
        r = evaluate_deal(listing(), asof=DAY)
        self.assertEqual(r["decision"], "BUY_CANDIDATE")
        self.assertEqual(r["acquisition_total_eur"], 52)
        self.assertEqual(r["conservative_gross_resale_eur"], 101)
        self.assertEqual(r["net_sale_proceeds_eur"], 83.88)
        self.assertEqual(r["net_profit_eur"], 31.88)
        self.assertEqual(r["roi"], 0.6131)
        self.assertTrue(r["manual_approval_required"])

    def test_unverified_or_unmatched_sales_never_count(self):
        i = card(sold=2)
        i["sold_comps"].append({"identity_key": i["identity_key"], "language": "jp", "condition": "NM",
                                "price_eur": 999, "sold": True, "verified": True,
                                "source_url": "https://example.org/999", "sold_at": "2026-10-10", "match_confidence": 1})
        r = evaluate_deal(listing([i]), asof=DAY)
        self.assertEqual(r["decision"], "REVIEW")
        self.assertIsNone(r["roi"])
        self.assertIsNone(r["score"])

    def test_low_photo_confidence_blocks_buy(self):
        r = evaluate_deal(listing([card(confidence=0.5)]), asof=DAY)
        self.assertEqual(r["decision"], "REVIEW")
        self.assertLessEqual(r["score"], 59)

    def test_counterfeit_or_reseal_blocks(self):
        fake = card()
        fake["evidence"]["counterfeit_risk"] = True
        self.assertEqual(evaluate_deal(listing([fake]), asof=DAY)["decision"], "REJECT")
        sealed = card()
        sealed["evidence"]["resealed_risk"] = True
        self.assertEqual(evaluate_deal(listing([sealed], kind="sealed"), asof=DAY)["decision"], "REJECT")

    def test_lot_unknown_inventory_no_buy(self):
        missing = card(sold=0)
        r = evaluate_deal(listing([card(), missing], kind="binder"), asof=DAY)
        self.assertEqual(r["decision"], "REVIEW")
        self.assertIsNone(r["roi"])
        self.assertEqual(r["priced_quantity_coverage"], 0.5)

    def test_stale_and_duplicate_comps_filtered(self):
        i = card(sold=3)
        i["sold_comps"][1]["source_url"] = i["sold_comps"][0]["source_url"]
        i["sold_comps"][2]["sold_at"] = "2025-08-01"
        r = evaluate_deal(listing([i]), asof=DAY)
        self.assertEqual(r["items"][0]["sold_comps_count"], 1)
        self.assertEqual(r["decision"], "REVIEW")

    def test_unverified_costs_cannot_trigger_buy(self):
        data = listing()
        data.pop("costs_verified")
        r = evaluate_deal(data, asof=DAY)
        self.assertEqual(r["decision"], "REVIEW")
        self.assertLessEqual(r["score"], 59)

    def test_invalid_money_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_deal(listing(asking=-1), asof=DAY)

if __name__ == "__main__":
    unittest.main()
