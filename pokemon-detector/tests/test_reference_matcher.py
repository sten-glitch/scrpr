"""Synthetic OpenCV reference-matcher smoke tests; NOT real Pokémon accuracy.

Dependencies are OPTIONAL for offline alpha, but installed in the CI visual
job. All reference images here are programmatically created test patterns
and never downloaded from Pokémon artwork websites.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import cv2
    import numpy as np
    from PIL import Image
    HAS_CV = True
except ImportError:
    HAS_CV = False

from reference_matcher import (
    ReferenceMatcher, ReferenceMatchError, build_reference_index,
    _safe_reference,
)

CATALOG = [
    {"identity_key": "demo:variant-A", "name": "Synthetic Card A",
     "set": "TEST", "number": "1/2", "language": "en", "finish": "holo"},
    {"identity_key": "demo:variant-B", "name": "Synthetic Card B",
     "set": "TEST", "number": "2/2", "language": "en", "finish": "normal"},
]


def synthetic_card(seed=1):
    rng = np.random.default_rng(seed)
    # Distinct high-texture patterns ensure a meaningful ORB smoke test.
    card = rng.integers(20, 235, size=(500,350,3),dtype=np.uint8)
    card = cv2.GaussianBlur(card,(3,3),0)
    cv2.rectangle(card,(12,12),(338,488),(0,0,0),6)
    cv2.rectangle(card,(27,75),(320,350),(255,255,255),3)
    cv2.putText(card, f"TEST {seed}", (32,57),cv2.FONT_HERSHEY_SIMPLEX,.95,(255,255,255),2)
    cv2.putText(card, "1/2", (255,460),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
    return card


def image_bytes(img):
    ok, encoded = cv2.imencode(".png",img)
    if not ok:
        raise RuntimeError("Could not encode test image")
    return encoded.tobytes()


def manifest(*entries):
    return {"references": [
        {"reference_id": ref, "identity_key": key,
         "image_file": filename, "rights_basis": "user_owned",
         "permission_reference": f"TEST_SYNTHETIC_{ref}"}
        for ref,key,filename in entries
    ]}


@unittest.skipUnless(HAS_CV, "Optional local OpenCV, NumPy and Pillow not installed")
class TestReferenceMatcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "photos").mkdir()
        (self.root / "private").mkdir()

    def make_reference(self, name="a.png", seed=1):
        img = synthetic_card(seed)
        (self.root / "photos" / name).write_bytes(image_bytes(img))
        return img

    def build(self, spec):
        output=self.root/"private"/"cards.sqlite"
        stats=build_reference_index(spec,self.root/"photos",output,CATALOG)
        self.assertFalse(stats["rights_verified_by_software"])
        return ReferenceMatcher(output)

    def test_good_reference_photo_has_visual_candidate(self):
        img=self.make_reference()
        matcher=self.build(manifest(("ref_A","demo:variant-A","a.png")))
        res=matcher.match_bgr(img)
        self.assertEqual(res["status"], "VISUAL_CANDIDATE")
        self.assertEqual(res["matched_identity_key"], "demo:variant-A")
        self.assertEqual(res["candidates"][0]["phash_distance"],0)
        self.assertGreaterEqual(res["candidates"][0]["orb_good_matches"],8)

    def test_duplicate_art_in_distinct_variants_must_abstain(self):
        self.make_reference("a.png",seed=3)
        self.make_reference("b.png",seed=3)
        matcher=self.build(manifest(
            ("ref_A","demo:variant-A","a.png"),
            ("ref_B","demo:variant-B","b.png")))
        query=synthetic_card(3)
        res=matcher.match_bgr(query)
        self.assertEqual(res["status"], "AMBIGUOUS")
        self.assertIsNone(res["matched_identity_key"])
        self.assertEqual(len(res["candidates"]),2)

    def test_unrelated_blank_card_returns_abstain(self):
        self.make_reference("a.png",seed=4)
        matcher=self.build(manifest(("ref_A","demo:variant-A","a.png")))
        query=np.full((500,350,3),255,dtype=np.uint8)
        res=matcher.match_bgr(query)
        self.assertEqual(res["status"], "ABSTAIN")
        self.assertIsNone(res["matched_identity_key"])

    def test_same_photo_bounds_provide_unverified_reference_match(self):
        img=self.make_reference("a.png",seed=5)
        matcher=self.build(manifest(("ref_A","demo:variant-A","a.png")))
        output=matcher.match_observations([image_bytes(img)],[
            {"image_index":0,"bbox_xyxy":[0,0,1,1]},
            {"image_index":0,"bbox_xyxy":[.1,.1,.12,.12]},
        ])
        self.assertEqual(output[0]["status"],"VISUAL_CANDIDATE")
        self.assertEqual(output[1]["status"],"ABSTAIN")
        self.assertIsNone(output[1]["matched_identity_key"])

    def test_no_original_reference_image_bytes_stored_in_db(self):
        img=self.make_reference("a.png",seed=6)
        matcher=self.build(manifest(("ref_A","demo:variant-A","a.png")))
        with sqlite3.connect(self.root/"private"/"cards.sqlite") as db:
            rows=db.execute("SELECT reference_id,identity_key,phash,orb,rights_basis FROM reference_features").fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][1],"demo:variant-A")
        self.assertIsInstance(rows[0][3],bytes)
        self.assertNotEqual(rows[0][3],image_bytes(img))
        self.assertEqual(matcher.identity_count,1)

    def test_refusing_existing_index_and_missing_rights(self):
        self.make_reference()
        index=self.build(manifest(("ref_A","demo:variant-A","a.png")))
        with self.assertRaises(ReferenceMatchError):
            self.build(manifest(("ref_B","demo:variant-B","a.png")))
        source=manifest(("ref_2","demo:variant-A","a.png"))
        source["references"][0]["permission_reference"]=""
        with self.assertRaises(ReferenceMatchError):
            build_reference_index(source,self.root/"photos",
                                  self.root/"private"/"second.sqlite",CATALOG)

    def test_no_traversal_no_unknown_catalog_keys(self):
        self.make_reference()
        with self.assertRaises(ReferenceMatchError):
            _safe_reference(self.root/"photos","../../etc/passwd.png")
        source=manifest(("ref_1","not-in-catalog","a.png"))
        with self.assertRaises(ReferenceMatchError):
            build_reference_index(source,self.root/"photos",
                                  self.root/"private"/"second.sqlite",CATALOG)

    def test_reject_unverified_source_photo(self):
        self.make_reference()
        source=manifest(("ref_1","demo:variant-A","a.png"))
        source["references"][0]["rights_basis"]="unknown"
        with self.assertRaises(ReferenceMatchError):
            build_reference_index(source,self.root/"photos",
                                  self.root/"private"/"other.sqlite",CATALOG)


if __name__=="__main__":
    unittest.main()
