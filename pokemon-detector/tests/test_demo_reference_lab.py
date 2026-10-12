"""Demo generator tests: copyright-free synthetic cards, no downloaded data."""
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__=="__main__":
    unittest.main()
