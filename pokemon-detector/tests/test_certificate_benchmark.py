"""Synthetic transport fixtures test benchmark accounting, never real OCR accuracy."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from certificate_benchmark import benchmark_certificates


class CertificateBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cases = []
        for index in range(3):
            data = f"synthetic benchmark test bytes {index}".encode()
            name = f"image-{index}.png"
            (self.root / name).write_bytes(data)
            self.cases.append({"case_id": str(index), "image": name,
                               "sha256": hashlib.sha256(data).hexdigest(),
                               "grader": "PSA", "certificate_number": "00123456",
                               "is_real": False, "clear_label": index < 2,
                               "used_for_training": False, "rights_basis": "synthetic test fixture",
                               "reviewer": "test harness", "truth_source": "fabricated test expectations only",
                               "independent_group_id": str(index)})
        self.manifest = {"version": 1, "cases": self.cases}

    def test_failures_remain_in_all_and_clear_denominators(self):
        answers = iter([{"grader": "PSA", "certificate_number": "00123456"},
                        {"status": "unavailable", "errors": ["ocr_unavailable"]},
                        {"grader": "PSA", "certificate_number": "123456"}])
        report = benchmark_certificates(self.manifest, self.root, reader=lambda data: next(answers))
        self.assertEqual(report["exact_match_rate"], 1/3)
        self.assertEqual(report["clear_label_exact_match_rate"], .5)
        self.assertEqual(report["failure_count"], 1)
        self.assertTrue(report["accuracy_measurable"])
        self.assertFalse(report["real_data_gate_passed"])
        self.assertGreaterEqual(report["latency_ms"]["p95"], report["latency_ms"]["median"])
        self.assertIn("excludes native", report["memory_scope"])

    def test_unavailable_zero_is_not_measured_accuracy(self):
        report = benchmark_certificates(self.manifest, self.root, reader=lambda data: {"status": "unavailable"})
        self.assertEqual(report["exact_match_rate"], 0)
        self.assertFalse(report["accuracy_measurable"])
        self.assertEqual(report["engine_unavailable_count"], 3)

    def test_reader_exceptions_are_counted(self):
        def broken(data):
            raise RuntimeError("private exception detail")
        report = benchmark_certificates(self.manifest, self.root, reader=broken)
        self.assertEqual(report["failure_count"], 3)
        self.assertNotIn("private exception", str(report))

    def test_provenance_and_training_checks_before_reader(self):
        for key, bad in [("reviewer", ""), ("rights_basis", ""), ("truth_source", None),
                         ("used_for_training", True), ("is_real", "yes"), ("sha256", "0"*64)]:
            manifest = copy.deepcopy(self.manifest)
            manifest["cases"][0][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                benchmark_certificates(manifest, self.root, reader=lambda data: self.fail("Reader ran"))

    def test_path_traversal_and_absolute_rejected(self):
        for bad in ("../outside.png", "C:/outside.png", "/outside.png", "image.png:stream", "..\\outside.png"):
            manifest = copy.deepcopy(self.manifest)
            manifest["cases"][0]["image"] = bad
            with self.subTest(path=bad), self.assertRaises(ValueError):
                benchmark_certificates(manifest, self.root, reader=lambda data: {})

    def test_duplicate_photo_rejected(self):
        self.cases[1]["image"] = self.cases[0]["image"]
        self.cases[1]["sha256"] = self.cases[0]["sha256"]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            benchmark_certificates(self.manifest, self.root, reader=lambda data: {})

    def test_injected_reader_never_qualifies_as_real_benchmark(self):
        for index in range(3, 50):
            row = copy.deepcopy(self.cases[0])
            data = f"synthetic benchmark test bytes {index}".encode()
            row.update({"case_id": str(index), "image": f"image-{index}.png",
                        "sha256": hashlib.sha256(data).hexdigest(), "independent_group_id": str(index)})
            (self.root / row["image"]).write_bytes(data)
            self.cases.append(row)
        for row in self.cases:
            row["is_real"] = True  # metadata alone does not turn the stub into real OCR
            row["clear_label"] = True
        report = benchmark_certificates(self.manifest, self.root, reader=lambda data: {"grader": "PSA", "certificate_number": "00123456"})
        self.assertFalse(report["real_data_gate_passed"])
        self.assertEqual(report["independent_real_clear_groups"], 50)
        self.assertEqual(report["engine"], "injected_test_reader")

    def test_symlink_rejected(self):
        link = self.root / "linked.png"
        try:
            link.symlink_to(self.root / self.cases[0]["image"])
        except OSError:
            self.skipTest("Symlinks unavailable")
        self.cases[0]["image"] = link.name
        with self.assertRaisesRegex(ValueError, "Symlink"):
            benchmark_certificates(self.manifest, self.root, reader=lambda data: {})


if __name__ == "__main__":
    unittest.main()
