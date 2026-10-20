"""BIGSTEN Flip Outcome Audit — offline, point-in-time verification of forecasts.

Computes forecast vs realized performance ONLY on privately documented,
actually executed and closed purchases. Keeps open/unsold inventory in the
denominator of exit-speed metrics; never silently drops it to advertise ROI.

Predictions must be snapshots taken before the purchase. No market calls,
no scraped "sold" listings, no generated facts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import statistics
from pathlib import Path


class BacktestError(ValueError):
    pass


def _day(value, field):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError()
        return dt.date.fromisoformat(value)
    except ValueError:
        raise BacktestError(f"{field}: expected YYYY-MM-DD")


def _finite(value, field, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BacktestError(f"{field}: numeric finite value required")
    if (positive and value <= 0) or (not positive and value < 0):
        raise BacktestError(f"{field}: positive or non-negative amount required")
    return float(value)


def _rate(n, d):
    return round(n / d, 4) if d else None


def audit_outcomes(data: list[dict], *, asof: dt.date | None = None, horizon_days: int = 14,
                   target_roi: float = .25) -> dict:
    """Evaluate selected acquisitions, not a market-wide trading strategy.

    Records must include each forecast even if no purchase was made. For
    purchases still in inventory, there is NO realized sale price or realized
    ROI; exits are unresolved, including those past holding horizon.
    """
    asof = asof or dt.datetime.now(dt.timezone.utc).date()
    if not isinstance(data, list) or not data:
        raise BacktestError("Expected nonempty historical deal records")
    if isinstance(horizon_days, bool) or not 1 <= horizon_days <= 365:
        raise BacktestError("horizon_days must be 1..365")
    if not isinstance(target_roi, (int, float)) or not 0 <= target_roi <= 10:
        raise BacktestError("target_roi must be in 0..10")
    ids = set()
    rows = []
    purchased = closed = on_time = overdue = 0
    forecast_error = []
    closed_returns = []
    closed_positive = 0
    closed_target = 0
    closed_candidates = 0
    winning_candidates = 0
    for i, case in enumerate(data):
        if not isinstance(case, dict):
            raise BacktestError(f"Record {i + 1} must be an object")
        deal_id = case.get("deal_id")
        if not isinstance(deal_id, str) or not deal_id.strip() or deal_id in ids:
            raise BacktestError("Every forecast needs unique nonempty deal_id")
        ids.add(deal_id)
        forecast_at = _day(case.get("forecast_at"), "forecast_at")
        if forecast_at > asof:
            raise BacktestError("Forecast cannot be in the future")
        decision = case.get("decision")
        if decision not in {"BUY_CANDIDATE", "REVIEW", "REJECT"}:
            raise BacktestError("Unknown forecast decision")
        roi_est = case.get("forecast_roi")
        if roi_est is not None:
            if isinstance(roi_est, bool) or not isinstance(roi_est, (int, float)) or not math.isfinite(roi_est) or not -1 <= roi_est <= 20:
                raise BacktestError("Invalid forecast_roi")
        bought_at = case.get("bought_at")
        closed_at = case.get("closed_at")
        row = {"deal_id": deal_id, "forecast_decision": decision,
               "forecast_roi": roi_est, "state": "not_purchased",
               "realized_roi": None, "days_to_exit": None}
        if bought_at is None:
            if closed_at is not None or case.get("purchase_cost_eur") is not None or case.get("net_sale_eur") is not None:
                raise BacktestError("Unbought deal cannot have a closed trade")
            rows.append(row)
            continue
        buy_date = _day(bought_at, "bought_at")
        if not forecast_at <= buy_date <= asof:
            raise BacktestError("Purchase date must follow forecast")
        if case.get("purchase_reviewed") is not True or not case.get("purchase_proof_reference"):
            raise BacktestError("Acquisition must be verified against purchase evidence")
        purchase = _finite(case.get("purchase_cost_eur"), "purchase_cost_eur", positive=True)
        purchased += 1
        elapsed = (asof - buy_date).days
        if closed_at is None:
            if case.get("net_sale_eur") is not None or case.get("sale_reviewed"):
                raise BacktestError("Unsold inventory cannot have realized proceeds")
            row["state"] = "open_overdue" if elapsed > horizon_days else "open_within_horizon"
            if elapsed > horizon_days:
                overdue += 1
            rows.append(row)
            continue
        close_date = _day(closed_at, "closed_at")
        if not buy_date <= close_date <= asof:
            raise BacktestError("Sale date must follow acquisition")
        if case.get("sale_reviewed") is not True or not case.get("sale_proof_reference"):
            raise BacktestError("Closed sale requires reviewed evidence")
        proceeds = _finite(case.get("net_sale_eur"), "net_sale_eur")
        roi = (proceeds - purchase) / purchase
        days_to_exit = (close_date - buy_date).days
        closed += 1
        closed_returns.append(roi)
        if days_to_exit <= horizon_days:
            on_time += 1
        if roi > 0:
            closed_positive += 1
        if roi >= target_roi:
            closed_target += 1
        if roi_est is not None:
            forecast_error.append(roi - roi_est)
        if decision == "BUY_CANDIDATE":
            closed_candidates += 1
            winning_candidates += int(roi >= target_roi)
        row.update(state="closed", realized_roi=round(roi, 4),
                   days_to_exit=days_to_exit)
        rows.append(row)
    return {
        "status": "HISTORICAL_OUTCOME_AUDIT_NOT_LIVE_PERFORMANCE",
        "asof": asof.isoformat(), "horizon_days": horizon_days,
        "target_roi": target_roi, "forecast_count": len(rows),
        "purchases_executed": purchased, "closed_trades": closed,
        "open_trades": purchased - closed, "open_overdue": overdue,
        "closed_within_horizon": on_time,
        "observed_exit_within_horizon_of_all_purchases": _rate(on_time, purchased),
        "realized_roi_mean_on_closed_only": round(statistics.mean(closed_returns), 4) if closed_returns else None,
        "realized_roi_median_on_closed_only": round(statistics.median(closed_returns), 4) if closed_returns else None,
        "profitable_closed_rate": _rate(closed_positive, closed),
        "target_roi_hit_rate_on_closed": _rate(closed_target, closed),
        "buy_candidate_target_precision_on_executed_closed": _rate(winning_candidates, closed_candidates),
        "forecast_roi_mean_error_realized_minus_predicted": (
            round(statistics.mean(forecast_error), 4) if forecast_error else None),
        "forecast_roi_mae_on_closed": (
            round(statistics.mean(abs(x) for x in forecast_error), 4) if forecast_error else None),
        "records": rows,
        "limitations": [
            "No investment success claims until real purchase and sale evidence is reviewed",
            "Closed-trade ROI excludes unsold inventory; reporting both prevents hiding unclosed positions",
            "ROI forecast error uses only trades actually bought and closed: selection bias remains",
            "An unsold item might later sell at a different price, or not sell at all",
            "No tax, capital allocation, or unpurchased opportunity performance can be inferred from this dataset",
        ],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare historic BIGSTEN forecasts to verified realized flips")
    ap.add_argument("history_json", help="JSON array of forecast/purchase/outcome records")
    ap.add_argument("--asof", help="Reference date YYYY-MM-DD")
    ap.add_argument("--out", default="flip_outcomes_report.json")
    ap.add_argument("--horizon-days", type=int, default=14)
    ap.add_argument("--target-roi", type=float, default=.25)
    args = ap.parse_args(argv)
    source = json.loads(Path(args.history_json).read_text(encoding="utf-8"))
    result = audit_outcomes(source, asof=_day(args.asof, "asof") if args.asof else None,
                            horizon_days=args.horizon_days, target_roi=args.target_roi)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Audited {result['forecast_count']} forecasts, {result['purchases_executed']} purchases, "
          f"{result['closed_trades']} closed trades. Report: {args.out}")


if __name__ == "__main__":
    main()
