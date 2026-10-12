"""Evidence ingestion & fast-exit guardrails; 100% synthetic fixtures and offline."""
import csv
import datetime as dt
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sales_evidence import REQUIRED, import_sales, evaluate_with_sales
from reasoning import evaluate_deal

DAY = dt.date(2026, 10, 12)
KEY = "tcgdex:sv03.5-199-holo-en-raw"


def record(i=1, **kw):
    base = dict(
        source="Private Transaction Export",
        transaction_id=f"test-sale-{i}",
        source_url=f"https://example.com/transaction/{i}",
        sold_at="2026-10-10",
        price_eur=str(110 + i),
        currency="EUR", identity_key=KEY, language="en",
        condition="NM", sale_status="completed",
        proof_type="platform_transaction_export",
        proof_reference=f"offline-test-record-{i}",
        reviewer="fixture-reviewer", reviewed_at="2026-10-11",
        identity_verified="yes", condition_verified="yes",
        price_verified="yes", settlement_verified="yes",
        match_confidence=".98",
    )
    base.update(kw)
    return base


def write_csv(folder, rows, headers=REQUIRED):
    path = Path(folder) / "sales.csv"
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


def example_listing(kind="single", cost_verified=True, inventory_verified=False):
    item = {
        "identity_key": KEY, "language": "en", "condition": "NM", "quantity": 1,
        "evidence": {
            "identity_confidence": .95, "condition_confidence": .95,
            "photo_confidence": .95, "authenticity_confidence": .95,
        },
        "sold_comps": [dict(identity_key=KEY, language="en", condition="NM",
                            sold=True, verified=True, price_eur=100000,
                            source_url="https://example.com/FAKE/999",
                            sold_at="2026-10-10", match_confidence=1.0)],
    }
    return {
        "kind": kind, "currency": "EUR", "asking_eur": 45,
        "acquisition": {"shipping_eur": 5, "taxes_eur": 2},
        "sale": {"marketplace_fee_pct": 12, "outbound_shipping_eur": 4,
                 "packaging_eur": 1},
        "costs_verified": cost_verified, "inventory_verified": inventory_verified,
        "items": [item],
    }


