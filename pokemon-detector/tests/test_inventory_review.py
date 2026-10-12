"""Cross-photo inventory bounds: no double-counting without human review."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory_review import review_inventory
from vision import analyze_listing, normalize_observation, resolve_catalog_id


def card(image=0, bbox=None, name="Charizard ex", num="199/165"):
    return normalize_observation({
        "image_index": image, "bbox_xyxy": bbox or [.1, .1, .4, .5],
        "name": name, "set": "151", "number": num,
        "finish": "holo", "language": "en", "condition": "NM",
        "identity_confidence": .95, "photo_confidence": .95,
        "condition_confidence": .7,
    }, 2)


class TestInventoryReview(unittest.TestCase):
    def test_same_card_appears_in_two_photos_qty_is_range_not_double(self):
        r = review_inventory([card(0), card(1)], ["id-1", "id-1"])
        self.assertEqual(r["total_model_observations"], 2)
        self.assertEqual(r["quantity_lower_bound_if_detections_correct"], 1)
        self.assertEqual(r["quantity_upper_bound_if_detections_correct"], 2)
        self.assertFalse(r["quantity_verified"])
        self.assertEqual(r["groups_requiring_review"], 1)
        self.assertTrue(r["groups"][0]["cross_photo_quantity_ambiguous"])

    def test_two_same_cards_in_one_photo_are_not_merged(self):
        r = review_inventory([
            card(0, [.1, .1, .3, .4]),
            card(0, [.6, .1, .9, .4]),
        ], ["id", "id"])
        self.assertEqual(r["quantity_lower_bound_if_detections_correct"], 2)
        self.assertEqual(r["quantity_upper_bound_if_detections_correct"], 2)
        self.assertFalse(r["groups"][0]["cross_photo_quantity_ambiguous"])

    def test_duplicate_detector_boxes_flagged_without_auto_buy(self):
        r = review_inventory([card(0), card(0)], ["id", "id"])
        self.assertEqual(r["groups"][0]["same_photo_duplicate_detections"], [1])
        self.assertEqual(r["quantity_upper_bound_if_detections_correct"], 1)
        self.assertTrue(r["groups"][0]["review_required"])

    def test_unidentified_card_across_photos_will_not_be_valued(self):
        unknown = card(0, name=None, num=None)
        unknown2 = card(1, name=None, num=None)
        r = review_inventory([unknown, unknown2], [None, None])
        self.assertEqual(r["quantity_lower_bound_if_detections_correct"], 1)
        self.assertEqual(r["quantity_upper_bound_if_detections_correct"], 2)
        self.assertEqual(r["groups_requiring_review"], 1)
        self.assertFalse(r["groups"][0]["resolved_catalog_identity"])

    def test_name_disagreement_blocks_catalog_identity(self):
        wrong = card(name="Pikachu")
        catalog = [{
            "identity_key": "tcgdex:151-199", "set": "151",
            "number": "199/165", "name": "Charizard ex",
            "language": "en", "finish": "holo",
        }]
        key, reason = resolve_catalog_id(wrong, catalog)
        self.assertIsNone(key)
        self.assertIn("No exact", reason)
        right = card()
        self.assertEqual(resolve_catalog_id(right, catalog)[0], "tcgdex:151-199")

    def test_review_visible_in_listing_output_not_marked_as_actual_count(self):
        src = {
            "listing_id": "manual:1", "asking_eur": 120, "kind_hint": "binder",
            "image_urls": ["https://i.ebayimg.com/images/g/a/test.webp",
                           "https://i.ebayimg.com/images/g/b/test.webp"],
        }
        v = {"kind": "binder", "observations": [card(0), card(1)]}
        result = analyze_listing(src, [], observation=v, asof=dt.date(2026, 10, 12))
        self.assertEqual(result["inventory_review"]["quantity_lower_bound_if_detections_correct"], 1)
        self.assertEqual(result["inventory_review"]["quantity_upper_bound_if_detections_correct"], 2)
        self.assertIsNone(result["assessment"]["roi"])
        self.assertEqual(result["assessment"]["decision"], "REVIEW")
        self.assertTrue(any("duplicated" in note for note in result["open_questions"]))

    def test_empty_analysis_no_confirmed_card_quantity(self):
        r = review_inventory([], [])
        self.assertEqual(r["total_model_observations"], 0)
        self.assertEqual(r["quantity_lower_bound_if_detections_correct"], 0)
        self.assertFalse(r["quantity_verified"])


if __name__ == "__main__":
    unittest.main()
