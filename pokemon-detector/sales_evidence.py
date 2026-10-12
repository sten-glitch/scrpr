"""BIGSTEN Pokémon — human-attested completed-sale evidence import.

No marketplace credentials or scraping. Imports a reviewed private CSV export of
completed transactions. Rejects active asking prices, unreviewed/future/stale
records, unverified identity/condition/price, bad currency and duplicated sales.

IMPORTANT: 'verified=True' in engine output means the named reviewer explicitly
attested that the underlying proof was examined. It is NOT cryptographic or
platform verification. Never load an untrusted seller-provided CSV as attested.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import json
import math
import re
import urllib.parse
from pathlib import Path

from reasoning import evaluate_deal

REQUIRED = (
    "source", "transaction_id", "source_url", "sold_at", "price_eur",
    "currency", "identity_key", "language", "condition", "sale_status",
    "proof_type", "proof_reference", "reviewer", "reviewed_at",
    "identity_verified", "condition_verified", "price_verified",
    "settlement_verified", "match_confidence",
)
PROOF_TYPES = {"settlement_record", "platform_transaction_export", "buyer_receipt", "seller_receipt"}
YES = {"yes", "true", "1"}
LANGUAGES = {"en", "jp", "de", "fr", "it", "es", "pt", "ko", "zh"}
CONDITIONS = {"NM", "LP", "MP", "HP", "DMG", "sealed"}
MAX_BYTES = 3_000_000
MAX_ROWS = 5000


def _parse_day(value: str, field: str) -> dt.date:
    try:
        if len(value) != 10:
            raise ValueError()
        return dt.date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f"{field}: expected YYYY-MM-DD")


def _url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 1500:
        raise ValueError("source_url: invalid URL")
    try:
        p = urllib.parse.urlsplit(value)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
            raise ValueError("source_url: only canonical HTTPS links without credentials/fragments")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", p.hostname) or "." not in p.hostname:
            raise ValueError("source_url: invalid hostname")
        if p.hostname.lower().endswith((".internal", ".local", ".localhost", ".test", ".invalid")):
            raise ValueError("source_url: invalid internal or test hostname")
    except ValueError:
        raise
    return value


def _row_to_comp(row: dict[str, str], asof: dt.date, max_age_days: int) -> dict:
    def get(k):
        v = row.get(k)
        return v.strip() if isinstance(v, str) else ""
    if get("sale_status").lower() != "completed":
        raise ValueError("sale_status: only completed transactions are comparable")
    if get("currency").upper() != "EUR":
        raise ValueError("currency: prices must be normalized to EUR with documented conversion before import")
    for k in ("identity_verified", "condition_verified", "price_verified", "settlement_verified"):
        if get(k).lower() not in YES:
            raise ValueError(f"{k}: reviewer attestation is required")
    proof_type = get("proof_type").lower()
    if proof_type not in PROOF_TYPES:
        raise ValueError("proof_type: a transaction record/receipt is mandatory, not a listing screenshot")
    if not get("proof_reference") or not get("reviewer") or not get("transaction_id") or not get("source"):
        raise ValueError("proof_reference, reviewer, transaction_id and source are mandatory")
    if len(get("proof_reference")) > 256 or len(get("source")) > 80 or len(get("transaction_id")) > 120 or len(get("reviewer")) > 120:
        raise ValueError("evidence reference exceeds maximum field length")
    ident = get("identity_key")
    if len(ident) < 6 or len(ident) > 256:
        raise ValueError("identity_key: precise product printing/variant is required")
    lang = get("language").lower()
    if lang not in LANGUAGES:
        raise ValueError("language: must identify product language")
    condition = get("condition")
    if condition not in CONDITIONS and not re.fullmatch(r"(PSA|BGS|CGC)_(?:[1-9]|10)(?:\.5)?", condition):
        raise ValueError("condition: specify raw/sealed or exact graded condition")
    try:
        price = float(get("price_eur"))
        confidence = float(get("match_confidence"))
    except ValueError:
        raise ValueError("price_eur and match_confidence must be numeric")
    if not math.isfinite(price) or not 0 < price <= 1000000:
        raise ValueError("price_eur: invalid realized transaction amount")
    if not math.isfinite(confidence) or not .9 <= confidence <= 1:
        raise ValueError("match_confidence: must be >= 0.90 after evidence review")
    sold_at, reviewed_at = _parse_day(get("sold_at"), "sold_at"), _parse_day(get("reviewed_at"), "reviewed_at")
    if not 0 <= (asof - sold_at).days <= max_age_days:
        raise ValueError("sold_at: stale or future transaction")
    if not sold_at <= reviewed_at <= asof:
        raise ValueError("reviewed_at: must fall between sold_at and asof")
    url = _url(get("source_url"))
    return {
        "identity_key": ident, "language": lang, "condition": condition,
        "sold": True, "verified": True, "price_eur": round(price, 2),
        "sold_at": sold_at.isoformat(), "source_url": url,
        "match_confidence": confidence,
        "verification_method": "human_attestation",
        "reviewer": get("reviewer"), "reviewed_at": reviewed_at.isoformat(),
        "proof_type": proof_type, "proof_reference": get("proof_reference"),
        "source": get("source"), "transaction_id": get("transaction_id"),
    }


def import_sales(path: str | Path, *, asof: dt.date | None = None,
                 max_age_days: int = 90) -> dict:
    """Return accepted comps and quarantined rows, never silently skip failed rows."""
    asof = asof or dt.datetime.now(dt.timezone.utc).date()
    if isinstance(max_age_days, bool) or not 1 <= max_age_days <= 365:
        raise ValueError("max_age_days must be 1..365")
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Missing or oversized CSV evidence file")
    accepted, quarantined, seen_transaction, seen_url = [], [], set(), set()
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or any(k not in reader.fieldnames for k in REQUIRED):
            raise ValueError("Invalid CSV header. Required: " + ", ".join(REQUIRED))
        for index, row in enumerate(reader, start=2):
            if index > MAX_ROWS + 1:
                raise ValueError("CSV evidence exceeds row limit")
            try:
                if None in row:
                    raise ValueError("CSV has excess columns")
                comp = _row_to_comp(row, asof, max_age_days)
                tid = (comp["source"].lower(), comp["transaction_id"].lower())
                url = comp["source_url"]
                if tid in seen_transaction or url in seen_url:
                    raise ValueError("Duplicate completed transaction / source URL")
                seen_transaction.add(tid)
                seen_url.add(url)
                accepted.append(comp)
            except (ValueError, TypeError) as exc:
                quarantined.append({"row": index, "error": str(exc)})
    return {
        "status": "HUMAN_ATTESTED_EVIDENCE_NOT_PLATFORM_VERIFIED",
        "asof": asof.isoformat(), "accepted": len(accepted),
        "quarantined": len(quarantined), "records": accepted,
        "quarantine": quarantined, "verification_limitations": [
            "Reviewer attestation cannot be cryptographically validated from a CSV",
            "Source and proof records must be inspected by a trusted reviewer",
            "This is a non-exhaustive sample; accepted comparables do NOT establish true market volume",
        ],
    }


def evaluate_with_sales(listing: dict, imported: dict, *, asof: dt.date | None = None,
                        min_roi: float = .25) -> dict:
    """Join exact like-for-like comps to listing; never trust seller costs_verified.

    Costs require a separate human-reviewed gate not provided by a raw
    marketplace listing. For binders/lots, physically audited quantities also
    require a separate gate. This function therefore cannot auto-approve.
    """
    if imported.get("status") != "HUMAN_ATTESTED_EVIDENCE_NOT_PLATFORM_VERIFIED":
        raise ValueError("A validated import report is required")
    clean = copy.deepcopy(listing)
    clean["costs_verified"] = False
    clean["inventory_verified"] = False
    items = clean.get("items")
    if not isinstance(items, list):
        raise ValueError("Listing must have normalized items")
    for item in items:
        # Replace, never append to potentially untrusted user-provided comps.
        item["sold_comps"] = [
            c for c in imported["records"]
            if c["identity_key"] == item.get("identity_key")
            and c["language"] == item.get("language")
            and c["condition"] == item.get("condition")
        ]
    result = evaluate_deal(clean, asof=asof, min_roi=min_roi)
    result["sale_evidence_import"] = {
        "accepted": imported["accepted"], "quarantined": imported["quarantined"],
        "verified_source": "human_attestation_only",
        "note": "Cost and physical inventory gates stay unverified in CSV-only mode",
    }
    if result["decision"] == "BUY_CANDIDATE":
        raise AssertionError("Sales CSV cannot approve purchase by itself")
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate human-reviewed completed Pokémon sales")
    ap.add_argument("csv_file", help="Private reviewed transaction CSV")
    ap.add_argument("--listing", help="Optional normalized listing JSON to evaluate")
    ap.add_argument("--out", default="sale_evidence_result.json")
    ap.add_argument("--asof", help="Evaluation date YYYY-MM-DD (defaults to today UTC)")
    ap.add_argument("--min-roi", type=float, default=.25)
    args = ap.parse_args(argv)
    asof = _parse_day(args.asof, "asof") if args.asof else None
    report = import_sales(args.csv_file, asof=asof)
    result = {"sale_evidence": report}
    if args.listing:
        listing = json.loads(Path(args.listing).read_text(encoding="utf-8"))
        result["deal_evaluation"] = evaluate_with_sales(listing, report, asof=asof, min_roi=args.min_roi)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Accepted {report['accepted']} human-reviewed transactions; quarantined {report['quarantined']}. Wrote {args.out}")


if __name__ == "__main__":
    main()