class TestSalesEvidence(unittest.TestCase):
    def _import(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(tmp, rows)
            return import_sales(path, asof=DAY)

    def test_three_attested_sales_are_accepted_but_not_platform_proven(self):
        imported = self._import([record(i) for i in range(1, 4)])
        self.assertEqual(imported["accepted"], 3)
        self.assertEqual(imported["quarantined"], 0)
        self.assertIn("ATTESTED", imported["status"])
        self.assertTrue(all(c["verified"] and c["verification_method"] == "human_attestation"
                            for c in imported["records"]))

    def test_active_asking_prices_screenshots_and_unconfirmed_settlement_quarantined(self):
        cases = [
            record(1, sale_status="active"),
            record(2, proof_type="listing_screenshot"),
            record(3, settlement_verified="no"),
            record(4, price_verified="no"),
            record(5, identity_verified="no"),
            record(6, condition_verified="no"),
        ]
        imported = self._import(cases)
        self.assertEqual(imported["accepted"], 0)
        self.assertEqual(imported["quarantined"], 6)
        self.assertEqual([x["row"] for x in imported["quarantine"]], list(range(2, 8)))

    def test_future_stale_and_bad_review_dates_rejected(self):
        cases = [
            record(1, sold_at="2026-10-13"),
            record(2, sold_at="2025-09-30"),
            record(3, reviewed_at="2026-10-13"),
            record(4, reviewed_at="2026-10-09"),
            record(5, sold_at="2026-02-30"),
        ]
        imported = self._import(cases)
        self.assertEqual(imported["quarantined"], 5)

    def test_same_transaction_or_source_url_is_not_double_counted(self):
        imported = self._import([
            record(1), record(1, price_eur="999"),
            record(3, source_url="https://example.com/transaction/1"),
        ])
        self.assertEqual(imported["accepted"], 1)
        self.assertEqual(imported["quarantined"], 2)

    def test_wrong_currency_identity_or_condition_rejected(self):
        imported = self._import([
            record(1, currency="GBP"),
            record(2, identity_key="bad"),
            record(3, language="unknown"),
            record(4, condition="unknown"),
            record(5, match_confidence=".75"),
            record(6, price_eur="-100"),
            record(7, source_url="http://example.com/a"),
        ])
        self.assertEqual(imported["accepted"], 0)
        self.assertEqual(imported["quarantined"], 7)

    def test_valid_condition_grading_format(self):
        c = record(condition="PSA_10")
        imported = self._import([c])
        self.assertEqual(imported["accepted"], 1)
        self.assertEqual(imported["records"][0]["condition"], "PSA_10")

    def test_rejects_malformed_or_unbounded_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text("source\nmanual\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                import_sales(path, asof=DAY)
            path = Path(tmp) / "sales.csv"
            path.write_text("x" * 3_000_001)
            with self.assertRaises(ValueError):
                import_sales(path, asof=DAY)

    def test_joins_only_exact_comps_and_clears_untrusted_costs_and_prior_comps(self):
        imported = self._import([record(i) for i in range(1, 6)] + [
            record(9, identity_key="tcgdex:DIFFERENT-999"),
            record(10, language="fr"),
            record(11, condition="LP"),
        ])
        listing = example_listing(cost_verified=True)
        out = evaluate_with_sales(listing, imported, asof=DAY)
        self.assertEqual(out["decision"], "REVIEW")
        self.assertEqual(out["items"][0]["sold_comps_count"], 5)
        self.assertEqual(out["items"][0]["observed_sold_comps_last_14d"], 5)
        self.assertGreater(out["net_profit_eur"], 0)
        self.assertLess(out["net_profit_eur"], 1000)
        self.assertEqual(out["sale_evidence_import"]["verified_source"], "human_attestation_only")
        self.assertEqual(listing["items"][0]["sold_comps"][0]["price_eur"], 100000)

    def test_missing_comps_never_creates_profit_or_score(self):
        imported = self._import([record(1), record(2)])
        out = evaluate_with_sales(example_listing(), imported, asof=DAY)
        self.assertEqual(out["decision"], "REVIEW")
        self.assertIsNone(out["roi"])
        self.assertIsNone(out["score"])

    def test_weak_14_day_sale_sample_rejects_fast_buy_even_with_cost_review(self):
        data = example_listing()
        data["items"][0]["sold_comps"] = [
            dict(identity_key=KEY, language="en", condition="NM", sold=True,
                 verified=True, price_eur=125+i,
                 source_url=f"https://example.com/{i}", sold_at="2026-09-10",
                 match_confidence=.99, verification_method="human_attestation",
                 reviewer="fixture-reviewer", proof_reference=f"offline-receipt-{i}",
                 reviewed_at="2026-10-11")
            for i in range(5)
        ]
        out = evaluate_deal(data, asof=DAY)
        self.assertEqual(out["decision"], "REVIEW")
        self.assertTrue(any("14 zile" in note for note in out["warnings"]))
        self.assertEqual(out["items"][0]["observed_sold_comps_last_14d"], 0)
        self.assertIsNotNone(out["roi"])

    def test_binder_requires_physical_inventory_even_when_all_other_data_strong(self):
        data = example_listing(kind="binder", inventory_verified=False)
        data["items"][0]["sold_comps"] = [
            dict(identity_key=KEY, language="en", condition="NM", sold=True,
                 verified=True, price_eur=125+i,
                 source_url=f"https://example.com/receipt/{i}",
                 sold_at="2026-10-10", match_confidence=.99,
                 verification_method="human_attestation", reviewer="fixture-reviewer",
                 proof_reference=f"offline-receipt-{i}", reviewed_at="2026-10-11")
            for i in range(5)
        ]
        out = evaluate_deal(data, asof=DAY)
        self.assertEqual(out["decision"], "REVIEW")
        self.assertTrue(any("Inventarul fizic" in note for note in out["warnings"]))
        data["inventory_verified"] = True
        approved_candidate = evaluate_deal(data, asof=DAY)
        self.assertEqual(approved_candidate["decision"], "BUY_CANDIDATE")
        self.assertTrue(approved_candidate["manual_approval_required"])


if __name__ == "__main__":
    unittest.main()
