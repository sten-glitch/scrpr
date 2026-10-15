"""Only low-trust catalog candidates; never treat fuzzy OCR as verified pricing."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalog_candidates import CatalogCandidateIndex, suggest_for_observations

CATALOG=[
    {"identity_key":"tcgdex:sv03.5-199-holo-en-raw","name":"Charizard ex",
     "set":"151","number":"199/165","finish":"holo","language":"en"},
    {"identity_key":"tcgdex:sv03.5-199-reverse-en-raw","name":"Charizard ex",
     "set":"151","number":"199/165","finish":"reverse","language":"en"},
    {"identity_key":"tcgdex:old-199-normal-en-raw","name":"Pikachu",
     "set":"Some Other Set","number":"199/165","finish":"normal","language":"en"},
    {"identity_key":"cardmarket:sealed:133","name":"Booster Box",
     "kind":"sealed","set":"151","number":"199/165"},
]


class TestCatalogCandidates(unittest.TestCase):
    def test_printing_candidates_never_verified(self):
        idx=CatalogCandidateIndex(CATALOG)
        result=idx.suggest({"name":"Charizard ex","number":"199/165"})
        self.assertEqual(len(result),2)
        self.assertEqual({x["finish"] for x in result},{"holo","reverse"})
        self.assertTrue(all(x["requires_manual_confirmation"] and
                            x["status"]=="CANDIDATE_NOT_VERIFIED" for x in result))

    def test_wrong_name_not_automatically_resolved_from_collector_number(self):
        idx=CatalogCandidateIndex(CATALOG)
        self.assertEqual(idx.suggest({"name":"Gengar","number":"199/165"}),[])

    def test_wrong_number_blocks_name_match(self):
        idx=CatalogCandidateIndex(CATALOG)
        self.assertEqual(idx.suggest({"name":"Charizard ex","number":"999/999"}),[])

    def test_name_only_suggests_but_does_not_resolve_identity(self):
        idx=CatalogCandidateIndex(CATALOG)
        result=idx.suggest({"name":"Charizard ex","number":None})
        self.assertGreaterEqual(len(result),1)
        self.assertFalse(result[0]["collector_number_matches"])

    def test_unknown_photo_abstains(self):
        idx=CatalogCandidateIndex(CATALOG)
        self.assertEqual(idx.suggest({"name":None,"number":None}),[])
        self.assertEqual(idx.suggest({"name":"????","number":None}),[])

    def test_observation_index_and_variant_remain_separate(self):
        report=suggest_for_observations(CATALOG,[{"image_index":0,"name":"Charizard ex","number":"199/165"}])
        self.assertEqual(report[0]["observation_index"],0)
        self.assertEqual(len(report[0]["candidates"]),2)
        self.assertIn("not proof",report[0]["note"])

    def test_catalog_input_validation_and_limits(self):
        with self.assertRaises(ValueError):
            CatalogCandidateIndex(None)
        idx=CatalogCandidateIndex(CATALOG)
        with self.assertRaises(ValueError):
            idx.suggest({"name":"Pikachu"},limit=20)
        with self.assertRaises(ValueError):
            suggest_for_observations(CATALOG,{"name":"Pikachu"})


if __name__=="__main__":
    unittest.main()
