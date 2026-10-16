import io
from contextlib import closing
import sqlite3
import tempfile
import threading
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from PIL import Image
except ImportError:
    Image = None
from vision_cost_router import VisionCostRouter


@unittest.skipIf(Image is None, "Optional Pillow dependency unavailable")
class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "workspace.sqlite"
        self.router = VisionCostRouter(self.path)
        stream = io.BytesIO()
        Image.new("RGB", (20, 20)).save(stream, "PNG")
        self.image = stream.getvalue()
        self.metadata = {"listing_id": "one"}
        self.budget = {"daily": 1, "monthly": 1, "per_listing": 1, "max_attempts_per_listing": 3}
        self.policy = {"external_authorized": True, "provider_enforces_max_cost": True,
                       "max_cost": .5, "estimated_cost": .1}

    def call(self, **changes):
        args = dict(budget=self.budget, policy=self.policy,
                    local_analyzer=lambda *_: {"confidence": .99},
                    external_analyzer=lambda *_, **kw: {"result": {"value": "ok"}, "actual_cost": .2})
        args.update(changes)
        return self.router.analyze_listing_image(self.image, self.metadata, **args)

    def test_external_disabled_default_and_heuristic_not_resolved(self):
        response = self.call(policy={})
        self.assertFalse(response["external_called"])
        self.assertEqual(response["reason"], "external_disabled")
        self.assertTrue(self.call()["external_called"])

    def test_explicit_local_resolution_cache_metadata_invalidation(self):
        self.call(local_analyzer=lambda *_: {"resolved": True})
        self.assertTrue(self.call()["cache_hit"])
        self.metadata["grader_hint"] = "PSA"
        self.assertFalse(self.call()["cache_hit"])

    def test_failure_retains_reserved_cost_and_exhausts_budget(self):
        def fail(*args, **kwargs):
            raise RuntimeError("secret")
        self.call(external_analyzer=fail)
        self.call(external_analyzer=fail)
        result = self.call(external_analyzer=fail)
        self.assertEqual(result["reason"], "budget_exhausted")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT SUM(charged) FROM vision_budget").fetchone()[0], 1000000)

    def test_actual_cost_reconciled_and_cache_reuses_external_result(self):
        self.call()
        self.assertTrue(self.call()["cache_hit"])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT charged FROM vision_budget").fetchone()[0], 200000)

    def test_unavailable_ocr_is_retried_and_cache_cost_is_zero(self):
        for _ in range(2):
            result = self.call(policy={}, local_analyzer=lambda *_: {"status": "unavailable"})
            self.assertFalse(result["cache_hit"])
        self.call()
        result = self.call()
        self.assertEqual(result["cost_reserved"], 0)
        self.assertEqual(result["actual_cost"], 0)

    def test_no_ceiling_resolution_attempt_limit(self):
        self.assertEqual(self.call(policy={"external_authorized": True})["reason"], "provider_cost_ceiling_unavailable")
        self.assertEqual(self.call(policy=dict(self.policy, max_pixels=100))["reason"], "resolution_limit")
        self.call(external_analyzer=lambda *a, **k: {"bad": True})
        self.assertEqual(self.call(budget=dict(self.budget, max_attempts_per_listing=1))["reason"], "attempt_limit")

    def test_each_spending_limit_blocks_before_call(self):
        for name in ("daily", "monthly", "per_listing"):
            with self.subTest(name=name):
                result = self.call(budget=dict(self.budget, **{name: .49}))
                self.assertEqual(result["reason"], "budget_exhausted")
                self.assertFalse(result["external_called"])

    def test_unknown_actual_cost_keeps_ceiling(self):
        self.call(external_analyzer=lambda *a, **k: {"result": {}})
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT charged FROM vision_budget").fetchone()[0], 500000)

    def test_overrun_recorded_and_blocks_future_calls(self):
        result = self.call(external_analyzer=lambda *a, **k: {"result": {}, "actual_cost": .6})
        self.assertEqual(result["reason"], "provider_cost_overrun")
        self.assertEqual(self.call()["reason"], "provider_cost_ceiling_breached")

    def test_concurrent_reservation_blocks_second_provider(self):
        entered, release = threading.Event(), threading.Event()
        def provider(*a, **k):
            entered.set()
            release.wait(5)
            return {"result": {}, "actual_cost": .1}
        worker = threading.Thread(target=lambda: self.call(external_analyzer=provider))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.call()["reason"], "concurrency_limit")
        finally:
            release.set()
            worker.join(5)


if __name__ == "__main__":
    unittest.main()
