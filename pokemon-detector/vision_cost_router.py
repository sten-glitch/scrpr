"""Local-first analysis cache and transactional reservations for injected providers.

No paid provider is configured. An injected external adapter must enforce the
supplied max_cost as a hard provider ceiling; estimates alone are insufficient.
Reservations survive errors/crashes and unknown billing is never refunded.
"""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, InvalidOperation
import hashlib
import io
import json
import sqlite3
import uuid
from ebay_deletion import DeletionLedger


def _units(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid budget amount") from exc
    if not number.is_finite() or number < 0 or number > 1000000:
        raise ValueError("Invalid budget amount")
    return int((number * 1000000).to_integral_value(rounding=ROUND_CEILING))


class VisionCostRouter:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self.deletions = DeletionLedger(db_path)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS vision_cache (
                    cache_key TEXT PRIMARY KEY, result_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS vision_budget (
                    id TEXT PRIMARY KEY, listing_id TEXT NOT NULL,
                    day TEXT NOT NULL, month TEXT NOT NULL,
                    reserved INTEGER NOT NULL, charged INTEGER NOT NULL,
                    status TEXT NOT NULL);
            """)

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        db.execute('PRAGMA secure_delete=ON')
        return db

    def analyze_listing_image(self, image, metadata, budget=None, policy=None, *,
                              local_analyzer=None, external_analyzer=None):
        budget, policy = budget or {}, policy or {}
        deletion_epoch = self.deletions.epoch()
        if not isinstance(image, bytes) or not image or len(image) > 5 * 1024 * 1024:
            raise ValueError("Expected image bytes up to 5 MiB")
        if not isinstance(metadata, dict):
            raise ValueError("Metadata must be a dictionary")
        from PIL import Image
        with Image.open(io.BytesIO(image)) as photo:
            pixels = photo.width * photo.height
            if pixels > 12000000:
                raise ValueError("Image exceeds pixel limit")
            if photo.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Unsupported image format")
            photo.verify()
        canonical = json.dumps({"metadata": metadata, "model": policy.get("model", "local-certificate-v1"),
            "pipeline": policy.get("pipeline", "local-first-v2"),
            "external_enabled": policy.get("external_authorized") is True and external_analyzer is not None},
            sort_keys=True, separators=(",", ":"), allow_nan=False)
        key = hashlib.sha256(image + canonical.encode()).hexdigest()
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self.deletions.register(db, 'cache', key, metadata, epoch=deletion_epoch)
            cached = db.execute("SELECT result_json FROM vision_cache WHERE cache_key=?", (key,)).fetchone()
        if cached:
            response = json.loads(cached[0])
            response.update(cache_hit=True, external_called=False, cost_reserved=0, actual_cost=0)
            return response
        if local_analyzer is None:
            from certificate_reader import read_slab_certificate
            local = read_slab_certificate(image, grader_hint=metadata.get("grader_hint"))
        else:
            local = local_analyzer(image, metadata)
        if not isinstance(local, dict):
            raise ValueError("Local analyzer must return a dictionary")
        response = {"result": local, "source": "local", "cache_hit": False,
                    "external_called": False, "reason": "local_unresolved", "cost_reserved": 0}
        if local.get("resolved") is True:
            response["reason"] = "local_resolved"
            self._cache(key, response, metadata, deletion_epoch)
            return response
        if policy.get("external_authorized") is not True or external_analyzer is None:
            response["reason"] = "external_disabled"
            if local.get("status") not in {"unavailable", "partial"} and not local.get("errors"):
                self._cache(key, response, metadata, deletion_epoch)
            return response
        # An estimate is not an upper bound. Only adapters with enforced ceilings
        # may be called; the entire ceiling, not the estimate, is reserved.
        if policy.get("provider_enforces_max_cost") is not True:
            response["reason"] = "provider_cost_ceiling_unavailable"
            return response
        max_pixels = policy.get("max_pixels", 1024 * 1024)
        if not isinstance(max_pixels, int) or not 1 <= max_pixels <= 25000000 or pixels > max_pixels:
            response["reason"] = "resolution_limit"
            return response
        listing_id = metadata.get("listing_id")
        if not isinstance(listing_id, str) or not listing_id.strip():
            raise ValueError("External analysis requires listing_id")
        ceiling = _units(policy.get("max_cost", 0))
        estimate = _units(policy.get("estimated_cost", 0))
        if not ceiling or estimate > ceiling:
            raise ValueError("A positive cost ceiling >= estimated cost is required")
        limits = [_units(budget.get(k, 0)) for k in ("daily", "monthly", "per_listing")]
        attempts = budget.get("max_attempts_per_listing", 1)
        concurrency = policy.get("max_concurrency", 1)
        if type(attempts) is not int or not 1 <= attempts <= 10 or type(concurrency) is not int or not 1 <= concurrency <= 10:
            raise ValueError("Invalid attempt/concurrency limit")
        now = datetime.now(timezone.utc)
        day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
        reservation = uuid.uuid4().hex
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            self.deletions.register(db, 'cache', key, metadata, epoch=deletion_epoch)
            active = db.execute("SELECT COUNT(*) FROM vision_budget WHERE status='pending'").fetchone()[0]
            overrun = db.execute("SELECT COUNT(*) FROM vision_budget WHERE status='provider_cost_overrun'").fetchone()[0]
            count = db.execute("SELECT COUNT(*) FROM vision_budget WHERE listing_id=?", (listing_id,)).fetchone()[0]
            sums = [db.execute("SELECT COALESCE(SUM(charged),0) FROM vision_budget WHERE " + column + "=?", (value,)).fetchone()[0]
                    for column, value in (("day", day), ("month", month), ("listing_id", listing_id))]
            reason = "concurrency_limit" if active >= concurrency else "attempt_limit" if count >= attempts else None
            if any(spent + ceiling > limit for spent, limit in zip(sums, limits)):
                reason = "budget_exhausted"
            if overrun:
                reason = "provider_cost_ceiling_breached"
            if reason:
                db.rollback()
                response["reason"] = reason
                return response
            db.execute("INSERT INTO vision_budget VALUES(?,?,?,?,?,?,?)",
                       (reservation, listing_id, day, month, ceiling, ceiling, "pending"))
            db.commit()
        response.update(external_called=True, cost_reserved=ceiling / 1000000)
        charged, status = ceiling, "failed_unknown_cost"
        try:
            external = external_analyzer(image, metadata, max_cost=ceiling / 1000000)
            if not isinstance(external, dict) or not isinstance(external.get("result"), dict):
                raise ValueError("Invalid provider result")
            if external.get("actual_cost") is not None:
                charged = _units(external["actual_cost"])
            status = "complete" if charged <= ceiling else "provider_cost_overrun"
            response.update(result=external["result"], source="external", reason=status,
                            actual_cost=external.get("actual_cost"))
        except Exception:
            response["reason"] = "external_failed_unknown_cost"
        finally:
            with closing(self._connect()) as db:
                db.execute("UPDATE vision_budget SET charged=?,status=? WHERE id=?", (charged, status, reservation))
        if status == "complete":
            self._cache(key, response, metadata, deletion_epoch)
        return response

    def _cache(self, key, response, metadata, deletion_epoch):
        data = json.dumps(response, allow_nan=False)
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self.deletions.register(db, 'cache', key, metadata, epoch=deletion_epoch)
            db.execute("INSERT OR REPLACE INTO vision_cache VALUES(?,?)", (key, data))
