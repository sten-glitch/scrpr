"""Opt-in internal research radar importer for BIGSTEN's own detector feed.

Reads exact normalized snapshot structure from detector.py. Lowest seller ASK
versus price GUIDE is a DISCOVERY SIGNAL, not actual resale value, executable
arbitrage, verified liquidity or completed-sale comps. Never auto-buy.

Only user-authorized private/research use; commercial re-publication of
underlying Cardmarket / TCGplayer or other market data requires permission.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from workspace import WorkspaceError, WorkspaceStore

OWN_RADAR_URL = "https://sten-glitch.github.io/scrpr/data/latest.json"
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
REQUIRED_COLS = {"k", "kind", "n", "s", "no", "v", "low", "a30"}
MAX_ROWS = 250000


def _price(x):
    if isinstance(x,bool) or not isinstance(x,(float,int)):
        return None
    v=float(x)
    if not math.isfinite(v) or not .1<=v<=1000000:
        return None
    return v


def _feed_time(payload):
    raw=payload.get("generatedAt")
    if not isinstance(raw,str) or len(raw)>40:
        raise WorkspaceError("Feed missing ISO generatedAt")
    try:
        day=dt.datetime.fromisoformat(raw.replace("Z","+00:00"))
        if day.tzinfo is None:
            raise ValueError("Missing timezone")
        day=day.astimezone(dt.timezone.utc)
    except ValueError as exc:
        raise WorkspaceError("Feed generatedAt must be an ISO timestamp with timezone") from exc
    if day > dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=2):
        raise WorkspaceError("Feed cannot be dated in the future")
    return day.isoformat(timespec="minutes")


def parse_detector_feed(raw: bytes, *, limit=250):
    if not isinstance(raw,bytes) or not 1 <= len(raw) <= MAX_SNAPSHOT_BYTES:
        raise WorkspaceError("Invalid or oversized detector snapshot")
    if isinstance(limit,bool) or not 1<=limit<=500:
        raise WorkspaceError("Signal limit must be 1..500")
    try:
        data=json.loads(raw)
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise WorkspaceError("Not a detector snapshot JSON") from exc
    if not isinstance(data,dict):
        raise WorkspaceError("Snapshot root must be a JSON object")
    cols=data.get("cols")
    rows=data.get("rows")
    if (not isinstance(cols,list) or not all(isinstance(x,str) for x in cols)
            or not REQUIRED_COLS.issubset(cols) or len(cols)>60 or len(cols)!=len(set(cols))
            or not isinstance(rows,list) or len(rows)>MAX_ROWS):
        raise WorkspaceError("Invalid detector snapshot columns or row count")
    observed_at=_feed_time(data)
    now=dt.datetime.now(dt.timezone.utc)
    age_hours=round(max(0,(now-dt.datetime.fromisoformat(observed_at)).total_seconds()/3600),2)
    idx={col:i for i,col in enumerate(cols)}
    eligible=[]
    missing=0
    for raw_row in rows:
        if not isinstance(raw_row,list) or len(raw_row)!=len(cols):
            missing+=1
            continue
        def v(field):
            return raw_row[idx[field]] if field in idx else None
        if v("kind")!="single":
            continue
        low,baseline=_price(v("low")),_price(v("a30"))
        if low is None or baseline is None or low<=0 or not 3<=low<=3000:
            continue
        # Signal is a raw asking-price-vs-guide spread, NOT verified profit.
        discount=(baseline-low)/baseline
        if discount<.18 or discount> .95:
            continue
        key=v("k")
        name=v("n")
        if (not isinstance(key,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,90}",key)
                or not isinstance(name,str) or not name.strip()):
            continue
        eligible.append({
            "card_key":key,
            "card_name":name.strip()[:160],
            "card_set":str(v("s") or "")[:100],
            "card_number":str(v("no") or "")[:25],
            "variant":str(v("v") or "")[:30],
            "lowest_ask_eur":round(low,2),
            "guide_reference_eur":round(baseline,2),
            "guide_discount_pct":round(100*discount,1),
        })
    eligible.sort(key=lambda r:(-r["guide_discount_pct"],r["card_key"]))
    return {
        "source_tag":"BIGSTEN_OWN_DETECTOR_INTERNAL_GUIDE",
        "generated_at":observed_at,
        "feed_age_hours":age_hours,
        "snapshot_stale":age_hours>36,
        "snapshot_rows":len(rows),
        "eligible_signals":len(eligible),
        "discarded_malformed_rows":missing,
        "signals":eligible[:limit],
        "fingerprint":hashlib.sha256(raw).hexdigest(),
        "proof":"ASKING_VS_GUIDE_NOT_SOLD_COMPS",
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise WorkspaceError("Redirects are not permitted for the pinned detector feed")


def fetch_own_detector_feed():
    """Connect ONLY to the owner's hardcoded HTTPS GitHub Pages data URL."""
    request=urllib.request.Request(OWN_RADAR_URL,headers={
        "User-Agent":"BIGSTEN-local-owner-radar/0.1",
        "Accept":"application/json",
    })
    handler=urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(
        context=ssl.create_default_context()))
    try:
        with handler.open(request,timeout=18) as response:
            if response.status!=200:
                raise WorkspaceError("Owned radar feed returned non-200 status")
            length=response.headers.get("Content-Length")
            if length and int(length)>MAX_SNAPSHOT_BYTES:
                raise WorkspaceError("Remote feed is oversized")
            raw=response.read(MAX_SNAPSHOT_BYTES+1)
    except (urllib.error.URLError,TimeoutError,ConnectionError) as exc:
        raise WorkspaceError("Could not retrieve owned detector feed over HTTPS") from exc
    if len(raw)>MAX_SNAPSHOT_BYTES:
        raise WorkspaceError("Remote feed exceeds 32 MiB")
    return raw


def import_feed(store: WorkspaceStore, raw: bytes, *, limit=250):
    report=parse_detector_feed(raw,limit=limit)
    result=store.store_signals(report["source_tag"],report["fingerprint"],
                               report["generated_at"],report["signals"])
    return {
        "status":result["status"],"accepted":result["accepted"],
        "source":report["source_tag"],"generated_at":report["generated_at"],
        "feed_age_hours":report["feed_age_hours"],"stale":report["snapshot_stale"],
        "eligible_signals":report["eligible_signals"],
        "discarded_malformed_rows":report["discarded_malformed_rows"],
        "warning":"Asking vs guide ONLY; signal does not prove an available listing, completed sale, net ROI or commercial data redistribution rights",
        "commercial_data_rights_not_established":True,
    }


def import_local_file(store, path: str | Path, *, limit=250):
    file=Path(path).expanduser().resolve()
    if not file.is_file() or file.stat().st_size>MAX_SNAPSHOT_BYTES:
        raise WorkspaceError("Local radar snapshot missing or oversized")
    return import_feed(store,file.read_bytes(),limit=limit)
