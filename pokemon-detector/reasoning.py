"""BIGSTEN Pokémon Deal Intelligence — conservative, evidence-first decision engine.

This module evaluates listings already discovered/normalized by adapters. It does not
scrape marketplaces, identify card images, authenticate cards, or provide sold data.
Inputs must contain EUR-denominated prices and auditable matched sold comparables.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

KINDS = {"single", "lot", "binder", "sealed"}


def _money(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite non-negative EUR amount")
    return float(value)


def _prob(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{field} must be a number from 0 to 1")
    return float(value)


def _date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s[:10])
    except (TypeError, ValueError, IndexError):
        return None


def _lower_quantile(values: list[float], fraction: float = 0.25) -> float:
    """Observed lower quartile, using a data point rather than interpolation."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.floor((len(ordered) - 1) * fraction))]


def _comps(item: dict, asof: dt.date, max_age_days: int = 90) -> list[dict]:
    """Filter only independently traceable, sold, recent and like-for-like comps."""
    chosen = []
    ident = item.get("identity_key")
    for c in item.get("sold_comps", []):
        if not c.get("sold") or not c.get("verified") or not c.get("source_url"):
            continue
        if not ident or not item.get("language") or not item.get("condition") or c.get("identity_key") != ident:
            continue
        if c.get("language") != item.get("language") or c.get("condition") != item.get("condition"):
            continue
        d = _date(c.get("sold_at"))
        if d is None or not 0 <= (asof - d).days <= max_age_days:
            continue
        if _prob(c.get("match_confidence", 0), "match_confidence") < 0.9:
            continue
        price = _money(c.get("price_eur"), "price_eur")
        if price > 0:
            chosen.append({"price_eur": price, "source_url": c["source_url"], "sold_at": d.isoformat()})
    # prevent duplicate evidence from one completed sale
    unique = {c["source_url"]: c for c in chosen}
    return list(unique.values())


