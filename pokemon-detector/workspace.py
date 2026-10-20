"""BIGSTEN local opportunity workbench (private SQLite, no external API).

Durable local workflow: research lead -> review -> watchlist -> purchase ->
self-reported sale. Every transition is audited. A hypothetical target resale
is ALWAYS labeled a scenario, never a real completed-sale comp. All receipts,
photos, and private notes must stay in ignored private/ (never GitHub).

This is a single-user local development module. It does NOT provide SaaS
authentication, tenant isolation, payment processing or external market rights.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import sqlite3
import uuid
from contextlib import closing
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit

KINDS = {"single", "graded", "sealed", "lot", "binder"}
SOURCES = {"manual", "community", "ebay", "cardmarket", "cardtrader",
           "tcgplayer", "auction", "own_inventory", "radar_research", "other"}
STATES = {"INBOX", "REVIEW", "WATCHLIST", "DISMISSED", "PURCHASED", "SOLD", "ARCHIVED"}
NEXT_STATES = {
    "INBOX": {"REVIEW", "WATCHLIST", "DISMISSED", "ARCHIVED"},
    "REVIEW": {"WATCHLIST", "DISMISSED", "ARCHIVED"},
    "WATCHLIST": {"REVIEW", "DISMISSED", "ARCHIVED"},
    "DISMISSED": {"REVIEW", "WATCHLIST", "ARCHIVED"},
    "PURCHASED": set(),
    "SOLD": set(),
    "ARCHIVED": set(),
}
ZERO = Decimal("0.00")
MAX_AMOUNT = Decimal("1000000.00")


class WorkspaceError(ValueError):
    pass


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _text(value, label, limit=500, *, required=False):
    if not isinstance(value, str) or len(value) > limit:
        raise WorkspaceError(f"{label} must be text up to {limit} characters")
    text = value.strip()
    if required and not text:
        raise WorkspaceError(f"{label} cannot be empty")
    return text


def _money(value, name, *, positive=False):
    if isinstance(value, bool) or value is None:
        raise WorkspaceError(f"{name} must be a finite EUR amount")
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise WorkspaceError(f"{name} must be a finite EUR amount") from exc
    if not n.is_finite() or n < 0 or n > MAX_AMOUNT or (positive and n <= 0):
        raise WorkspaceError(f"{name} must be between 0 and 1,000,000 EUR")
    return n.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def _date(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise WorkspaceError(f"{name}: YYYY-MM-DD required")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise WorkspaceError(f"{name}: invalid date") from exc
    if parsed > dt.datetime.now(dt.timezone.utc).date():
        raise WorkspaceError(f"{name}: future trades cannot be marked as completed")
    return parsed


def _url(value):
    if not value:
        return ""
    value = _text(value, "source_url", 1500)
    try:
        p = urlsplit(value)
        host = p.hostname or ""
        if (p.scheme != "https" or p.username or p.password or p.fragment
                or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
                or "." not in host or host.endswith((".local", ".internal", ".test"))):
            raise WorkspaceError("source_url must be a public HTTPS source link")
    except ValueError as exc:
        raise WorkspaceError("Invalid source_url") from exc
    return value


def _as_float(money):
    return float(money.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def scenario(inputs: dict):
    """What-if model, NEVER a platform valuation or realized resale price.

    Inputs are user-entered target prices and explicit fees. Missing target
    resale or fee model => no hypothetical ROI, not an invented opportunity.
    """
    if not isinstance(inputs, dict):
        raise WorkspaceError("Scenario must be an object")
    purchase = _money(inputs.get("asking_eur"), "asking_eur", positive=True)
    target = inputs.get("target_resale_eur")
    if target in ("", None):
        return {
            "status": "UNKNOWN_NO_USER_TARGET",
            "roi": None, "net_profit_eur": None,
            "source": "USER_ASSUMPTIONS_ONLY_NOT_MARKET_EVIDENCE",
        }
    target = _money(target, "target_resale_eur", positive=True)
    extras = sum((_money(inputs.get(k, 0), k) for k in (
        "inbound_shipping_eur", "purchase_taxes_eur", "customs_eur",
        "buyer_fees_eur")), ZERO)
    sale_extras = sum((_money(inputs.get(k, 0), k) for k in (
        "outbound_shipping_eur", "packaging_eur", "other_selling_eur")), ZERO)
    fee_raw = inputs.get("selling_fee_pct", None)
    if fee_raw in (None, ""):
        return {"status": "UNKNOWN_FEE_UNSPECIFIED", "roi": None,
                "net_profit_eur": None,
                "source": "USER_ASSUMPTIONS_ONLY_NOT_MARKET_EVIDENCE"}
    fee = _money(fee_raw, "selling_fee_pct")
    if fee >= 100:
        raise WorkspaceError("Selling fee must be below 100%")
    total_buy = purchase + extras
    net_sale = target * (Decimal(1) - fee / Decimal(100)) - sale_extras
    profit = net_sale - total_buy
    roi = profit / total_buy
    breakeven = (total_buy + sale_extras) / (Decimal(1) - fee / Decimal(100))
    # Maximum item bid for a 25% ROI on stated assumptions, not fair market value.
    max_item_bid = net_sale / Decimal("1.25") - extras
    return {
        "status": "HYPOTHETICAL_ONLY",
        "source": "USER_ASSUMPTIONS_ONLY_NOT_MARKET_EVIDENCE",
        "asking_eur": _as_float(purchase),
        "target_resale_eur": _as_float(target),
        "total_buy_eur": _as_float(total_buy),
        "net_sale_eur": _as_float(net_sale),
        "net_profit_eur": _as_float(profit),
        "roi": round(float(roi), 4),
        "break_even_resale_eur": _as_float(breakeven),
        "max_item_bid_for_25pct_roi_eur": max(0.0, _as_float(max_item_bid)),
        "assumptions_not_verified": True,
        "warnings": ["Target resale price, costs and fees are user assumptions; this is NOT a verified market opportunity",
                     "No completed sales, liquidity, tax advice or guarantees were inferred"],
    }


class WorkspaceStore:
    """All methods open and explicitly close SQLite handles (Windows-safe)."""
    def __init__(self, path="private/bigsten_workspace.sqlite"):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _initialize(self):
        with closing(self._connect()) as db:
            with db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS listings (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        source TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        external_id TEXT NOT NULL DEFAULT '',
                        asking_eur REAL NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        analysis_json TEXT,
                        note TEXT NOT NULL DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS listing_by_status ON listings(status,updated_at);
                    CREATE UNIQUE INDEX IF NOT EXISTS unique_external_listing
                      ON listings(source,external_id)
                      WHERE external_id <> '';
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        listing_id TEXT NOT NULL,
                        happened_at TEXT NOT NULL,
                        action TEXT NOT NULL,
                        detail_json TEXT NOT NULL,
                        FOREIGN KEY(listing_id) REFERENCES listings(id)
                    );
                    CREATE INDEX IF NOT EXISTS event_by_listing ON events(listing_id,id);
                    CREATE TABLE IF NOT EXISTS scenarios (
                        listing_id TEXT PRIMARY KEY,
                        assumptions_json TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(listing_id) REFERENCES listings(id)
                    );
                    CREATE TABLE IF NOT EXISTS trades (
                        listing_id TEXT PRIMARY KEY,
                        purchased_at TEXT NOT NULL,
                        price_eur REAL NOT NULL,
                        acquisition_extras_eur REAL NOT NULL,
                        sold_at TEXT,
                        sale_gross_eur REAL,
                        selling_extras_eur REAL,
                        proof_reference TEXT NOT NULL DEFAULT '',
                        FOREIGN KEY(listing_id) REFERENCES listings(id)
                    );
                    CREATE TABLE IF NOT EXISTS radar_signals (
                        card_key TEXT PRIMARY KEY,
                        card_name TEXT NOT NULL,
                        card_set TEXT NOT NULL,
                        card_number TEXT NOT NULL,
                        variant TEXT NOT NULL,
                        lowest_ask_eur REAL NOT NULL,
                        guide_reference_eur REAL NOT NULL,
                        guide_discount_pct REAL NOT NULL,
                        observed_at TEXT NOT NULL,
                        source_tag TEXT NOT NULL,
                        provenance TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS feed_imports (
                        source_tag TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        imported_at TEXT NOT NULL,
                        rows_accepted INTEGER NOT NULL,
                        PRIMARY KEY(source_tag,fingerprint)
                    );
                """)

    def _event(self, db, listing_id, action, details):
        db.execute("INSERT INTO events(listing_id,happened_at,action,detail_json) VALUES (?,?,?,?)",
                   (listing_id,_now(),action,json.dumps(details,ensure_ascii=False,separators=(",",":"))))

    def create_listing(self, data: dict, *, analysis: dict | None=None):
        if not isinstance(data, dict):
            raise WorkspaceError("Expected listing object")
        title = _text(data.get("title",""),"title",300,required=True)
        description = _text(data.get("description",""),"description",1800)
        kind = data.get("kind","single")
        source = str(data.get("source","manual")).strip().lower()
        if kind not in KINDS or source not in SOURCES:
            raise WorkspaceError("Unknown listing kind/source")
        asking = _money(data.get("asking_eur"),"asking_eur",positive=True)
        source_url = _url(data.get("source_url",""))
        external = _text(data.get("external_id",""),"external_id",140)
        note = _text(data.get("note",""),"note",1000)
        if analysis is not None:
            if not isinstance(analysis,dict):
                raise WorkspaceError("Analysis must be an object")
            # Never store raw image payloads, which are transient on localhost.
            packed = json.dumps(analysis,ensure_ascii=False,allow_nan=False)
            if len(packed) > 190000:
                raise WorkspaceError("Analysis report exceeds storage limit")
            for forbidden in ('"base64":','"image_files":','"image_messages":'):
                if forbidden in packed:
                    raise WorkspaceError("Raw image content cannot be stored as listing analysis")
        else:
            packed = None
        uid = uuid.uuid4().hex
        now = _now()
        with closing(self._connect()) as db:
            try:
                with db:
                    db.execute("""INSERT INTO listings
                        (id,title,description,kind,source,source_url,external_id,asking_eur,status,created_at,updated_at,analysis_json,note)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (uid,title,description,kind,source,source_url,external,_as_float(asking),
                         "REVIEW" if analysis is not None else "INBOX",now,now,packed,note))
                    self._event(db,uid,"CREATED",{"source":source,"analysis_attached":bool(analysis)})
            except sqlite3.IntegrityError as exc:
                raise WorkspaceError("Listing already tracked from that source/external_id") from exc
        return self.get_listing(uid)

    def _get(self, db, listing_id):
        if not isinstance(listing_id,str) or not re.fullmatch(r"[0-9a-f]{32}",listing_id):
            raise WorkspaceError("Invalid listing id")
        row=db.execute("SELECT * FROM listings WHERE id=?",(listing_id,)).fetchone()
        if row is None:
            raise WorkspaceError("Listing not found")
        return row

    def get_listing(self, listing_id):
        with closing(self._connect()) as db:
            row=self._get(db,listing_id)
            result=dict(row)
            result["analysis"]=json.loads(result.pop("analysis_json")) if result["analysis_json"] else None
            scenario_row=db.execute("SELECT result_json,assumptions_json,updated_at FROM scenarios WHERE listing_id=?",(listing_id,)).fetchone()
            result["scenario"]=(dict(scenario_row) if scenario_row else None)
            if scenario_row:
                result["scenario"]={"result":json.loads(scenario_row["result_json"]),
                                     "assumptions":json.loads(scenario_row["assumptions_json"]),
                                     "updated_at":scenario_row["updated_at"]}
            trade=db.execute("SELECT * FROM trades WHERE listing_id=?",(listing_id,)).fetchone()
            result["trade"]=self._trade(dict(trade)) if trade else None
            result["events"]=[
                {"id":e["id"],"at":e["happened_at"],"action":e["action"],
                 "detail":json.loads(e["detail_json"])}
                for e in db.execute("SELECT * FROM events WHERE listing_id=? ORDER BY id DESC LIMIT 100",(listing_id,))
            ]
            return result

    def list_listings(self, status=None, *, limit=100):
        if status is not None and status not in STATES:
            raise WorkspaceError("Invalid status filter")
        if isinstance(limit,bool) or not 1 <= limit <= 300:
            raise WorkspaceError("Listing limit must be 1..300")
        query="SELECT id,title,kind,source,source_url,asking_eur,status,created_at,updated_at,note FROM listings"
        params=[]
        if status:
            query+=" WHERE status=?"
            params.append(status)
        query+=" ORDER BY updated_at DESC,id DESC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute(query,params)]

    def set_status(self, listing_id, status):
        if status not in STATES:
            raise WorkspaceError("Invalid pipeline status")
        with closing(self._connect()) as db:
            with db:
                row=self._get(db,listing_id)
                previous=row["status"]
                if status not in NEXT_STATES[previous]:
                    raise WorkspaceError(f"Transition {previous} -> {status} not allowed")
                db.execute("UPDATE listings SET status=?,updated_at=? WHERE id=?",
                           (status,_now(),listing_id))
                self._event(db,listing_id,"STATUS_CHANGED",{"from":previous,"to":status})
        return self.get_listing(listing_id)

    def save_scenario(self, listing_id, assumptions):
        if not isinstance(assumptions,dict):
            raise WorkspaceError("Scenario must be an object")
        with closing(self._connect()) as db:
            with db:
                listing=self._get(db,listing_id)
                # Never trust clients to override actual listing acquisition price.
                clean={
                    "asking_eur":listing["asking_eur"],
                    "target_resale_eur":assumptions.get("target_resale_eur"),
                }
                for k in ("inbound_shipping_eur","purchase_taxes_eur","customs_eur",
                          "buyer_fees_eur","outbound_shipping_eur","packaging_eur",
                          "other_selling_eur","selling_fee_pct"):
                    clean[k]=assumptions.get(k)  # None is unknown, not zero
                # No default-zero omissions: require explicit fees/cost values.
                if clean["target_resale_eur"] not in (None,""):
                    missing=[k for k in ("inbound_shipping_eur","purchase_taxes_eur","customs_eur",
                          "buyer_fees_eur","outbound_shipping_eur","packaging_eur",
                          "other_selling_eur","selling_fee_pct")
                          if clean[k] in (None,"")]
                    if missing:
                        raise WorkspaceError("Specify all costs explicitly (enter 0 only when known): "+", ".join(missing))
                result=scenario(clean)
                db.execute("""INSERT INTO scenarios(listing_id,assumptions_json,result_json,updated_at)
                    VALUES(?,?,?,?) ON CONFLICT(listing_id) DO UPDATE SET
                    assumptions_json=excluded.assumptions_json,result_json=excluded.result_json,
                    updated_at=excluded.updated_at""",
                    (listing_id,json.dumps(clean),json.dumps(result),_now()))
                self._event(db,listing_id,"SCENARIO_UPDATED",{"status":result["status"],
                    "roi":result["roi"],"user_assumptions_only":True})
        return self.get_listing(listing_id)

    def purchase(self, listing_id, payload):
        if not isinstance(payload,dict):
            raise WorkspaceError("Purchase must be an object")
        when=_date(payload.get("purchased_at"),"purchased_at")
        price=_money(payload.get("price_eur"),"price_eur",positive=True)
        if "acquisition_extras_eur" not in payload:
            raise WorkspaceError("Enter acquisition extras explicitly (0 if known)")
        extras=_money(payload["acquisition_extras_eur"],"acquisition_extras_eur")
        with closing(self._connect()) as db:
            with db:
                row=self._get(db,listing_id)
                if row["status"]!="WATCHLIST":
                    raise WorkspaceError("Move listing to WATCHLIST before recording a real purchase")
                db.execute("""INSERT INTO trades(listing_id,purchased_at,price_eur,acquisition_extras_eur)
                              VALUES (?,?,?,?)""",(listing_id,when.isoformat(),_as_float(price),_as_float(extras)))
                db.execute("UPDATE listings SET status='PURCHASED',updated_at=? WHERE id=?",(_now(),listing_id))
                self._event(db,listing_id,"PURCHASE_RECORDED",{
                    "date":when.isoformat(),"total_acquisition_eur":_as_float(price+extras),
                    "evidence":"USER_REPORTED_NOT_INDEPENDENTLY_VERIFIED"})
        return self.get_listing(listing_id)

    def sale(self, listing_id, payload):
        if not isinstance(payload,dict):
            raise WorkspaceError("Sale must be an object")
        day=_date(payload.get("sold_at"),"sold_at")
        gross=_money(payload.get("sale_gross_eur"),"sale_gross_eur",positive=True)
        if "selling_extras_eur" not in payload:
            raise WorkspaceError("Enter all selling costs explicitly, including 0 if known")
        fees=_money(payload["selling_extras_eur"],"selling_extras_eur")
        proof=_text(payload.get("proof_reference",""),"proof_reference",180)
        with closing(self._connect()) as db:
            with db:
                row=self._get(db,listing_id)
                if row["status"]!="PURCHASED":
                    raise WorkspaceError("Only purchased items can be marked as sold")
                trade=db.execute("SELECT purchased_at FROM trades WHERE listing_id=?",(listing_id,)).fetchone()
                if trade is None or day<dt.date.fromisoformat(trade["purchased_at"]):
                    raise WorkspaceError("Sale date must be on/after actual purchase date")
                db.execute("""UPDATE trades SET sold_at=?,sale_gross_eur=?,selling_extras_eur=?,
                              proof_reference=? WHERE listing_id=?""",
                           (day.isoformat(),_as_float(gross),_as_float(fees),proof,listing_id))
                db.execute("UPDATE listings SET status='SOLD',updated_at=? WHERE id=?",(_now(),listing_id))
                self._event(db,listing_id,"SALE_RECORDED",{
                    "date":day.isoformat(),"sale_gross_eur":_as_float(gross),
                    "provenance":"USER_REPORTED_WITH_REFERENCE" if proof else "USER_REPORTED_UNATTESTED"})
        return self.get_listing(listing_id)

    @staticmethod
    def _trade(row):
        purchase=_money(row["price_eur"],"purchase")+_money(row["acquisition_extras_eur"],"extras")
        out=dict(row)
        out["total_acquisition_eur"]=_as_float(purchase)
        out["evidence_status"]="USER_REPORTED_NOT_INDEPENDENTLY_VERIFIED"
        if row["sold_at"]:
            sale_net=_money(row["sale_gross_eur"],"sale")-_money(row["selling_extras_eur"],"fees")
            profit=sale_net-purchase
            days=(dt.date.fromisoformat(row["sold_at"])-dt.date.fromisoformat(row["purchased_at"])).days
            out.update({"net_sale_eur":_as_float(sale_net),
                        "net_profit_eur":_as_float(profit),
                        "realized_roi":round(float(profit/purchase),4),
                        "holding_days":days,"within_14_days":days<=14,
                        "evidence_status":"USER_REPORTED_WITH_REFERENCE" if row["proof_reference"]
                        else "USER_REPORTED_UNATTESTED"})
        else:
            out.update({"net_profit_eur":None,"realized_roi":None,"holding_days":None})
        return out

    def dashboard(self):
        with closing(self._connect()) as db:
            counts={row["status"]:row["n"] for row in db.execute(
                "SELECT status,COUNT(*) AS n FROM listings GROUP BY status")}
            rows=[self._trade(dict(row)) for row in db.execute("SELECT * FROM trades ORDER BY purchased_at DESC")]
            sold=[r for r in rows if r["sold_at"]]
            held=sum((r["total_acquisition_eur"] for r in rows if not r["sold_at"]),0.0)
            profit=sum((r["net_profit_eur"] for r in sold),0.0)
            source_status=list(db.execute("SELECT source_tag,MAX(imported_at) imported_at,COUNT(*) snapshots FROM feed_imports GROUP BY source_tag"))
            signals=db.execute("SELECT COUNT(*) AS n FROM radar_signals").fetchone()["n"]
        return {
            "listings_total":sum(counts.values()),
            "counts":counts,"signals_total":signals,
            "positions_open":len(rows)-len(sold),
            "position_cost_eur":round(held,2),
            "self_reported_sales":len(sold),
            "self_reported_realized_profit_eur":round(profit,2) if sold else None,
            "sources":[dict(x) for x in source_status],
            "all_results_user_reported":True,
            "no_verified_liquidity_data":True,
            "public_saas_safe":False,
        }

    def radar(self, limit=120):
        if isinstance(limit,bool) or not 1<=limit<=400:
            raise WorkspaceError("Invalid radar size")
        with closing(self._connect()) as db:
            rows=db.execute("""SELECT * FROM radar_signals
                ORDER BY guide_discount_pct DESC,card_key LIMIT ?""",(limit,)).fetchall()
            return [dict(r) for r in rows]

    def store_signals(self, source_tag, fingerprint, observed_at, rows):
        """Store guide-only signals; never auto-create purchasable listings."""
        source_tag=_text(source_tag,"source",100,required=True)
        fingerprint=_text(fingerprint,"hash",128,required=True)
        observed_at=_text(observed_at,"observed_at",80,required=True)
        if not isinstance(rows,list) or len(rows)>500:
            raise WorkspaceError("Signal import too large")
        with closing(self._connect()) as db:
            with db:
                exists=db.execute("SELECT 1 FROM feed_imports WHERE source_tag=? AND fingerprint=?",
                                  (source_tag,fingerprint)).fetchone()
                if exists:
                    return {"status":"UNCHANGED","accepted":0,"duplicates":True}
                count=0
                for r in rows:
                    if not isinstance(r,dict):
                        continue
                    if not (r.get("card_key") and r.get("card_name")):
                        continue
                    db.execute("""INSERT INTO radar_signals
                      (card_key,card_name,card_set,card_number,variant,lowest_ask_eur,
                       guide_reference_eur,guide_discount_pct,observed_at,source_tag,provenance)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(card_key) DO UPDATE SET
                       card_name=excluded.card_name,card_set=excluded.card_set,
                       card_number=excluded.card_number,variant=excluded.variant,
                       lowest_ask_eur=excluded.lowest_ask_eur,
                       guide_reference_eur=excluded.guide_reference_eur,
                       guide_discount_pct=excluded.guide_discount_pct,
                       observed_at=excluded.observed_at,source_tag=excluded.source_tag,
                       provenance=excluded.provenance""",
                       (r["card_key"],r["card_name"],r.get("card_set",""),
                        r.get("card_number",""),r.get("variant",""),
                        r["lowest_ask_eur"],r["guide_reference_eur"],
                        r["guide_discount_pct"],observed_at,source_tag,
                        "ASKING_VS_GUIDE_ONLY_NOT_COMPLETED_SALES"))
                    count+=1
                db.execute("INSERT INTO feed_imports VALUES(?,?,?,?,?)",
                           (source_tag,fingerprint,observed_at,_now(),count))
        return {"status":"IMPORTED_GUIDE_ONLY","accepted":count,
                "is_real_sale_evidence":False,"duplicates":False}

    def export(self):
        with closing(self._connect()) as db:
            ids=[r["id"] for r in db.execute("SELECT id FROM listings ORDER BY created_at LIMIT 300")]
        return {"exported_at":_now(),"private_local_workspace":True,
                "listings":[self.get_listing(i) for i in ids],
                "dashboard":self.dashboard(),
                "radar":self.radar(limit=400)}
