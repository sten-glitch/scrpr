"""Offline security, identity, provenance and catalog tests for Visual Intelligence."""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import (VisionError, analyze_listing, normalize_analysis,
                    normalize_observation, resolve_catalog_id, validate_image_url,
                    provisional_listing)

TODAY = dt.date(2026, 10, 12)
URL = "https://i.ebayimg.com/images/g/demo/s-l1600.webp"


def listing(kind="binder", images=2):
    return {"listing_id": "ebay:123", "listing_url": "https://www.ebay.co.uk/itm/123",
            "title": "Pokemon collection lot cheap BUY NOW", "description": "graded PSA 10!",
            "asking_eur": 80, "image_urls": [URL] * images, "kind_hint": kind}


def obs(**overrides):
    d = {"image_index": 0, "bbox_xyxy": [0.1, 0.1, 0.5, 0.6],
         "name": "Charizard ex", "set": "151", "number": "199/165",
         "language": "en", "finish": "holo", "condition": "NM",
         "identity_confidence": .99, "condition_confidence": .99,
         "photo_confidence": .95, "flags": ["back_not_visible"]}
    d.update(overrides)
    return d


def vision(kind="binder", observations=None, **other):
    x = {"kind": kind, "summary": "Cards visible", "inventory_complete": True,
         "observations": [obs()] if observations is None else observations, "uncertainties": []}
    x.update(other)
    return x


CAT = [{"identity_key": "tcgdex:sv03.5-199-en-holo-raw", "set": "151",
        "number": "199/165", "language": "en", "finish": "holo"},
       {"identity_key": "tcgdex:sv03.5-199-en-reverse-raw", "set": "151",
        "number": "199/165", "language": "en", "finish": "reverse"}]


