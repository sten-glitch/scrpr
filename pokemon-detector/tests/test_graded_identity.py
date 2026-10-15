import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from graded_identity import resolve_query, metadata_prefilter
from catalog_candidates import CatalogCandidateIndex
from similar_listings import search_similar

CAT = [{"identity_key": "jp:set:3:holo", "name": "ピカチュウ", "aliases": ["Pikachu"],
        "set_id": "set", "set": "Example set", "number": "003", "language": "ja", "finish": "holo"},
       {"identity_key": "en:other:3:holo", "name": "Pikachu", "set_id": "other", "set": "Other set",
        "number": "3", "language": "en", "finish": "holo"}]


class GradedIdentityTests(unittest.TestCase):
    def test_japanese_catalog_not_stripped(self):
        self.assertEqual(CatalogCandidateIndex(CAT).suggest({"name": "ピカチュウ", "number": "003"})[0]["language"], "ja")

    def test_card_language_not_title_language(self):
        for text in ("Pikachu #003 PSA 10", "ピカチュウ #003 PSA 10"):
            result = resolve_query(text, CAT)
            self.assertNotIn("language", result["fields"])
            self.assertEqual(result["status"], "NEEDS_CLARIFICATION")

    def test_exact_query_requires_set_variant_language(self):
        result = resolve_query({"name": "Pikachu", "set_id": "set", "number": "003", "variant": "holo",
                                "language": "Japanese", "grader": "PSA", "grade": "10"}, CAT)
        self.assertEqual(result["canonical_identity"], "pokemon|ja|set|3|holo|PSA|10")
        self.assertEqual(result["status"], "RESOLVED_QUERY")

    def test_no_guess_from_incomplete_catalog(self):
        result = resolve_query("Pikachu #003 PSA 10 Japanese", CAT[:1])
        self.assertEqual(result["status"], "NEEDS_CLARIFICATION")
        self.assertFalse(result["queries"])

    def test_exclusions_and_speculative_grade(self):
        for text in ("Pokemon PSA 10 empty slab", "Pokemon raw could grade PSA 10", "Pokemon sealed booster PSA 10"):
            self.assertEqual(metadata_prefilter({"title": text})["status"], "EXCLUDED")
        self.assertEqual(metadata_prefilter({"title": "Pokemon could grade PSA 10"})["status"], "REVIEW")

    def test_cert_query_preserves_leading_zero_and_not_a_grade(self):
        r = resolve_query("PSA 00123456", CAT)
        self.assertEqual(r["fields"]["certification_number"], "00123456")
        self.assertNotIn("grade", r["fields"])

    def test_conflicting_grade_and_language(self):
        self.assertEqual(resolve_query({"text": "PSA 9 Japanese", "grade": "10", "language": "en"}, CAT)["status"], "CONFLICT")

    def test_conflicting_text_never_overridden_by_structured_values(self):
        for query in ({"text":"PSA 9 PSA 10", "identity_key":CAT[0]['identity_key'],"language":"ja","grader":"PSA","grade":"10"},
                      {"text":"PSA 12345678","certification_number":"12345679"},
                      {"text":"BGS 12345678","grader":"PSA"}):
            self.assertEqual(resolve_query(query,CAT)["status"],"CONFLICT")

    def test_offline_search_never_constructs_client(self):
        from unittest.mock import patch
        with patch("similar_listings.EbayClient", side_effect=AssertionError("network")):
            self.assertEqual(search_similar("PSA 12345678", [], live=False)["status"], "READY_FOR_SEARCH")

    def test_live_mock_keeps_unknown_identity_and_cross_market_item_single(self):
        class Client:
            requests_used = 2
            def search(self, *args, **kwargs):
                return {"items": [{"itemId": "v1|123|0", "title": "Pokemon Pikachu PSA 10"}],
                        "coverage": {"complete": False, "raw_count": 1}}
        r = search_similar("PSA 12345678", [], live=True, markets=["EBAY_US", "EBAY_GB"], client=Client())
        self.assertEqual(len(r["listings"]), 1)
        self.assertEqual(r["raw_listing_count"], 2)
        self.assertIsNone(r["exact_match_supply"])
        self.assertEqual(r['status'],'PARTIAL_RESULTS')
        self.assertEqual(len(r['listings'][0]['observations']),2)

    def test_bad_query(self):
        for query in ({"grade": 10}, {"unknown": "x"}, ""):
            with self.assertRaises(ValueError):
                resolve_query(query, CAT)


if __name__ == "__main__":
    unittest.main()
