"""BIGSTEN Pokémon deal discovery: official eBay Browse API -> optional image analysis.

Search broad Pokémon listings across eBay regions, including singles, slabs,
binders, lots and sealed. This is discovery, NOT a completed-sale feed or a
recommendation to buy. Authenticated API access is required; no scraping.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import urllib.parse
from pathlib import Path

from detector import EBAY_MARKETS, EBAY_CTX, EBAY_SEARCH, ECB, ebay_token, get, get_json, parse_ecb, to_eur
from vision import MAX_IMAGES, VisionError, analyze_listing, validate_image_url

QUERIES = {
    "single": ["pokemon card rare holo", "pokemon charizard card"],
    "graded": ["pokemon PSA 10 card", "pokemon CGC graded"],
    "binder": ["pokemon binder collection", "pokemon binder cards"],
    "lot": ["pokemon card lot", "pokemon card collection"],
    "sealed": ["pokemon booster box sealed", "pokemon elite trainer box sealed"],
}
GET_ITEM = "https://api.ebay.com/buy/browse/v1/item/"
MARKETS = tuple(EBAY_MARKETS.keys())


def _images(item: dict) -> list[str]:
    candidates = []
    for key in ("image", "thumbnailImages"):
        v = item.get(key)
        if isinstance(v, dict):
            candidates.append(v.get("imageUrl"))
        elif isinstance(v, list):
            candidates.extend(t.get("imageUrl") for t in v if isinstance(t, dict))
    candidates.extend(t.get("imageUrl") for t in item.get("additionalImages", []) if isinstance(t, dict))
    urls = []
    for url in candidates:
        if not isinstance(url, str) or url in urls:
            continue
        try:
            urls.append(validate_image_url(url))
        except VisionError:
            continue
    return urls[:MAX_IMAGES]


def _money(data: dict | None, fx: dict) -> float | None:
    if not isinstance(data, dict):
        return None
    try:
        num = float(data["value"])
        if not 0 <= num < 1_000_000:
            return None
        ans = to_eur(num, data.get("currency"), fx)
        return round(ans, 2) if ans is not None else None
    except (TypeError, ValueError, KeyError):
        return None


def listing_from_ebay(item: dict, market: str, hint: str, fx: dict) -> dict | None:
    """Normalize only sourced fields; unknown costs must remain unknown."""
    item_id = item.get("itemId")
    price = _money(item.get("price"), fx)
    images = _images(item)
    url = item.get("itemWebUrl")
    if not item_id or price is None or price <= 0 or not url or not images:
        return None
    # Do not invent shipping when not provided for delivery to Romania.
    shipping = None
    for opt in item.get("shippingOptions") or []:
        if not isinstance(opt, dict):
            continue
        shipping = _money(opt.get("shippingCost"), fx)
        if shipping is not None:
            break
    listing = {
        "listing_id": f"ebay:{market}:{item_id}",
        "source": "eBay Browse API", "marketplace": market,
        "listing_url": url, "title": str(item.get("title") or "")[:300],
        "description": "", "kind_hint": hint,
        "image_urls": images, "asking_eur": price,
        "acquisition": {"shipping_eur": shipping} if shipping is not None else {},
        "sale": {},  # seller fees/packaging not known yet
        "seller": (item.get("seller") or {}).get("username"),
        "location_country": (item.get("itemLocation") or {}).get("country"),
        "currency_original": (item.get("price") or {}).get("currency"),
        "shipping_verified": shipping is not None,
        "costs_verified": False,
    }
    return listing


def _headers(token: str, market: str) -> dict:
    return {"Authorization": "Bearer " + token,
            "X-EBAY-C-MARKETPLACE-ID": market,
            "X-EBAY-C-ENDUSERCTX": EBAY_CTX}


def discover(queries: dict[str, list[str]], markets: list[str], *,
             per_search: int = 8, max_offers: int = 60,
             with_details: bool = False) -> dict:
    if not 1 <= per_search <= 50 or not 1 <= max_offers <= 300:
        raise ValueError("Search limits out of range")
    if not markets or any(m not in MARKETS for m in markets):
        raise ValueError("Unsupported eBay marketplace")
    if not queries or any(
        kind not in QUERIES or not isinstance(q, list) or any(not isinstance(s, str) or not s.strip() for s in q)
        for kind, q in queries.items()
    ):
        raise ValueError("Invalid discovery categories")
    cid, secret = os.environ.get("EBAY_CLIENT_ID"), os.environ.get("EBAY_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET")
    fx = parse_ecb(get(ECB))
    token = ebay_token(cid, secret)
    offers, errors, searched = {}, [], 0
    for market in markets:
        for hint, phrases in queries.items():
            for phrase in phrases:
                params = urllib.parse.urlencode({
                    "q": phrase[:100],
                    "category_ids": "183454",
                    "sort": "newlyListed", "limit": str(per_search),
                    "filter": "buyingOptions:{FIXED_PRICE},deliveryCountry:RO",
                })
                try:
                    data = get_json(EBAY_SEARCH + "?" + params, headers=_headers(token, market))
                    searched += 1
                except Exception as err:
                    errors.append({"market": market, "query": phrase, "error_type": type(err).__name__})
                    continue
                for item in data.get("itemSummaries") or []:
                    offer = listing_from_ebay(item, market, hint, fx)
                    if offer and offer["listing_id"] not in offers:
                        offers[offer["listing_id"]] = offer
                    if len(offers) >= max_offers:
                        break
                if len(offers) >= max_offers:
                    break
            if len(offers) >= max_offers:
                break
        if len(offers) >= max_offers:
            break
    rows = list(offers.values())
    # Fetch full listing images only when explicitly requested, bounded by max_offers.
    if with_details:
        for offer in rows:
            market, item_id = offer["marketplace"], offer["listing_id"].split(":", 2)[2]
            try:
                details = get_json(GET_ITEM + urllib.parse.quote(item_id, safe=""),
                                   headers=_headers(token, market))
                if _images(details):
                    offer["image_urls"] = list(dict.fromkeys(
                        _images(details) + offer["image_urls"]))[:MAX_IMAGES]
                offer["description"] = re.sub(r"<[^>]*>", " ", str(details.get("description") or ""))[:1500]
            except Exception as err:
                errors.append({"market": market, "item_id": item_id, "error_type": type(err).__name__})
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sources": ["eBay Browse API"], "regions": markets, "queries_executed": searched,
        "offers_found": len(rows), "errors": errors, "offers": rows,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Official eBay Pokémon listing discovery")
    p.add_argument("--markets", default="EBAY_DE,EBAY_GB,EBAY_US",
                   help="Comma-separated eBay marketplace IDs")
    p.add_argument("--categories", default="single,graded,binder,lot,sealed",
                   help="Comma-separated categories")
    p.add_argument("--per-search", type=int, default=8)
    p.add_argument("--max-offers", type=int, default=30)
    p.add_argument("--details", action="store_true", help="Fetch item details and additional images")
    p.add_argument("--out", default="pokemon_scan.json")
    p.add_argument("--vision-top", type=int, default=0,
                   help="Opt-in to a maximum number of AI vision calls (default zero)")
    p.add_argument("--catalog", help="Catalog JSON from catalog_export.py")
    args = p.parse_args(argv)
    markets = [v.strip() for v in args.markets.split(",") if v.strip()]
    cats = [v.strip() for v in args.categories.split(",") if v.strip()]
    if any(c not in QUERIES for c in cats):
        p.error("Unsupported categories")
    if args.vision_top < 0 or args.vision_top > 10:
        p.error("--vision-top must be 0..10 to cap model costs")
    if args.vision_top and not args.details:
        p.error("--vision-top requires --details for useful photo coverage")
    catalog = []
    if args.catalog:
        catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    result = discover({c: QUERIES[c] for c in cats}, markets, per_search=args.per_search,
                      max_offers=args.max_offers, with_details=args.details)
    result["vision_results"] = []
    for offer in result["offers"][:args.vision_top]:
        try:
            out = analyze_listing(offer, catalog)
            result["vision_results"].append(out)
        except Exception as err:
            result["vision_results"].append({
                "listing_id": offer["listing_id"],
                "error_type": type(err).__name__,
                "note": "Vision failed; no investment conclusion was produced",
            })
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Discovered {result['offers_found']} listings; vision analyzed {len(result['vision_results'])}; saved {output}")


if __name__ == "__main__":
    main()
