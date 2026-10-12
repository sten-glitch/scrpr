"""Unlabeled public photo import must not automatically authenticate cards."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_web_photo_review import prepare_web_photo_review, ReviewImportError

PNG_HEAD=b"\x89PNG\r\n\x1a\n"

class TestExternalReviewPrep(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.dataset=self.root/"third-party"
        for part in ("train/images","test/images","test/labels"):
            (self.dataset/part).mkdir(parents=True)
        (self.dataset/"data.yaml").write_text("names: ['card']\n",encoding="utf-8")

    def test_train_leakage_and_duplicates_excluded_from_review_sample(self):
        (self.dataset/"train/images"/"train.png").write_bytes(PNG_HEAD+b"already-seen")
        (self.dataset/"test/images"/"leaked.png").write_bytes(PNG_HEAD+b"already-seen")
        (self.dataset/"test/images"/"one.png").write_bytes(PNG_HEAD+b"unique-A")
        (self.dataset/"test/images"/"duplicate.png").write_bytes(PNG_HEAD+b"unique-A")
        (self.dataset/"test/images"/"two.png").write_bytes(PNG_HEAD+b"unique-B")
        (self.dataset/"test/images"/"notes.jpg").write_bytes(b"not real photo")
        output=self.root/"private-review"
        result=prepare_web_photo_review(self.dataset,output,source="detector",max_photos=50)
        self.assertEqual(result["photo_count"],2)
        self.assertFalse(result["identity_accuracy_eligible_without_human_review"])
        names=[r["image_file"] for r in result["images"]]
        self.assertTrue(all(name.startswith("detector_test_") for name in names))
        self.assertTrue(all((output/name).is_file() for name in names))
        self.assertTrue(all(row["exact_card_identity_known"] is False for row in result["images"]))
        self.assertFalse(result["test_split_is_guaranteed_independent"])
        meta=json.loads((output/"SOURCE_ATTRIBUTION.json").read_text())
        self.assertEqual(meta["photo_count"],2)
        with self.assertRaisesRegex(ReviewImportError,"not empty"):
            prepare_web_photo_review(self.dataset,output,source="detector",max_photos=50)

    def test_unsupported_splits_and_unknown_sources_fail_closed(self):
        (self.dataset/"test/images"/"one.png").write_bytes(PNG_HEAD+b"unique")
        with self.assertRaisesRegex(ReviewImportError,"held-out"):
            prepare_web_photo_review(self.dataset,self.root/"output",
                                     source="detector",split="train")
        with self.assertRaisesRegex(ReviewImportError,"Unknown"):
            prepare_web_photo_review(self.dataset,self.root/"output",source="untrusted")
        with self.assertRaisesRegex(ReviewImportError,"Maximum"):
            prepare_web_photo_review(self.dataset,self.root/"output",source="detector",max_photos=500)

    def test_no_exact_variant_or_photo_rights_claims(self):
        (self.dataset/"test/images"/"one.png").write_bytes(PNG_HEAD+b"unique")
        x=prepare_web_photo_review(self.dataset,self.root/"out",
                                   source="binder",max_photos=1)
        self.assertEqual(x["source"]["license_displayed"],"CC BY 4.0")
        self.assertFalse(x["images"][0]["commercial_reuse_cleared"])
        self.assertTrue(x["images"][0]["needs_manual_content_and_rights_review"])

if __name__=="__main__":
    unittest.main()
