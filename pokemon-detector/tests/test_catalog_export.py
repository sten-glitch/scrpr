"""Offline regression tests for visual catalog export."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from catalog_export import export_catalog, export_sealed_products


SET = '''const set = {
 id: "sv03.5", name: {en: "151"}, cardCount: {official: 165},
 thirdParty: {cardmarket: 5402}
}'''
EXPLICIT = '''const card = {
 name: {en: "Charizard ex"}, rarity: "Special illustration rare",
 variants: [
  {type: "holo", thirdParty: {cardmarket: 733794, tcgplayer: 517045}},
  {type: "reverse", thirdParty: {cardmarket: 733795}}
 ]
}'''
LEGACY = '''const card = {
 name: {en: "Pikachu"}, thirdParty: {cardmarket: 1234}
}'''


class TestCatalogExport(unittest.TestCase):
    def test_explicit_variants_and_no_synthetic_legacy_reverse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Scarlet & Violet" / "151").mkdir(parents=True)
            (root / "Scarlet & Violet" / "151.ts").write_text(SET, encoding="utf-8")
            (root / "Scarlet & Violet" / "151" / "199.ts").write_text(EXPLICIT, encoding="utf-8")
            (root / "Scarlet & Violet" / "151" / "025.ts").write_text(LEGACY, encoding="utf-8")
            records = export_catalog(root)
        self.assertEqual(len(records), 3)
        holo = next(x for x in records if x["finish"] == "holo")
        self.assertEqual(holo["set"], "151")
        self.assertEqual(holo["number"], "199/165")
        self.assertEqual(holo["identity_key"], "tcgdex:sv03.5-199-holo-en-raw")
        pk = [x for x in records if x["name"] == "Pikachu"]
        self.assertEqual(len(pk), 1)
        self.assertEqual(pk[0]["finish"], "normal")

    def test_sealed_catalog_ids_are_independent_from_prints(self):
        data = [{"idProduct": 45, "name": "151 Booster Bundle", "idExpansion": 5402},
                {"idProduct": 46, "name": "151 Booster Box", "idExpansion": 5402},
                {"idProduct": "bad", "name": "Unknown", "idExpansion": 5402}]
        items = export_sealed_products(data)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["kind"], "sealed")
        self.assertEqual(items[0]["identity_key"], "cardmarket:sealed:45")
        self.assertEqual(items[0]["set"], "151")


if __name__ == "__main__":
    unittest.main()
