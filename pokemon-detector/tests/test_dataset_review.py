"""Photo Review Lab: reviewed labels, original photo hash and safe atomic JSON."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataset_review import PhotoReviewStore, PhotoReviewError

# Minimal synthetic PNG signatures; test the annotation bookkeeping, not
# image decoding accuracy (covered separately in local_cv/reference tests).
ONE_PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-file-A"
TWO_PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-file-B"
CAT = [{"identity_key":"demo:card-A","name":"Card A","number":"1/1"}]


class TestPhotoReviewStore(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.photos=self.root/"photos"
        self.photos.mkdir()
        self.private=self.root/"private"
        self.private.mkdir()
        (self.photos/"a.png").write_bytes(ONE_PNG)
        (self.photos/"b.png").write_bytes(TWO_PNG)
        (self.photos/"secret.txt").write_text("not an image")
        self.output=self.private/"holdout.json"
        self.store=PhotoReviewStore(self.photos,self.output,CAT)

    def data(self, *, case_id="case_001", photo="a.png", kind="single",
             key="demo:card-A", box=None, **extra):
        d={"case_id":case_id,"image_file":photo,"kind":kind,"split":"holdout",
           "expected_identity_key":key,"annotation_verified":True,
           "annotation_reference":"manual-inspection-001",
           "reviewer":"human-1", "bbox_xyxy":box, "notes":"inspected"}
        d.update(extra)
        return d

    def test_photo_allowlist_and_images_only(self):
        self.assertEqual(self.store.photo_names,("a.png","b.png"))
        data,mime=self.store.image("a.png")
        self.assertEqual(data,ONE_PNG)
        self.assertEqual(mime,"image/png")
        for name in ("../../etc/passwd","secret.txt","/etc/passwd","sub/a.png",
                     "a.png/../secret.txt",".hidden.png",None):
            with self.subTest(name=name),self.assertRaises(PhotoReviewError):
                self.store.image(name)

    def test_save_and_reload_private_manifest(self):
        row=self.store.save(self.data())
        self.assertEqual(len(row["photo_sha256"]),64)
        self.assertTrue(self.output.is_file())
        self.assertEqual(self.store.summary()["labeled_photos"],1)
        self.assertEqual(self.store.summary()["labeled_cases"],1)
        again=PhotoReviewStore(self.photos,self.output,CAT)
        self.assertEqual(again.export()["cases"][0],row)
        self.assertEqual(again.summary()["status"],"PRIVATE_REVIEW_ONLY_NOT_CALIBRATED")

    def test_multi_card_binder_distinct_regions(self):
        a=self.data(case_id="binder_001",kind="binder",
                    box=[.05,.05,.40,.48])
        b=self.data(case_id="binder_002",kind="binder",
                    box=[.58,.50,.95,.95])
        self.store.save(a)
        self.store.save(b)
        self.assertEqual(self.store.summary()["labeled_cases"],2)
        with self.assertRaisesRegex(PhotoReviewError,"Overlapping"):
            self.store.save(self.data(case_id="binder_003",kind="binder",
                                      box=[.06,.06,.40,.48]))
        with self.assertRaisesRegex(PhotoReviewError,"Overlapping"):
            self.store.save(self.data(case_id="binder_004",kind="binder"))
        with self.assertRaisesRegex(PhotoReviewError,"existing case"):
            self.store.save(self.data(case_id="binder_001",photo="b.png",kind="binder"))

    def test_negative_has_no_identity(self):
        row=self.store.save(self.data(case_id="negative_001",kind="negative",key=None))
        self.assertIsNone(row["expected_identity_key"])
        with self.assertRaises(PhotoReviewError):
            self.store.save(self.data(case_id="negative_002",kind="negative"))

    def test_human_attestation_and_proof_required(self):
        for change in (
            {"annotation_verified":False},
            {"annotation_reference":""},
            {"reviewer":""},
            {"expected_identity_key":""},
            {"expected_identity_key":"not-a-catalog-card"},
            {"split":"training"},
            {"bbox_xyxy":[.5,.5,.1,.1]},
            {"bbox_xyxy":[0,0,0.001,0.001]},
            {"reviewed_at":"2999-01-01"},
            {"case_id":"x/../a"}
        ):
            with self.subTest(change=change),self.assertRaises(PhotoReviewError):
                self.store.save(self.data(**change))
        self.assertFalse(self.output.exists())

    def test_detect_changed_photo_after_human_review(self):
        row=self.store.save(self.data())
        self.assertEqual(self.store.summary()["labeled_cases"],1)
        (self.photos/"a.png").write_bytes(b"\x89PNG\r\n\x1a\nchanged")
        with self.assertRaisesRegex(PhotoReviewError,"digest"):
            self.store.save({**row,"notes":"re-reviewed"})
        with self.assertRaisesRegex(PhotoReviewError,"digest"):
            PhotoReviewStore(self.photos,self.output,CAT)

    def test_atomic_failed_update_does_not_lose_previous_review(self):
        stored=self.store.save(self.data())
        old_content=self.output.read_text()
        with self.assertRaises(PhotoReviewError):
            self.store.save(self.data(case_id="case_002",photo="does-not-exist.png"))
        self.assertEqual(self.output.read_text(),old_content)
        self.assertEqual(self.store.export()["cases"],[stored])

    def test_no_dataset_in_photo_source_directory(self):
        with self.assertRaises(PhotoReviewError):
            PhotoReviewStore(self.photos,self.photos/"labels.json",CAT)

    def test_symlink_not_in_photo_allowlist(self):
        outside=self.root/"external.png"
        outside.write_bytes(ONE_PNG)
        link=self.photos/"link.png"
        try:
            link.symlink_to(outside)
        except (NotImplementedError,OSError):
            self.skipTest("Symlinks require special permission on this OS")
        fresh=PhotoReviewStore(self.photos,self.private/"other.json",CAT)
        self.assertNotIn("link.png",fresh.photo_names)


if __name__=="__main__":
    unittest.main()
