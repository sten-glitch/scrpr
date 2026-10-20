"""Synthetic offline checks for purchase/exits; not a claim of investment performance."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flip_outcomes import audit_outcomes, BacktestError

DAY = dt.date(2026, 10, 12)

def record(i, *, state="closed", roi=.3, decision="BUY_CANDIDATE"):
    b = {"deal_id":f"fictional-{i}", "forecast_at":"2026-09-28",
         "decision":decision, "forecast_roi":.35}
    if state == "unbought":
        return b
    b.update(bought_at="2026-09-29", purchase_cost_eur=100,
             purchase_reviewed=True, purchase_proof_reference=f"synthetic-buy-{i}")
    if state == "closed":
        b.update(closed_at="2026-10-07", net_sale_eur=100*(1+roi),
                 sale_reviewed=True, sale_proof_reference=f"synthetic-sell-{i}")
    return b


class TestOutcomes(unittest.TestCase):
    def test_closed_roi_and_forecast_calibration(self):
        r = audit_outcomes([record(1), record(2, roi=-.1), record(3, state="unbought")], asof=DAY)
        self.assertEqual(r["forecast_count"], 3)
        self.assertEqual(r["purchases_executed"], 2)
        self.assertEqual(r["closed_trades"], 2)
        self.assertEqual(r["closed_within_horizon"], 2)
        self.assertEqual(r["observed_exit_within_horizon_of_all_purchases"], 1)
        self.assertEqual(r["realized_roi_mean_on_closed_only"], .1)
        self.assertEqual(r["target_roi_hit_rate_on_closed"], .5)
        self.assertEqual(r["buy_candidate_target_precision_on_executed_closed"], .5)
        self.assertEqual(r["forecast_roi_mean_error_realized_minus_predicted"], -.25)
        self.assertEqual(r["forecast_roi_mae_on_closed"], .25)
        self.assertEqual(r["records"][2]["state"], "not_purchased")

    def test_open_exposure_not_misreported_as_profit(self):
        r = audit_outcomes([record(1), record(2, state="open")], asof=DAY, horizon_days=10)
        self.assertEqual(r["purchases_executed"], 2)
        self.assertEqual(r["closed_trades"], 1)
        self.assertEqual(r["open_overdue"], 1)
        self.assertEqual(r["observed_exit_within_horizon_of_all_purchases"], .5)
        self.assertEqual(r["realized_roi_mean_on_closed_only"], .3)
        self.assertIsNone(r["records"][1]["realized_roi"])

    def test_refuses_fake_sold_prices_without_reviews(self):
        unverified = record(1)
        unverified["sale_reviewed"] = False
        with self.assertRaises(BacktestError):
            audit_outcomes([unverified], asof=DAY)
        no_receipt = record(2)
        no_receipt["purchase_proof_reference"] = ""
        with self.assertRaises(BacktestError):
            audit_outcomes([no_receipt], asof=DAY)

    def test_no_future_lookahead(self):
        cases = [
            {**record(1), "forecast_at":"2026-10-13"},
            {**record(2), "bought_at":"2026-09-01"},
            {**record(3), "closed_at":"2026-10-13"},
            {**record(4), "closed_at":"2026-09-01"},
        ]
        for case in cases:
            with self.subTest(deal_id=case["deal_id"]), self.assertRaises(BacktestError):
                audit_outcomes([case], asof=DAY)

    def test_no_realized_sale_for_open_inventory(self):
        x = record(1, state="open")
        x["net_sale_eur"] = 200
        with self.assertRaises(BacktestError):
            audit_outcomes([x], asof=DAY)
        x = record(2, state="unbought")
        x["closed_at"] = "2026-10-01"
        with self.assertRaises(BacktestError):
            audit_outcomes([x], asof=DAY)

    def test_duplicate_and_invalid_evidence_rejected(self):
        with self.assertRaises(BacktestError):
            audit_outcomes([record(1), record(1)], asof=DAY)
        with self.assertRaises(BacktestError):
            audit_outcomes([], asof=DAY)
        with self.assertRaises(BacktestError):
            audit_outcomes([record(1)], asof=DAY, horizon_days=0)
        with self.assertRaises(BacktestError):
            audit_outcomes([{**record(1), "net_sale_eur":float("inf")}], asof=DAY)


if __name__ == "__main__":
    unittest.main()