class TestVisualIntelligence(unittest.TestCase):
    def test_public_https_only(self):
        self.assertEqual(validate_image_url(URL), URL)
        for link in ["http://example.com/a.png", "https://localhost/x",
                     "https://127.0.0.1/a", "https://169.254.169.254/meta",
                     "https://user:pw@images.example.com/a",
                     "https://box.internal/a", "file:///etc/passwd",
                     "https://[::1]/a", "https://example.com:444/a"]:
            with self.subTest(link=link), self.assertRaises(VisionError):
                validate_image_url(link)

    def test_missing_and_excess_images_rejected(self):
        for imgs in ([], [URL] * 9):
            x = listing()
            x["image_urls"] = imgs
            with self.assertRaises(VisionError):
                analyze_listing(x, CAT, observation=vision(), asof=TODAY)

    def test_invalid_bbox_and_image_reference_rejected(self):
        for bad in ({"image_index": 2}, {"image_index": -1},
                    {"bbox_xyxy": [0, 0, 2, 1]},
                    {"bbox_xyxy": [0.7, 0.1, 0.2, 0.9]},
                    {"bbox_xyxy": None}):
            with self.subTest(bad=bad), self.assertRaises(VisionError):
                normalize_observation(obs(**bad), 2)

    def test_output_clamped_and_untrusted_fields_discarded(self):
        r = normalize_observation(obs(
            identity_confidence=999, condition_confidence=-1,
            flags=["possible_counterfeit", "execute_shell", "possible_counterfeit"],
            costs_verified=True, sold_comps=[{"price_eur": 10}], identity_key="fake"), 2)
        self.assertEqual(r["identity_confidence"], 1)
        self.assertEqual(r["condition_confidence"], 0)
        self.assertEqual(r["flags"], ["possible_counterfeit"])
        self.assertNotIn("sold_comps", r)
        self.assertNotIn("identity_key", r)
        self.assertNotIn("costs_verified", r)

    def test_model_claims_cannot_certify_complete_inventory(self):
        a = normalize_analysis(vision(inventory_complete=True), 2)
        self.assertFalse(a["inventory_complete"])

    def test_exact_catalog_matching_includes_variant(self):
        n = normalize_observation(obs(), 2)
        key, _ = resolve_catalog_id(n, CAT)
        self.assertEqual(key, "tcgdex:sv03.5-199-en-holo-raw")
        n["finish"] = "reverse"
        key, _ = resolve_catalog_id(n, CAT)
        self.assertEqual(key, "tcgdex:sv03.5-199-en-reverse-raw")
        n["language"] = "jp"
        key, _ = resolve_catalog_id(n, CAT)
        self.assertIsNone(key)

    def test_sealed_catalog_identity_is_not_authentication(self):
        x = normalize_observation(obs(name="151 Booster Bundle", set="151",
                                      number=None, finish="unknown",
                                      language="unknown", condition="sealed"), 2)
        trusted = [{"kind":"sealed", "identity_key":"cardmarket:sealed:555",
                    "name":"151 Booster Bundle", "set":"151"}]
        self.assertEqual(resolve_catalog_id(x, trusted)[0], "cardmarket:sealed:555")
        assessed = analyze_listing(listing(kind="sealed"), trusted,
            observation=vision(kind="sealed", observations=[{
                **obs(name="151 Booster Bundle", set="151", number=None,
                      finish="unknown", language="unknown", condition="sealed"),
                "authenticity_confidence": 1.0, "sold_comps":[{"price_eur":900}],
            }]), asof=TODAY)
        self.assertEqual(assessed["assessment"]["decision"], "REVIEW")
        self.assertEqual(assessed["assessment"]["items"][0]["identity_key"], "cardmarket:sealed:555")
        self.assertIsNone(assessed["assessment"]["roi"])

    def test_missing_variant_or_multiple_matching_rows_is_ambiguous(self):
        n = normalize_observation(obs(finish="unknown"), 2)
        self.assertIsNone(resolve_catalog_id(n, CAT)[0])
        n["finish"] = "holo"
        self.assertIsNone(resolve_catalog_id(n, CAT + [{
            **CAT[0], "identity_key": "another-printing"
        }])[0])

    def test_graded_slab_requires_serial_and_graded_catalog(self):
        n = normalize_observation(obs(grade_company="PSA", grade_number="10"), 2)
        key, warning = resolve_catalog_id(n, CAT)
        self.assertIsNone(key)
        self.assertIn("Graded", warning)

    def test_zero_trust_never_promotes_vision_to_verified_sales(self):
        injected = vision(kind="single", sold_comps=[{"price_eur": 999999, "verified": True}],
                          costs_verified=True)
        result = analyze_listing(listing(kind="single"), CAT, observation=injected, asof=TODAY)
        self.assertEqual(result["status"], "VISION_ONLY_NOT_BUY_READY")
        self.assertEqual(result["assessment"]["decision"], "REVIEW")
        self.assertIsNone(result["assessment"]["score"])
        self.assertIsNone(result["assessment"]["roi"])
        self.assertTrue(result["assessment"]["manual_approval_required"])

    def test_unverified_condition_and_authenticity_not_full_score(self):
        analysis = normalize_analysis(vision(kind="single"), 2)
        candidate, notes = provisional_listing(listing(kind="single"), analysis, CAT)
        self.assertFalse(candidate["costs_verified"])
        self.assertEqual(candidate["items"][0]["evidence"]["authenticity_confidence"], 0)
        self.assertLess(candidate["items"][0]["evidence"]["condition_confidence"], .8)
        self.assertEqual(candidate["items"][0]["sold_comps"], [])

    def test_lot_has_unknown_inventory_placeholder_even_when_model_says_complete(self):
        result = analyze_listing(listing(), CAT, observation=vision(), asof=TODAY)
        self.assertEqual(result["assessment"]["kind"], "binder")
        self.assertEqual(result["assessment"]["priced_quantity_coverage"], 0)
        self.assertEqual(result["assessment"]["decision"], "REVIEW")
        self.assertEqual(len(result["assessment"]["items"]), 2)
        self.assertTrue(any("inventory" in note.lower() for note in result["open_questions"]))

    def test_suspected_counterfeit_and_reseal_force_reject(self):
        r = analyze_listing(listing(kind="single"), CAT,
                            observation=vision(kind="single",
                                observations=[obs(flags=["possible_counterfeit"])]), asof=TODAY)
        self.assertEqual(r["assessment"]["decision"], "REJECT")
        s = analyze_listing(listing(kind="sealed"), [],
                            observation=vision(kind="sealed",
                                observations=[obs(flags=["possible_reseal"], condition="sealed")]), asof=TODAY)
        self.assertEqual(s["assessment"]["decision"], "REJECT")

    def test_duplicate_cards_across_images_are_not_priced_twice(self):
        # The model must reconcile duplicate photos. Until then no buying, no price comps.
        r = analyze_listing(listing(), CAT, observation=vision(observations=[obs(), obs(image_index=1)]), asof=TODAY)
        self.assertEqual(r["assessment"]["decision"], "REVIEW")
        self.assertIsNone(r["assessment"]["net_profit_eur"])

    def test_multi_item_single_becomes_lot_with_unknown_inventory(self):
        result = analyze_listing(listing(kind="single"), CAT,
              observation=vision(kind="single", observations=[obs(), obs(image_index=1)]), asof=TODAY)
        self.assertEqual(result["assessment"]["kind"], "lot")
        self.assertGreaterEqual(len(result["assessment"]["items"]), 3)

    def test_bad_model_response_fails_closed(self):
        with self.assertRaises(VisionError):
            normalize_analysis({"kind": "lot", "observations": [obs()] * 101}, 1)
        with self.assertRaises(VisionError):
            normalize_analysis({"kind": "lot", "observations": {}}, 1)

    def test_photo_analyzer_does_not_need_cloud_api_for_offline_evidence(self):
        out = analyze_listing(listing(), CAT, observation=vision(), asof=TODAY)
        self.assertEqual(out["catalog_resolutions"][0]["identity_key"], CAT[0]["identity_key"])
        self.assertEqual(out["catalog_resolutions"][0]["image_index"], 0)


if __name__ == "__main__":
    unittest.main()
