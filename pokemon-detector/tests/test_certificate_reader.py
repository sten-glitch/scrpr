import io
import sys
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from certificate_reader import parse_certificate_text, read_slab_certificate
from local_cv import LocalCVError, _checked_image


class CertificateParserTests(unittest.TestCase):
    def test_explicit_prefix_preserves_leading_zero_and_no_registry_claim(self):
        original = "PSA\nCERT # 00123456\nGEM MT 10\n1999 JAPANESE\nCARD NUMBER: 003\nNAME: ピカチュウ\nSET: Promo"
        result = parse_certificate_text(original)
        self.assertEqual(result["certificate_number"], "00123456")
        self.assertEqual(result["original_text"], original)
        self.assertEqual(result["grade"], "10")
        self.assertEqual(result["card_number"], "003")
        self.assertEqual(result["card_name"], "ピカチュウ")
        self.assertEqual(result["language_clues"], ["ja"])
        self.assertEqual(result["verification_status"], "unavailable")
        self.assertLess(result["certificate_confidence"], .8)

    def test_grader_alias_and_variable_certificate_lengths(self):
        for name, expected, cert in [("Beckett", "BGS", "000123456789"), ("CGC", "CGC", "1234567")]:
            result = parse_certificate_text(f"{name}\nCertification number: {cert}\nGrade 9.5")
            self.assertEqual(result["grader"], expected)
            self.assertEqual(result["certificate_number"], cert)
            self.assertEqual(result["grade"], "9.5")

    def test_numbers_in_title_not_certificates(self):
        for text in ["PSA 10 Pikachu #003 1999 Japanese", "PSA\n1999\n003\n10"]:
            self.assertIsNone(parse_certificate_text(text, allow_label_layout=True)["certificate_number"])

    def test_layout_is_opt_in_and_weak(self):
        text = "PSA\n1999\n12345678\nGEM MT 10"
        self.assertIsNone(parse_certificate_text(text)["certificate_number"])
        result = parse_certificate_text(text, allow_label_layout=True)
        self.assertEqual(result["certificate_number"], "12345678")
        self.assertLess(result["certificate_confidence"], .5)
        self.assertIsNone(parse_certificate_text("12345678", "PSA", allow_label_layout=True)["certificate_number"])

    def test_conflicts_abstain(self):
        self.assertIsNone(parse_certificate_text("PSA CERT 12345678", "CGC")["certificate_number"])
        result = parse_certificate_text("PSA CERT 12345678\nCERT 87654321")
        self.assertIsNone(result["certificate_number"])
        self.assertIn("conflicting_certificate_candidates", result["errors"])

    def test_ocr_ambiguities_are_never_repaired(self):
        result = parse_certificate_text("PSA CERT 123O5678")
        self.assertIsNone(result["certificate_number"])
        self.assertEqual(result["candidates"][0]["value"], "123O5678")
        self.assertIn("ambiguous_certificate_characters", result["errors"])

    def test_cert_hash_not_card_number(self):
        self.assertIsNone(parse_certificate_text("PSA CERT #12345678")["card_number"])

    def test_separated_certificate_is_not_truncated(self):
        result = parse_certificate_text("PSA CERT 1234-5678")
        self.assertIsNone(result["certificate_number"])
        self.assertEqual(result["candidates"][0]["value"], "1234-5678")

    def test_short_explicit_certificate_kept_only_as_evidence(self):
        for token in ("1", "1999", "00000001"):
            result = parse_certificate_text(f"PSA CERT {token}")
            self.assertIsNone(result["certificate_number"])
            self.assertEqual(result["candidates"][0]["value"], token)
            self.assertIn("certificate_candidate_too_short", result["errors"])


class CertificateImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PIL import Image
            import cv2
        except ImportError:
            raise unittest.SkipTest("Optional image packages unavailable")
        stream = io.BytesIO()
        Image.new("RGB", (600, 1000), "white").save(stream, format="PNG")
        cls.image = stream.getvalue()

    def test_bounded_crops_and_original_evidence(self):
        calls = []
        def read(crop):
            calls.append(crop.shape)
            return "PSA\nCERT 12345678" if len(calls) == 1 else ""
        result = read_slab_certificate(self.image, ocr=read)
        self.assertEqual(result["certificate_number"], "12345678")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(max(shape) <= 1200 for shape in calls))
        self.assertEqual(len(result["image_sha256"]), 64)
        self.assertEqual(result["crops"][0]["original_text"], "PSA\nCERT 12345678")
        self.assertEqual(result["verification_status"], "unavailable")

    def test_missing_engine_not_empty_success(self):
        def missing(crop):
            raise ImportError("Not installed")
        result = read_slab_certificate(self.image, ocr=missing)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("ocr_unavailable", result["errors"])
        self.assertEqual(len(result["crops"]), 1)

    def test_conflicting_regions_not_silently_selected(self):
        results = iter(["PSA CERT 12345678", "PSA CERT 87654321"])
        result = read_slab_certificate(self.image, ocr=lambda crop: next(results))
        self.assertIsNone(result["certificate_number"])

    def test_invalid_image_rejected_before_ocr(self):
        with self.assertRaises(LocalCVError):
            read_slab_certificate(b"not an image", ocr=lambda crop: self.fail("OCR called"))

    def test_orientation_applied_before_crop_geometry(self):
        from PIL import Image
        stream = io.BytesIO()
        exif = Image.Exif()
        exif[274] = 6  # stored landscape, displayed upright
        Image.new("RGB", (100, 60), "white").save(stream, format="JPEG", exif=exif)
        _, decoded = _checked_image(stream.getvalue())
        self.assertEqual(decoded.shape[:2], (100, 60))

    def test_successful_empty_ocr_is_no_certificate(self):
        result = read_slab_certificate(self.image, ocr=lambda crop: "")
        self.assertEqual(result["status"], "no_certificate")

    def test_only_two_readers_enter_expensive_processing(self):
        release, entered = threading.Event(), threading.Event()
        guard = threading.Lock()
        active, peak = 0, 0
        def slow_read(*args, **kwargs):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    entered.set()
            release.wait(3)
            with guard:
                active -= 1
            return {}
        with patch("certificate_reader._read_slab_certificate", side_effect=slow_read):
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(read_slab_certificate, self.image) for _ in range(4)]
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(peak, 2)
                finally:
                    release.set()
                for future in futures:
                    future.result(timeout=3)
        self.assertEqual(peak, 2)


if __name__ == "__main__":
    unittest.main()
