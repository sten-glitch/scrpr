"""Synthetic binder image detection tests — not a card recognition benchmark.

All images generated in memory with basic rectangles; tests only geometry,
abstention, and decompression/pixel guards. Real Pokémon listing images will
need separately labeled evaluation before any accuracy claim.
"""
import io
import sys
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

from local_cv import _checked_image, detect_card_boxes, analyze_local_photo, LocalCVError


@unittest.skipUnless(HAS_CV, "Optional CV dependencies not installed")
class TestSyntheticBinder(unittest.TestCase):
    def scene(self):
        mat=np.full((950,1350,3),245,dtype=np.uint8)
        # Realistic card aspect ~0.714, separate with clear contrasting borders.
        for x,y in [(130,160),(720,160)]:
            cv2.rectangle(mat,(x,y),(x+265,y+370),(5,5,5),7)
            cv2.rectangle(mat,(x+12,y+12),(x+253,y+358),(125,125,125),2)
        return mat

    def test_two_card_regions_can_be_found_in_synthetic_binder(self):
        scene=self.scene()
        coords=detect_card_boxes(cv2,scene,max_cards=20)
        self.assertGreaterEqual(len(coords),2)
        centers=[((box[0]+box[2])/2,(box[1]+box[3])/2) for box in coords]
        self.assertTrue(any(abs(cx-262.5/1350)<.06 and abs(cy-345/950)<.07
                            for cx,cy in centers))
        self.assertTrue(any(abs(cx-852.5/1350)<.06 and abs(cy-345/950)<.07
                            for cx,cy in centers))
        self.assertTrue(all(0<=v<=1 for box in coords for v in box))

    def test_synthetic_observations_abstain_on_identity(self):
        ok,buffer=cv2.imencode(".png",self.scene())
        self.assertTrue(ok)
        data=analyze_local_photo(buffer.tobytes(),run_ocr=False)
        self.assertGreaterEqual(len(data["observations"]),2)
        self.assertFalse(data["inventory_complete"])
        for obs in data["observations"]:
            self.assertIsNone(obs["name"])
            self.assertEqual(obs["finish"],"unknown")
            self.assertEqual(obs["condition"],"unknown")
            self.assertEqual(obs["identity_confidence"],0.0)

    def test_missing_and_tiny_image_rejected_before_recognition(self):
        with self.assertRaises(LocalCVError):
            _checked_image(b"not-a-png")
        buf=io.BytesIO()
        Image.new("RGB",(16,16),(255,255,255)).save(buf,format="PNG")
        with self.assertRaises(LocalCVError):
            _checked_image(buf.getvalue())

    def test_invalid_card_detection_limit(self):
        with self.assertRaises(LocalCVError):
            detect_card_boxes(cv2,self.scene(),max_cards=0)


if __name__=="__main__":
    unittest.main()
