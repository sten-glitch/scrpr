"""No-network tests: web image research must never invent detection precision."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from public_photo_audit import run_public_photo_audit, audit_html, PublicAuditError


def fake_commons(*, max_images, root, search):
    p=Path(root)
    p.mkdir(parents=True,exist_ok=True)
    (p/"scene.png").write_bytes(b"\x89PNG\r\n\x1a\nPHOTO_1")
    (p/"copy.png").write_bytes(b"\x89PNG\r\n\x1a\nPHOTO_1")
    return {
        "items":[
            {"image_file":"scene.png","source_title":"Card & collectors <script>",
             "source_page":"https://commons.wikimedia.org/wiki/File:card_%26_collectors.jpg",
             "author":"Photographer<script>","license":"CC BY-SA 4.0"},
            {"image_file":"copy.png","source_title":"Duplicate","author":"",
             "source_page":"https://commons.wikimedia.org/wiki/File:duplicate.jpg",
             "license":"CC BY-SA 4.0"},
        ],
        "failed":[{"reason":"one image rejected by Commons whitelist"}],
    }


def fake_previews(*,root):
    p=Path(root)
    p.mkdir(parents=True,exist_ok=True)
    (p/"demo.jpg").write_bytes(b"\xff\xd8\xffPHOTO_2\xff\xd9")
    return {"items":[{"image_file":"demo.jpg",
                      "source_page":"https://universe.roboflow.com/tcg-card-dectector/pokemon-card-detector-gksmy",
                      "license_displayed":"CC BY 4.0"}],
            "failed":[]}


class TestPublicPhotoAudit(unittest.TestCase):
    def scan(self, binary,run_ocr):
        self.assertFalse(run_ocr)
        if b"PHOTO_1" in binary:
            return {"observations":[{"bbox_xyxy":[.15,.2,.8,.9]}]}
        return {"observations":[]}

    def test_two_unique_real_images_are_unlabeled_not_identity_accuracy(self):
        report=run_public_photo_audit(
            commons=20, previews=True, search="pokemon cards",
            commons_import=fake_commons, preview_import=fake_previews,
            image_analysis=self.scan)
        s=report["summary"]
        self.assertEqual(s["real_public_photos_processed"],2)
        self.assertEqual(s["provisional_rectangles"],1)
        self.assertEqual(s["photos_with_at_least_one_rectangle"],1)
        self.assertEqual(s["download_or_analysis_failures"],1)
        self.assertIsNone(s["card_box_precision"])
        self.assertIsNone(s["real_photo_card_identity_accuracy"])
        self.assertEqual(s["identified_pokemon_card_printings"],0)
        self.assertTrue(all(not row["card_presence_human_verified"]
                            for row in report["cases"]))
        self.assertNotIn("PHOTO_1",json.dumps(report))
        output=audit_html(report)
        self.assertIn("UNLABELED RESEARCH",output)
        self.assertIn("CC BY-SA 4.0",output)
        self.assertIn("&lt;script&gt;",output)
        self.assertNotIn("<script>",output)
        self.assertNotIn("<img",output)

    def test_reject_invalid_source_selection(self):
        for kwargs in ({"commons":-1},{"commons":100},
                       {"commons":0,"previews":False},
                       {"search":"a"},{"previews":"false"}):
            with self.subTest(kwargs=kwargs),self.assertRaises(PublicAuditError):
                run_public_photo_audit(**kwargs)

    def test_one_source_failure_does_not_invent_results(self):
        def inaccessible(**_kwargs):
            raise ValueError("source unavailable")
        report=run_public_photo_audit(
            commons=4, previews=False,
            commons_import=inaccessible,
            image_analysis=self.scan)
        self.assertEqual(report["summary"]["real_public_photos_processed"],0)
        self.assertEqual(report["summary"]["download_or_analysis_failures"],1)
        self.assertEqual(report["status"],
                         "REAL_PUBLIC_UNLABELED_PHOTO_RESEARCH_NOT_AN_ACCURACY_BENCHMARK")

    def test_html_rejects_fabricated_accuracy_reports(self):
        with self.assertRaises(PublicAuditError):
            audit_html({"status":"PERFECT_ACCURACY","summary":{}})

    def test_bad_decoded_image_is_counted_as_error_not_photo(self):
        def invalid_image(*_args,**_kwargs):
            raise ValueError("malformed image")
        report=run_public_photo_audit(
            commons=10, previews=True,
            commons_import=fake_commons,
            preview_import=fake_previews,
            image_analysis=invalid_image)
        self.assertEqual(report["summary"]["real_public_photos_processed"],0)
        self.assertEqual(report["summary"]["download_or_analysis_failures"],3)


if __name__ == "__main__":
    unittest.main()
