"""Offline tests for local-photo input; no eBay credentials or vision API."""
import base64
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from photo_inputs import PhotoInputError, prepare_photo_inputs
from vision import analyze_listing, call_vision_api, VisionError

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+y0QcAAAAASUVORK5CYII="
)


class TestPhotoInputs(unittest.TestCase):
    def _local(self, folder, name="one.png", contents=PNG):
        path = Path(folder) / name
        path.write_bytes(contents)
        return str(path)

    def test_offline_local_photo_has_manifest_without_embedded_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._local(tmp)
            result = prepare_photo_inputs({"image_files": [path]})
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["image_messages"], [])
        self.assertEqual(result["manifest"][0]["reference"], "one.png")
        self.assertEqual(result["manifest"][0]["mime"], "image/png")
        self.assertTrue(result["local"])

    def test_photo_packed_as_data_url_only_for_explicit_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._local(tmp)
            res = prepare_photo_inputs({"image_files": [path]}, encode_local=True)
        uri = res["image_messages"][0]["image_url"]["url"]
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), PNG)

    def test_reject_fake_or_unreadable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in [("fake.png", b"not an image"), ("evil.exe", PNG)]:
                path = self._local(tmp, name, data)
                with self.subTest(name=name), self.assertRaises(PhotoInputError):
                    prepare_photo_inputs({"image_files": [path]})
            missing = str(Path(tmp) / "missing.png")
            with self.assertRaises(PhotoInputError):
                prepare_photo_inputs({"image_files": [missing]})

    def test_invalid_and_oversized(self):
        with tempfile.TemporaryDirectory() as tmp:
            huge = self._local(tmp, "huge.png", PNG + b"x" * (5 * 1024 * 1024))
            with self.assertRaises(PhotoInputError):
                prepare_photo_inputs({"image_files": [huge]})
            p = self._local(tmp)
            with self.assertRaises(PhotoInputError):
                prepare_photo_inputs({"image_files": [p] * 9})
            with self.assertRaises(PhotoInputError):
                prepare_photo_inputs({"image_files": [p], "image_urls": ["https://example.com/card.jpg"]})

    def test_model_cached_observation_and_local_photo_no_network(self):
        observation = {
            "kind": "single", "inventory_complete": False,
            "observations": [{
                "image_index": 0, "bbox_xyxy": [.1, .1, .9, .9],
                "name": "Pikachu", "set": "151", "number": "25/165",
                "language": "en", "finish": "normal", "condition": "unknown",
                "identity_confidence": .8, "condition_confidence": .2,
                "photo_confidence": .85,
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = self._local(tmp, "binder.png")
            listing = {"image_files": [path], "asking_eur": 40, "kind_hint": "single"}
            with patch("vision.call_vision_api", side_effect=AssertionError("Should not call provider")):
                out = analyze_listing(listing, [], observation=observation, asof=dt.date(2026, 10, 12))
        self.assertEqual(out["status"], "VISION_ONLY_NOT_BUY_READY")
        self.assertEqual(out["image_urls"], [])
        self.assertEqual(out["image_manifest"][0]["reference"], "binder.png")
        self.assertEqual(out["assessment"]["decision"], "REVIEW")
        self.assertIsNone(out["assessment"]["roi"])
        self.assertTrue(out["assessment"]["manual_approval_required"])

    def test_optional_provider_call_is_mockable_with_local_data(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, size): return json.dumps({
                "choices": [{"message": {"content": json.dumps({
                    "kind": "single", "observations": []
                })}}]
            }).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._local(tmp)
            def opener(req, timeout):
                payload = json.loads(req.data)
                image = payload["messages"][1]["content"][1]["image_url"]["url"]
                self.assertTrue(image.startswith("data:image/png;base64,"))
                self.assertIn("Bearer", req.headers["Authorization"])
                return Response()
            with patch.dict("os.environ", {"VISION_API_KEY": "test-only-key",
                                           "BIGSTEN_PAID_VISION_AUTHORIZED": "1",
                                           "VISION_API_URL": "https://api.openai.com/v1/chat/completions"}), \
                 patch("vision.urllib.request.urlopen", side_effect=opener):
                got = call_vision_api({"image_files": [path], "title": "Mock listing"})
        self.assertEqual(got["kind"], "single")


if __name__ == "__main__":
    unittest.main()
