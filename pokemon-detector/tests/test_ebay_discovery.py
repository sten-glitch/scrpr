"""Offline fixtures for eBay -> Pokémon photo-analysis discovery."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ebay_discovery as d

FX = {"EUR": 1.0, "USD": 1.2, "GBP": 0.85, "RON": 5.0}
IMG = "https://i.ebayimg.com/images/g/test/s-l1600.jpg"


def item(**changes):
    base = {
        "itemId": "v1|123|0", "title": "Pokemon Binder Lot",
        "itemWebUrl": "https://www.ebay.co.uk/itm/123",
        "price": {"value": "85", "currency": "GBP"},
        "image": {"imageUrl": IMG},
        "itemLocation": {"country": "GB"},
        "seller": {"username": "seller_name"},
        "shippingOptions": [{"shippingCost": {"value": "5", "currency": "GBP"}}],
    }
    base.update(changes)
    return base


class TestDiscovery(unittest.TestCase):
    def test_normalized_listing_and_original_provenance(self):
        o = d.listing_from_ebay(item(), "EBAY_GB", "binder", FX)
        self.assertEqual(o["listing_id"], "ebay:EBAY_GB:v1|123|0")
        self.assertEqual(o["kind_hint"], "binder")
        self.assertEqual(o["asking_eur"], 100)
        self.assertEqual(o["acquisition"]["shipping_eur"], 5.88)
        self.assertEqual(o["image_urls"], [IMG])
        self.assertFalse(o["costs_verified"])
        self.assertEqual(o["location_country"], "GB")

    def test_unknown_shipping_is_not_zero(self):
        o = d.listing_from_ebay(item(shippingOptions=[]), "EBAY_GB", "lot", FX)
        self.assertEqual(o["acquisition"], {})
        self.assertFalse(o["shipping_verified"])

    def test_no_image_or_bad_price_skipped(self):
        self.assertIsNone(d.listing_from_ebay(item(image={"imageUrl":"http://localhost/img"}), "EBAY_GB", "lot", FX))
        self.assertIsNone(d.listing_from_ebay(item(price={"value": "-1", "currency": "GBP"}), "EBAY_GB", "lot", FX))
        self.assertIsNone(d.listing_from_ebay(item(price={"value": "100", "currency": "XXX"}), "EBAY_GB", "lot", FX))

    def test_deduped_images_and_limit(self):
        self.assertEqual(d._images({"image":{"imageUrl":IMG},
                      "additionalImages":[{"imageUrl":IMG}]*11}), [IMG])

    def test_broad_market_scan_without_vision_calls(self):
        with patch.dict(os.environ, {"EBAY_CLIENT_ID":"fake", "EBAY_CLIENT_SECRET":"fake"}):
            with patch.object(d, "get", return_value=b'<Cube><Cube currency="GBP" rate="0.85"/></Cube>'), \
                 patch.object(d, "ebay_token", return_value="token"), \
                 patch.object(d, "get_json", return_value={"itemSummaries":[item(), item()]}):
                result = d.discover({"binder":["pokemon binder"]}, ["EBAY_GB"])
        self.assertEqual(result["offers_found"], 1)
        self.assertEqual(result["queries_executed"], 1)
        self.assertEqual(result["offers"][0]["kind_hint"], "binder")
        self.assertEqual(result["offers"][0]["image_urls"], [IMG])

    def test_missing_credentials_abort_before_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                d.discover({"single":["pokemon card"]}, ["EBAY_DE"])

    def test_invalid_markets_or_limits(self):
        for markets, count in [(["EBAY_NOT_REAL"], 10), (["EBAY_US"], 301)]:
            with self.assertRaises(ValueError):
                d.discover({"single":["pikachu"]}, markets, max_offers=count)

    def test_details_fetch_multiple_photos_when_opted_in(self):
        second = "https://i.ebayimg.com/images/g/second/s-l1600.jpg"
        calls = []
        def fake_get_json(url, **kw):
            calls.append(url)
            if "/item_summary/search?" in url:
                return {"itemSummaries":[item()]}
            return {"additionalImages":[{"imageUrl": second}], "description":"binder with many cards"}
        with patch.dict(os.environ, {"EBAY_CLIENT_ID":"x", "EBAY_CLIENT_SECRET":"y"}):
            with patch.object(d, "get", return_value=b'<Cube><Cube currency="GBP" rate="0.85"/></Cube>'), \
                 patch.object(d, "ebay_token", return_value="tok"), \
                 patch.object(d, "get_json", side_effect=fake_get_json):
                result = d.discover({"binder":["pokemon binder"]}, ["EBAY_GB"], with_details=True)
        self.assertIn(second, result["offers"][0]["image_urls"])
        self.assertEqual(result["offers"][0]["description"], "binder with many cards")
        self.assertTrue(any("/item/v1%7C123%7C0" in u for u in calls))


if __name__ == "__main__":
    unittest.main()
