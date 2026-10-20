"""Listing Truth Engine regression suite — no eBay, cloud model or web calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from listing_truth import evaluate_listing_truth, extract_claims


def observation(slab=None, company=None, grade=None, flags=None, image=0,
                edition=None, edition_confidence=0.0, confidence=.95):
    return {
        "image_index": image,
        "bbox_xyxy": [.1,.1,.8,.9],
        "name":"Charizard", "set":"Base", "number":"4/102",
        "slab_visible":slab, "grade_company":company, "grade_number":grade,
        "photo_confidence":confidence, "flags":flags or [],
        "edition":edition, "edition_confidence":edition_confidence,
    }


def assess(title, observations=None, description=""):
    return evaluate_listing_truth(
        {"title":title, "description":description},
        {"observations":observations if observations is not None else []})


class TestListingTruth(unittest.TestCase):
    def test_psa_10_without_photo_is_unverified_not_false(self):
        out = assess("Charizard PSA 10 vintage")
        self.assertEqual(out["status"], "REVIEW_REQUIRED")
        self.assertEqual(out["findings"][0]["status"], "UNVERIFIED")

    def test_raw_photo_explicitly_contradicts_slab_claim(self):
        out = assess("Charizard PSA 10", [observation(slab=False)])
        self.assertEqual(out["status"], "CONFLICT_DETECTED")
        self.assertEqual(out["findings"][0]["image_indices"], [0])

    def test_no_visible_slab_label_is_not_equivalent_to_raw_photo(self):
        out = assess("Charizard PSA 10", [observation(slab=None)])
        self.assertEqual(out["status"], "REVIEW_REQUIRED")

    def test_different_certification_label_contradicts_title(self):
        out = assess("Charizard PSA 10", [observation(slab=True,company="BGS",grade="9.5")])
        self.assertEqual(out["status"], "CONFLICT_DETECTED")

    def test_matching_slab_label_not_authenticated(self):
        out = assess("Charizard PSA 10", [observation(slab=True, company="PSA",grade="10")])
        self.assertEqual(out["status"], "VISUALLY_CONSISTENT_NOT_AUTHENTICATED")
        self.assertTrue(out["human_approval_required"])
        self.assertIn("NOT independently verified", out["findings"][0]["explanation"])

    def test_ungraded_title_conflicts_with_visible_slab(self):
        out=assess("Charizard ungraded NM", [observation(slab=True, company="PSA",grade="9")])
        self.assertEqual(out["status"], "CONFLICT_DETECTED")

    def test_speculative_psa_language_not_treated_as_slab(self):
        for title in ("could grade PSA 10", "potential PSA 10", "not PSA 10",
                      "worth PSA 10 money", "similar to PSA 10"):
            with self.subTest(title=title):
                out=assess(title,[observation(slab=False)])
                self.assertNotEqual(out["status"], "CONFLICT_DETECTED")
                self.assertEqual(out["findings"][0]["status"], "QUALIFIED_CLAIM")

    def test_sealed_photo_risk_is_flag_not_verified_counterfeit(self):
        out=assess("Factory sealed booster box",
                   [observation(flags=["possible_reseal"])])
        self.assertEqual(out["status"], "HIGH_RISK_REVIEW")
        self.assertEqual(out["findings"][0]["status"], "RISK_FLAG")
        self.assertIn("NOT proof",out["findings"][0]["explanation"])

    def test_sealed_no_risk_still_requires_proof(self):
        out=assess("Factory sealed Elite Trainer Box")
        self.assertEqual(out["findings"][0]["status"],"UNVERIFIED")

    def test_first_edition_printing_is_not_assumed_from_number(self):
        out=assess("Base set 1st edition Charizard", [observation()])
        self.assertEqual(out["findings"][0]["type"],"first_edition")
        self.assertEqual(out["findings"][0]["status"],"UNVERIFIED")

    def test_explicit_conflicting_edition_signals(self):
        out=assess("Base 1st edition Charizard",
                   [observation(edition="unlimited",edition_confidence=.98)])
        self.assertEqual(out["status"],"CONFLICT_DETECTED")
        out2=assess("Shadowless Base Charizard",
                    [observation(edition="shadowless",edition_confidence=.91)])
        self.assertEqual(out2["status"],"VISUALLY_CONSISTENT_NOT_AUTHENTICATED")

    def test_very_low_confidence_photo_cannot_contradict(self):
        out=assess("Charizard PSA 10", [observation(slab=False,confidence=.19)])
        self.assertEqual(out["status"], "REVIEW_REQUIRED")

    def test_no_claims_no_fake_assertions(self):
        out=assess("Pokemon binder with cards")
        self.assertEqual(out["status"],"NO_CHECKABLE_CLAIMS")
        self.assertEqual(out["findings"],[])

    def test_untrusted_description_is_bounded(self):
        data={"title":"Pikachu","description":"buy now " * 1000000}
        claims=extract_claims(data)
        self.assertEqual(claims,[])
        with self.assertRaises(ValueError):
            extract_claims({"title":1, "description":"hi"})

    def test_seller_text_cannot_prove_grading_on_its_own(self):
        out=assess("Charizard PSA 10 factory sealed")
        self.assertEqual(out["counts"]["UNVERIFIED"],2)
        self.assertTrue(out["seller_text_is_untrusted"])


if __name__=="__main__":
    unittest.main()
