"""BIGSTEN Pokémon deal discovery: official eBay Browse API -> optional image analysis.

Search broad Pokémon listings across eBay regions, including singles, slabs,
binders, lots and sealed. This is discovery, NOT a completed-sale feed or a
recommendation to buy. Authenticated API access is required; no scraping.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import email.utils
import json
import math
import os
import re
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from ebay_deletion import DeletionLedger, seller_identity

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


class EbayError(RuntimeError):
    """Sanitized upstream failure; never includes credentials or response bodies."""


class EbayBudgetError(EbayError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EbayError("eBay redirects are disabled")


def _transport(url, *, headers, data=None):
    request = urllib.request.Request(url, headers=headers, data=data)
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=25) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise EbayError("eBay response exceeds size limit")
    return json.loads(raw)


class EbayClient:
    """Official Browse client with per-instance memory token cache and call budget.

    transport(url, headers=..., data=None) returns JSON or raises HTTPError.
    Browse retries consume max_requests; OAuth attempts have a separate bounded
    counter. Environment credentials never fall back across sandbox/production.
    """

    def __init__(self, environment="sandbox", *, max_requests=20,
                 transport=None, clock=None, sleep=None):
        if environment not in ("sandbox", "production"):
            raise ValueError("Environment must be sandbox or production")
        if not isinstance(max_requests, int) or not 1 <= max_requests <= 300:
            raise ValueError("max_requests must be 1..300")
        self.environment = environment
        self.base = "https://api.sandbox.ebay.com" if environment == "sandbox" else "https://api.ebay.com"
        from local_config import load_ebay_config
        load_ebay_config()
        prefix = "EBAY_" + environment.upper()
        self._client_id = os.environ.get(prefix + "_CLIENT_ID")
        self._secret = os.environ.get(prefix + "_CLIENT_SECRET")
        if not self._client_id or not self._secret:
            raise EbayError("Set " + prefix + "_CLIENT_ID and " + prefix + "_CLIENT_SECRET")
        self.max_requests = max_requests
        self.requests_used = 0
        self.oauth_requests_used = 0
        self._transport = transport or _transport
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._token = None
        self._expires_at = 0

    def _access_token(self):
        if self._token and self._clock() < self._expires_at:
            return self._token
        if self.oauth_requests_used >= self.max_requests * 2:
            raise EbayBudgetError("eBay OAuth request budget exhausted")
        self.oauth_requests_used += 1
        basic = base64.b64encode((self._client_id + ":" + self._secret).encode()).decode()
        try:
            data = self._transport(self.base + "/identity/v1/oauth2/token", headers={
                "Authorization": "Basic " + basic,
                "Content-Type": "application/x-www-form-urlencoded"},
                data=urllib.parse.urlencode({"grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope"}).encode())
            token, expiry = data["access_token"], float(data["expires_in"])
            if not isinstance(token, str) or not token or not 0 < expiry <= 86400:
                raise ValueError()
        except Exception:
            raise EbayError("eBay OAuth authentication failed") from None
        self._token = token
        self._expires_at = self._clock() + max(0, expiry - min(60, expiry / 10))
        return token

    def _get(self, path, market):
        if market not in MARKETS:
            raise ValueError("Unsupported eBay marketplace")
        refreshed = False
        for attempt in range(3):
            if self.requests_used >= self.max_requests:
                raise EbayBudgetError("eBay Browse request budget exhausted")
            token = self._access_token()
            self.requests_used += 1
            try:
                data = self._transport(self.base + "/buy/browse/v1/" + path,
                                       headers=_headers(token, market))
                if not isinstance(data, dict) or data.get("errors"):
                    raise EbayError("eBay returned an invalid or error response")
                return data
            except urllib.error.HTTPError as error:
                if error.code == 401 and not refreshed and attempt < 2:
                    self._token = None
                    refreshed = True
                    continue
                if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    delay = 2 ** attempt
                    retry_after = None
                    try:
                        retry_after = error.headers.get("Retry-After")
                        if retry_after is not None:
                            try:
                                delay = float(retry_after)
                            except ValueError:
                                when = email.utils.parsedate_to_datetime(retry_after)
                                if when.tzinfo is None:
                                    when = when.replace(tzinfo=dt.timezone.utc)
                                delay = max(0, (when - dt.datetime.now(dt.timezone.utc)).total_seconds())
                    except (TypeError, ValueError, AttributeError):
                        pass
                    if not math.isfinite(delay) or delay < 0:
                        delay = 2 ** attempt
                    if delay > 5:
                        raise EbayError("eBay rate limit requires a later retry") from None
                    self._sleep(delay)
                    continue
                raise EbayError("eBay HTTP " + str(error.code)) from None
            except EbayError:
                raise
            except Exception:
                raise EbayError("eBay request failed") from None
        raise EbayError("eBay retry limit exceeded")

    def search(self, query, market="EBAY_GB", *, limit=20, max_pages=1,
               category_id="183454", filters="buyingOptions:{FIXED_PRICE},deliveryCountry:RO"):
        if not isinstance(query, str) or not query.strip() or len(query) > 100:
            raise ValueError("Search query must contain 1..100 characters")
        if not isinstance(limit, int) or not 1 <= limit <= 200 or not isinstance(max_pages, int) or not 1 <= max_pages <= 10:
            raise ValueError("Invalid eBay pagination limits")
        rows, seen, raw_counts = [], set(), []
        for page in range(max_pages):
            params = {"q": query, "limit": limit, "offset": page * limit, "sort": "newlyListed"}
            if category_id:
                params["category_ids"] = category_id
            if filters:
                params["filter"] = filters
            data = self._get("item_summary/search?" + urllib.parse.urlencode(params), market)
            batch = data.get("itemSummaries") or []
            if not isinstance(batch, list):
                raise EbayError("Invalid eBay search response")
            raw_counts.append(len(batch))
            for item in batch[:limit]:
                if isinstance(item, dict) and item.get("itemId") and item["itemId"] not in seen:
                    seen.add(item["itemId"])
                    rows.append(item)
            # Construct subsequent URLs ourselves, never follow an upstream URL.
            if len(batch) < limit or not data.get("next"):
                break
        return {"items": rows, "coverage": {"market": market,
                "pages_fetched": page + 1, "max_pages": max_pages,
                "raw_count": sum(raw_counts), "raw_counts_per_page": raw_counts,
                "complete": not bool(data.get("next"))}, "errors": []}

    def get_item(self, item_id, market="EBAY_GB"):
        if not isinstance(item_id, str) or not item_id or len(item_id) > 200:
            raise ValueError("Invalid eBay item ID")
        return self._get("item/" + urllib.parse.quote(item_id, safe=""), market)


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
        "seller_identity": seller_identity(item),
        "item_id": item_id,
        "source": "eBay Browse API", "marketplace": market,
        "listing_url": url, "title": str(item.get("title") or "")[:300],
        "description": "", "kind_hint": hint,
        "image_urls": images, "asking_eur": price,
        "acquisition": {"shipping_eur": shipping} if shipping is not None else {},
        "sale": {},  # seller fees/packaging not known yet
        "seller": (item.get("seller") or {}).get("username"),
        "location_country": (item.get("itemLocation") or {}).get("country"),
        "currency_original": (item.get("price") or {}).get("currency"),
        "price_original": dict(item.get("price") or {}),
        "localizedAspects": item.get("localizedAspects") or [],
        "condition": item.get("condition"),
        "conditionId": item.get("conditionId"),
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
             with_details: bool = False, environment: str | None = None,
             max_requests: int = 60, max_pages: int = 1) -> dict:
    if not 1 <= per_search <= 50 or not 1 <= max_offers <= 300:
        raise ValueError("Search limits out of range")
    if not markets or any(m not in MARKETS for m in markets):
        raise ValueError("Unsupported eBay marketplace")
    if not queries or any(
        kind not in QUERIES or not isinstance(q, list) or any(not isinstance(s, str) or not s.strip() for s in q)
        for kind, q in queries.items()
    ):
        raise ValueError("Invalid discovery categories")
    client = EbayClient(environment, max_requests=max_requests) if environment else None
    cid, secret = os.environ.get("EBAY_CLIENT_ID"), os.environ.get("EBAY_CLIENT_SECRET")
    if not client and (not cid or not secret):
        raise RuntimeError("Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET or select an environment")
    fx = parse_ecb(get(ECB))
    token = None if client else ebay_token(cid, secret)
    offers, errors, searched, coverage = {}, [], 0, []
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
                    if client:
                        found = client.search(phrase[:100], market, limit=per_search, max_pages=max_pages)
                        coverage.append(dict(found["coverage"], query=phrase))
                        data = {"itemSummaries": found["items"]}
                    else:
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
                details = client.get_item(item_id, market) if client else get_json(
                    GET_ITEM + urllib.parse.quote(item_id, safe=""), headers=_headers(token, market))
                offer["localizedAspects"] = details.get("localizedAspects") or offer["localizedAspects"]
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
        "coverage": coverage,
        "environment": environment or "legacy_production",
        "browse_requests_used": client.requests_used if client else None,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Official eBay Pokémon listing discovery")
    p.add_argument("--markets", default="EBAY_DE,EBAY_GB,EBAY_US",
                   help="Comma-separated eBay marketplace IDs")
    p.add_argument("--categories", default="graded",
                   help="Comma-separated categories")
    p.add_argument("--per-search", type=int, default=8)
    p.add_argument("--environment", choices=("sandbox", "production"), default="sandbox")
    p.add_argument("--max-requests", type=int, default=30)
    p.add_argument("--max-pages", type=int, default=1)
    p.add_argument("--max-offers", type=int, default=30)
    p.add_argument("--details", action="store_true", help="Fetch item details and additional images")
    p.add_argument("--out", default="pokemon_scan.json", help="Filename within the workspace managed export directory")
    p.add_argument("--workspace", default="private/bigsten_workspace.sqlite")
    p.add_argument("--vision-top", type=int, default=0,
                   help="Opt-in to a maximum number of AI vision calls (default zero)")
    p.add_argument("--catalog", help="Catalog JSON from catalog_export.py")
    args = p.parse_args(argv)
    ledger = DeletionLedger(args.workspace)
    epoch = ledger.epoch()
    if Path(args.out).name != args.out or not args.out.endswith('.json'):
        p.error('--out must be a JSON filename; exports are stored beside the managed workspace')
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
                      max_offers=args.max_offers, with_details=args.details,
                      environment=args.environment, max_requests=args.max_requests, max_pages=args.max_pages)
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
    output = ledger.export(args.out, result, scope=args.environment, epoch=epoch)
    print(f"Discovered {result['offers_found']} listings; vision analyzed {len(result['vision_results'])}; saved {output}")


if __name__ == "__main__":
    main()