def evaluate_deal(listing: dict, *, asof: dt.date | None = None, min_roi: float = 0.25) -> dict:
    """Return a reproducible decision, never an automatic purchase command.

    Required fields: kind, asking_eur, items. A component's identity_key must
    distinguish edition, finish, language and grading. Condition must match comps.
    Evidence values (0..1) come from upstream verification, not the engine.
    No verified sold comps -> price/ROI/score unknown, not zero or a fake bargain.
    """
    asof = asof or dt.datetime.now(dt.timezone.utc).date()
    kind = listing.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    if listing.get("currency", "EUR") != "EUR":
        raise ValueError("normalize prices to EUR before evaluation")
    if not (0 <= min_roi <= 10):
        raise ValueError("min_roi outside supported range")
    asking = _money(listing.get("asking_eur"), "asking_eur")
    acq = listing.get("acquisition") or {}
    buy_extra = sum(_money(acq.get(k, 0), k) for k in ("shipping_eur", "taxes_eur", "customs_eur", "buyer_fees_eur", "other_eur"))
    total_buy = asking + buy_extra
    if total_buy <= 0:
        raise ValueError("total acquisition cost must be > 0")
    sale = listing.get("sale") or {}
    fee = _money(sale.get("marketplace_fee_pct", 0), "marketplace_fee_pct")
    if fee >= 100:
        raise ValueError("marketplace fee cannot reach 100%")
    sale_extra = sum(_money(sale.get(k, 0), k) for k in ("outbound_shipping_eur", "packaging_eur", "other_eur"))

    items = listing.get("items") or []
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list (one for a single/sealed listing)")
    if kind in ("single", "sealed") and len(items) != 1:
        raise ValueError("single/sealed listing requires exactly one item")

    reasons, warnings, breakdown = [], [], []
    projected = 0.0
    total_qty = 0
    priced_qty = 0
    confidence_numer = 0.0
    material_risk = False
    weak_recent_sales = False  # sample-based indicator, not verified transaction velocity
    for i, item in enumerate(items):
        qty = item.get("quantity", 1)
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 10000:
            raise ValueError(f"items[{i}].quantity must be a positive integer <= 10000")
        total_qty += qty
        e = item.get("evidence") or {}
        identity = _prob(e.get("identity_confidence", 0), "identity_confidence")
        condition = _prob(e.get("condition_confidence", 0), "condition_confidence")
        photo = _prob(e.get("photo_confidence", 0), "photo_confidence")
        authenticity = _prob(e.get("authenticity_confidence", 0), "authenticity_confidence")
        if e.get("counterfeit_risk") is True or e.get("edition_mismatch") is True:
            material_risk = True
            reasons.append(f"Item {i + 1}: semnal de fals / ediție nepotrivită")
        if kind == "sealed":
            if e.get("resealed_risk") is True:
                material_risk = True
                reasons.append(f"Item {i + 1}: semnal de posibilă resigilare")
            if authenticity < 0.8:
                warnings.append("Sigiliul nu este verificat cu suficientă încredere")
        matched = _comps(item, asof)
        recent_14d = sum((asof - _date(c["sold_at"])).days <= 14 for c in matched)
        if len(matched) >= 3 and recent_14d < 2:
            weak_recent_sales = True
            warnings.append(f"Item {i + 1}: doar {recent_14d} comparabile observate în ultimele 14 zile; ieșirea rapidă este neconfirmată")
        prices = [c["price_eur"] for c in matched]
        valuation = round(_lower_quantile(prices), 2) if len(prices) >= 3 else None
        q = min(identity, condition, photo, authenticity)
        comp_quality = min(len(matched) / 5, 1.0)
        confidence = round(0.7 * q + 0.3 * comp_quality, 3)
        confidence_numer += confidence * qty
        if valuation is not None:
            projected += valuation * qty
            priced_qty += qty
        else:
            warnings.append(f"Item {i + 1}: sub 3 vânzări comparabile, verificate și recente")
        if min(identity, condition, photo, authenticity) < 0.8:
            warnings.append(f"Item {i + 1}: identificarea, condiția sau autenticitatea necesită verificare")
        breakdown.append({"identity_key": item.get("identity_key"), "quantity": qty,
                          "sold_comps_count": len(matched), "observed_sold_comps_last_14d": recent_14d,
                          "sample_not_total_sales": True, "conservative_unit_resale_eur": valuation,
                          "confidence": confidence, "evidence_urls": [c["source_url"] for c in matched]})

    coverage = priced_qty / total_qty
    overall_confidence = round(confidence_numer / total_qty, 3)
    # Unknown goods carry ZERO counted resale value, not an invented estimated value.
    # For lots we are conservative; avoid relying on a tiny priced subset.
    sufficient = coverage >= (0.9 if kind in ("lot", "binder") else 1.0)
    if not sufficient:
        warnings.append("Acoperire insuficientă: valoarea produselor neidentificate nu este demonstrată")
    projected = round(projected, 2)
    net_sale = round(projected * (1 - fee / 100) - sale_extra, 2) if sufficient else None
    profit = round(net_sale - total_buy, 2) if net_sale is not None else None
    roi = round(profit / total_buy, 4) if profit is not None else None
    if material_risk:
        decision = "REJECT"
    elif roi is None:
        decision = "REVIEW"
    elif roi < min_roi:
        decision = "REJECT" if roi < 0 else "REVIEW"
        reasons.append("Marja netă nu atinge pragul de cumpărare")
    elif listing.get("costs_verified") is not True:
        decision = "REVIEW"
        warnings.append("Costurile de achiziție și revânzare nu au fost validate; valorile lipsă nu sunt presupuse zero")
    elif kind in ("lot", "binder") and listing.get("inventory_verified") is not True:
        decision = "REVIEW"
        warnings.append("Inventarul fizic/cantitățile din lot nu au fost reconciliate și validate")
    elif weak_recent_sales:
        decision = "REVIEW"
    elif overall_confidence < 0.8 or any("necesită verificare" in w for w in warnings):
        decision = "REVIEW"
    else:
        decision = "BUY_CANDIDATE"  # human approval required; never purchase automatically

    # Score only when enough comparable evidence exists. Confidence lowers the
    # score; attractive ROI cannot mask a low-confidence or contraindicated deal.
    if roi is None:
        score = None
    else:
        profitability = max(0.0, min(1.0, roi / 0.75))
        score = round(100 * (0.65 * profitability + 0.35 * overall_confidence) * coverage)
        if material_risk:
            score = min(score, 10)
        elif decision != "BUY_CANDIDATE":
            score = min(score, 59)

    return {"decision": decision, "score": score, "currency": "EUR", "kind": kind,
            "asking_eur": round(asking, 2), "acquisition_total_eur": round(total_buy, 2),
            "conservative_gross_resale_eur": projected if sufficient else None,
            "net_sale_proceeds_eur": net_sale, "net_profit_eur": profit, "roi": roi,
            "confidence": overall_confidence, "priced_quantity_coverage": round(coverage, 3),
            "reasons": reasons, "warnings": list(dict.fromkeys(warnings)),
            "items": breakdown, "asof": asof.isoformat(), "manual_approval_required": True,
            "comparable_window_days": 90, "rapid_exit_window_days": 14,
            "sampled_sales_not_market_volume": True}


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python reasoning.py listing.json")
    with open(sys.argv[1], encoding="utf-8") as f:
        print(json.dumps(evaluate_deal(json.load(f)), ensure_ascii=False, indent=2))
