"""Demo generator tests: copyright-free synthetic cards, no downloaded data."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    import cv2
    import numpy as np
    from PIL import Image
    HAS_CV=True
except ImportError:
    HAS_CV=False

from demo_reference_lab import create_demo
from reference_matcher import ReferenceMatcher


@unittest.skipUnless(HAS_CV,"Optional free offline CV packages not installed")
class TestSyntheticReferenceDemo(unittest.TestCase):
    def test_full_local_demo_index_and_image_build(self):
        with tempfile.TemporaryDirectory() as root:
            result=create_demo(root)
            self.assertEqual(result["status"],"SYNTHETIC_DEMONSTRATION_ONLY")
            self.assertEqual(result["reference_count"],2)
            self.assertTrue(Path(result["catalog"]).is_file())
            self.assertTrue(Path(result["index"]).is_file())
            self.assertTrue(Path(result["query_image"]).is_file())
            self.assertTrue(Path(result["reference_manifest"]).is_file())
            matcher=ReferenceMatcher(result["index"])
            self.assertEqual(matcher.reference_count,2)
            self.assertEqual(result["self_test"]["matched_identity_key"],"bigsten:synthetic:A")
            self.assertEqual(result["self_test"]["status"],"VISUAL_CANDIDATE")
            # Demonstration references are user's generated local files,
            # not silently copied to this public repository.
            with self.assertRaisesRegex(ValueError,"refusing to overwrite"):
                create_demo(root)


    def test_resume_after_interrupted_windows_sqlite_write_keeps_user_files(self):
        """Reproduces user's partial directory from WinError 32 safely."""
        with tempfile.TemporaryDirectory() as root:
            with patch("demo_reference_lab.build_reference_index",
                       side_effect=PermissionError("[WinError 32] SQLite file in use")):
                with self.assertRaises(PermissionError):
                    create_demo(root)
            root=Path(root)
            self.assertFalse((root/"demo_cards.sqlite").exists())
            demo_photo=root/"demo_references"/"demo_reference_A.png"
            catalog=root/"demo_catalog.json"
            manifest=root/"demo_reference_manifest.json"
            query=root/"demo_queries"/"demo_query_A.png"
            before={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (demo_photo,catalog,manifest,query)}
            repaired=create_demo(root,resume=True)
            self.assertEqual(repaired["self_test"]["status"],"VISUAL_CANDIDATE")
            self.assertEqual(repaired["reference_count"],2)
            after={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (demo_photo,catalog,manifest,query)}
            self.assertEqual(before,after,"Resume must never modify existing demo assets")

    def test_resume_rejects_modified_files_without_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("demo_reference_lab.build_reference_index",
                       side_effect=PermissionError("simulated interrupted write")):
                with self.assertRaises(PermissionError):
                    create_demo(root)
            modified=Path(root)/"demo_references"/"demo_reference_A.png"
            modified.write_bytes(b"THIS IS NOT A DEMO IMAGE")
            with self.assertRaisesRegex(ValueError,"refusing to overwrite"):
                create_demo(root,resume=True)
            self.assertEqual(modified.read_bytes(),b"THIS IS NOT A DEMO IMAGE")
            self.assertFalse((Path(root)/"demo_cards.sqlite").exists())


if __name__=="__main__":
    unittest.main()
