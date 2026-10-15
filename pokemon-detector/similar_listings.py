"""Graded-query orchestration using existing catalog, eBay and supply components.

Network is opt-in. Search hits lacking exact identity remain candidate listings;
their counts never become the exact query's physical-card inventory.
"""
import datetime as dt
import time

from graded_identity import resolve_query, metadata_prefilter
from ebay_discovery import EbayClient, EbayError, _images
from unique_supply import aggregate_supply


def search_similar(query, catalog, *, live=False, environment="sandbox",
                   markets=None, client=None):
    started = time.perf_counter()
    resolution = resolve_query(query, catalog)
    markets = markets or ["EBAY_GB", "EBAY_US", "EBAY_DE"]
    if not isinstance(markets, list) or not 1 <= len(markets) <= 3 or len(set(markets)) != len(markets) or any(m not in {"EBAY_GB", "EBAY_US", "EBAY_DE"} for m in markets):
        raise ValueError("Select distinct UK, US or Germany marketplaces")
    if environment not in {"sandbox", "production"} or not isinstance(live, bool):
        raise ValueError("Invalid search mode")
    out = {"query": resolution, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "environment": environment, "live_requested": live, "listings": [],
           "coverage": [], "errors": [], "excluded_count": 0,
           "exact_match_supply": None, "unresolved_identity_count": 0,
           "paid_ai_calls": 0, "external_api_calls": 0, "raw_listing_count": 0,
           "limitations": ["Fixed-price offers deliverable to Romania; maximum two pages per query and marketplace",
                           "Search hits require card/variant and certificate review; prices are asking prices",
                           "Not global eBay inventory; no certificate authentication or automatic image download"]}
    if not live or not resolution["queries"]:
        out["status"] = "READY_FOR_SEARCH" if resolution["queries"] else resolution["status"]
    else:
        try:
            api = client or EbayClient(environment, max_requests=12)
        except EbayError as exc:
            out["errors"].append(str(exc))
            out["status"] = "CREDENTIALS_UNAVAILABLE"
            out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            return out
        seen = {}
        for market in markets:
            for phrase in resolution["queries"][:2]:
                try:
                    result = api.search(phrase, market, limit=20, max_pages=2)
                except (EbayError, ValueError) as exc:
                    out["coverage"].append({"market": market, "query": phrase, "complete": False, "error": str(exc)})
                    out["errors"].append(str(exc))
                    continue
                out["coverage"].append({**result["coverage"], "query": phrase})
                out["raw_listing_count"] += result["coverage"].get("raw_count", len(result["items"]))
                for item in result["items"]:
                    item_id = item.get("itemId")
                    if not isinstance(item_id, str):
                        continue
                    scope = metadata_prefilter(item)
                    if scope["status"] == "EXCLUDED":
                        out["excluded_count"] += 1
                        continue
                    if item_id in seen:
                        if market not in seen[item_id]["marketplaces"]:
                            seen[item_id]["marketplaces"].append(market)
                        seen[item_id]["observations"].append({"marketplace":market,
                            "title":str(item.get("title") or "")[:300], "price":item.get("price"),
                            "query":phrase})
                        continue
                    seen[item_id] = {"item_id": item_id, "marketplace": market, "marketplaces": [market],
                                     "title": str(item.get("title") or "")[:300],
                                     "url": item.get("itemWebUrl"), "images": _images(item),
                                     "price": item.get("price"), "grading_claim": scope,
                                     "identity_status": "UNRESOLVED_SEARCH_HIT",
                                     "observations":[{"marketplace":market,"title":str(item.get("title") or "")[:300],
                                                      "price":item.get("price"),"query":phrase}],
                                     "certificate_status": "NOT_READ"}
        out["listings"] = list(seen.values())
        out["unresolved_identity_count"] = len(seen)
        out["external_api_calls"] = api.requests_used
        out["status"] = "PARTIAL_RESULTS" if out["errors"] or any(not c.get("complete") for c in out["coverage"]) else "SEARCH_HITS_REQUIRE_REVIEW"
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return out


def review_supply(listings):
    """Explicit local review input; never promote seller/OCR text automatically."""
    if not isinstance(listings, list) or len(listings) > 1000:
        raise ValueError("Supply review accepts at most 1000 listing observations")
    return aggregate_supply(listings)
