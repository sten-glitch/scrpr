#!/usr/bin/env python3
"""Detector Pokémon — daily multi-market price build (stdlib only).

Sources, all official or public feeds (no scraping):
  EU  Cardmarket public price guide + catalogs (daily files, no key)
  EU  CardTrader API v2 (optional, CARDTRADER_TOKEN)
  EU/UK/US eBay Browse API, active fixed-price listings (optional, EBAY_CLIENT_ID + EBAY_CLIENT_SECRET)
  US  TCGplayer market prices via tcgcsv.com (daily dump, no key)
  IDs TCGdex cards-database (GitHub, MIT): links one card across all markets
Writes <out>/latest.json, <out>/history.json and <history>/<YYYY-MM-DD>.json.
"""
import argparse, base64, datetime as dt, gzip, json, os, re, statistics, sys, time
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = 'pokemon-detector/1.0 (personal daily price tracker; GitHub Actions)'
CM = 'https://downloads.s3.cardmarket.com/productCatalog'
TCGCSV = 'https://tcgcsv.com/tcgplayer/3'
ECB = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
EBAY_TOKEN = 'https://api.ebay.com/identity/v1/oauth2/token'
EBAY_SEARCH = 'https://api.ebay.com/buy/browse/v1/item_summary/search'
EBAY_MARKETS = {'EBAY_DE': 'EUR', 'EBAY_FR': 'EUR', 'EBAY_IT': 'EUR', 'EBAY_ES': 'EUR', 'EBAY_GB': 'GBP', 'EBAY_US': 'USD'}
EBAY_CTX = 'contextualLocation=country%3DRO%2Czip%3D010011'  # prices and shipping as seen from Bucharest
CT = 'https://api.cardtrader.com/api/v2'

EU = set('AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE'.split())
VAT_RO = 0.21
LOW_VALUE_DUTY = 3.0        # EU flat duty per tariff line on parcels <= €150, from 1.7.2026
RO_LOGISTICS_RON = 25.0     # Romanian fee per non-EU parcel <= €150, from 1.1.2026
DUTY_OVER_150 = 0.027       # shortcut: 9504 40 rate assumed, unverified in TARIC; check before large imports
BROKER_OVER_150 = 15.0      # shortcut: courier customs brokerage estimate
SHIP_GUESS = {'EU': 6.0, 'GB': 8.0, 'US': 15.0, 'OTHER': 15.0}  # used only when eBay omits shipping
BAD_TITLE = re.compile(r'\b(psa|bgs|cgc|sgc|graded|gradiert|slab|proxy|custom|orica|replica|fake|lot|bundle|playset|'
                       r'japan(ese)?|jpn|jap|korean|kor|chinese|chn|simplified|digital|code card|empty|'
                       r'deutsch|german|fran[cç]ais|french|italiano|italian|espa[nñ]ol|spanish|portugu[eê]s)\b', re.I)  # keep English copies only


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- http
def get(url, headers=None, data=None, tries=4, timeout=120):
    h = {'User-Agent': UA, 'Accept-Encoding': 'gzip', **(headers or {})}
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
                b = r.read()
                return gzip.decompress(b) if r.headers.get('Content-Encoding') == 'gzip' else b
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
            time.sleep(int(e.headers.get('Retry-After') or 0) or 3 * (i + 1))
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def get_json(url, **kw):
    return json.loads(get(url, **kw))


# ---------------------------------------------------------------- FX
def parse_ecb(xml_bytes):
    rates = {'EUR': 1.0}
    for el in ET.fromstring(xml_bytes).iter():
        if el.get('currency') and el.get('rate'):
            rates[el.get('currency')] = float(el.get('rate'))
    return rates


def to_eur(value, cur, fx):
    return None if value is None or cur not in fx else float(value) / fx[cur]


# ---------------------------------------------------------------- TCGdex mapping
def _str(key, s):
    for q in ('"', "'"):
        m = re.search(r'\b' + key + r'\s*:\s*' + q + r'((?:[^' + q + r'\\]|\\.)*)' + q, s)
        if m:
            return m.group(1).replace('\\' + q, q)
    return None


def _block(s, key, opener='{'):
    """Text of the first balanced `key: {...}` (or [...]) block, else None."""
    m = re.search(r'\b' + key + r'\s*:\s*(\S)', s)
    if not m or m.group(1) != opener:
        return None
    close = '}' if opener == '{' else ']'
    depth, start = 0, m.start(1)
    for k in range(start, len(s)):
        depth += s[k] == opener
        depth -= s[k] == close
        if depth == 0:
            return s[start:k + 1]
    return None


def _ids(block):
    out = {}
    for k in ('cardmarket', 'tcgplayer', 'cardtrader'):
        m = re.search(k + r'\s*:\s*(\d+)', block or '')
        out[k] = int(m.group(1)) if m else None
    return out


def parse_set(text):
    name = _block(text, 'name')
    count = _block(text, 'cardCount')
    abbr = _block(text, 'abbreviations')
    m = re.search(r'official\s*:\s*(\d+)', count or '')
    return {'id': _str('id', text), 'name': _str('en', name or '') or _str('id', text),
            'official': int(m.group(1)) if m else None, 'code': _str('official', abbr or ''),
            **{'cm_' + k: v for k, v in _ids(_block(text, 'thirdParty')).items()}}


def parse_card(text):
    """-> (english name, rarity, [(variant type, ids)])"""
    name = _str('en', _block(text, 'name') or '')
    variants = _block(text, 'variants', '[')
    out = []
    if variants:
        depth, start = 0, None
        for k, ch in enumerate(variants):
            if ch == '{':
                start = k if depth == 0 else start
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    obj = variants[start:k + 1]
                    tp = _block(obj, 'thirdParty')
                    if tp:
                        out.append((_str('type', obj) or 'normal', _ids(tp)))
        text = text.replace(variants, '')
    if not out:
        tp = _block(text, 'thirdParty')
        if tp:  # older cards: one id pair for the card; Cardmarket keeps reverse holo in its -holo fields
            ids = _ids(tp)
            out = [('normal', ids), ('reverse', ids)]
    return name, _str('rarity', text), out


TP_SUB = {'normal': ['Normal', 'Holofoil'], 'holo': ['Holofoil', 'Normal'], 'reverse': ['Reverse Holofoil']}


def load_tcgdex(root):
    """Map (cardmarket idProduct, price suffix) -> card identity. Also cardmarket idExpansion -> set."""
    root = Path(root)
    series, sets, cards = {}, {}, {}
    for p in root.glob('*.ts'):
        series[p.stem] = _str('id', p.read_text(encoding='utf8'))
    for p in root.glob('*/*.ts'):
        sets[(p.parent.name, p.stem)] = parse_set(p.read_text(encoding='utf8'))
    for p in sorted(root.glob('*/*/*.ts')):
        st = sets.get((p.parent.parent.name, p.parent.name))
        if not st:
            continue
        name, rarity, variants = parse_card(p.read_text(encoding='utf8'))
        local = p.stem
        num = f'{local}/{st["official"]}' if st['official'] and re.fullmatch(r'\d+', local) else local
        for vtype, ids in variants:
            if not ids.get('cardmarket'):
                continue
            key = (ids['cardmarket'], '-holo' if vtype == 'reverse' else '')
            cards.setdefault(key, {
                'name': name, 'set': st['name'], 'code': st['code'], 'local': local, 'no': num, 'rarity': rarity,
                'tp': ids['tcgplayer'], 'tp_sub': TP_SUB.get(vtype, ['Normal', 'Holofoil']), 'ct': ids['cardtrader'],
                'tp_group': st['cm_tcgplayer'],
                'img': f'https://assets.tcgdex.net/en/{series.get(p.parent.parent.name)}/{st["id"]}/{local}/high.webp'})
    exp = {s['cm_cardmarket']: s['name'] for s in sets.values() if s['cm_cardmarket']}
    return cards, exp


# ---------------------------------------------------------------- Cardmarket rows
def _v(x):
    return x if isinstance(x, (int, float)) and x > 0 else None


def build_rows(prices, singles, sealed, cards, exp):
    pg = {g['idProduct']: g for g in prices['priceGuides']}
    rows = []
    for p in singles['products']:
        g = pg.get(p['idProduct'])
        if not g:
            continue
        for sfx, variant in (('', 'Normal'), ('-holo', 'Reverse Holo')):
            trend = _v(g.get('trend' + sfx))
            if trend is None or trend < 2:  # under €2 is noise for investing
                continue
            c = cards.get((p['idProduct'], sfx), {})
            rows.append({
                'k': f"{p['idProduct']}{'h' if sfx else ''}", 'id': p['idProduct'], 'kind': 'single',
                'n': c.get('name') or p['name'], 's': c.get('set') or exp.get(p['idExpansion']) or f"Expansiunea #{p['idExpansion']}",
                'no': c.get('no'), 'v': variant, 'img': c.get('img'),
                'avg': _v(g.get('avg' + sfx)), 'low': _v(g.get('low' + sfx)), 'tr': trend,
                'a1': _v(g.get('avg1' + sfx)), 'a7': _v(g.get('avg7' + sfx)), 'a30': _v(g.get('avg30' + sfx)),
                '_c': c})
    for p in (sealed or {}).get('products', []):
        g = pg.get(p['idProduct'])
        trend = _v(g and g.get('trend'))
        if trend is None or trend < 2:
            continue
        rows.append({'k': str(p['idProduct']), 'id': p['idProduct'], 'kind': 'sealed', 'n': p['name'],
                     's': exp.get(p['idExpansion']) or p.get('categoryName', ''), 'no': None, 'v': 'Sigilat', 'img': None,
                     'avg': _v(g.get('avg')), 'low': _v(g.get('low')), 'tr': trend, 'a1': None, 'a7': None, 'a30': None, '_c': {}})
    return rows


def metrics(r, fee=5.0, ship=3.0):
    """Same formulas as the page (docs/index.html), used here to pick which cards get eBay/CardTrader lookups."""
    liq = 3 if r['a1'] else 2 if r['a7'] else 1 if r['a30'] else 0
    mom = r['a7'] / r['a30'] - 1 if r['a7'] and r['a30'] else None
    acc = r['a1'] / r['a7'] - 1 if r['a1'] and r['a7'] else None
    ref = min(r['tr'], r['a7'] or r['tr'])
    roi = (ref * (1 - fee / 100) - 1) / (r['low'] + ship) - 1 if r['low'] else None
    suspect = bool(r['low'] and r['low'] < 0.25 * ref)
    clamp = lambda x, a, b: max(a, min(b, x))
    score = clamp(40 * (0 if suspect else clamp(roi or 0, 0, 1)) + 30 * clamp((mom or 0) / 0.4, -1, 1)
                  + 15 * clamp((acc or 0) / 0.3, -1, 1) + 15 * liq / 3, 0, 100)
    return {'liq': liq, 'mom': mom, 'acc': acc, 'ref': ref, 'roi': roi, 'suspect': suspect, 'score': score}


def pick_candidates(rows, n_score=100, n_mom=50, lo=20, hi=2000):
    pool = [r for r in rows if r['kind'] == 'single' and r['no'] and r['_c'].get('name') and lo <= r['tr'] <= hi]
    for r in pool:
        r['_m'] = metrics(r)
    pool = [r for r in pool if r['_m']['liq'] >= 2]
    top = sorted(pool, key=lambda r: -r['_m']['score'])[:n_score]
    mom = sorted([r for r in pool if (r['_m']['mom'] or 0) >= 0.1], key=lambda r: -r['_m']['mom'])[:n_mom]
    seen, out = set(), []
    for r in top + mom:
        if r['k'] not in seen:
            seen.add(r['k'])
            out.append(r)
    return out


# ---------------------------------------------------------------- US: TCGplayer via tcgcsv
def tcgplayer_prices(groups, sleep=0.2):
    """-> {(productId, subTypeName): {'market':, 'low':}} in USD"""
    out = {}
    for gid in sorted(groups):
        try:
            res = get_json(f'{TCGCSV}/{gid}/prices').get('results') or []
        except Exception as e:  # one missing group must not stop the run
            log(f'  tcgcsv group {gid}: {e}')
            continue
        for x in res:
            out[(x['productId'], x.get('subTypeName'))] = {'market': x.get('marketPrice'), 'low': x.get('lowPrice')}
        time.sleep(sleep)
    return out


def us_price(c, tp, fx):
    for sub in c.get('tp_sub') or []:
        p = tp.get((c.get('tp'), sub))
        if p and (p['market'] or p['low']):
            return to_eur(p['market'] or p['low'], 'USD', fx)
    return None


# ---------------------------------------------------------------- landed cost into Romania
def landed_eur(item_eur, ship_eur, origin, fx):
    base = item_eur + ship_eur
    if origin in EU:
        return base
    if base <= 150:
        return (base + LOW_VALUE_DUTY) * (1 + VAT_RO) + RO_LOGISTICS_RON / fx.get('RON', 5.0)
    duty = base * DUTY_OVER_150
    return (base + duty) * (1 + VAT_RO) + BROKER_OVER_150


def _origin_group(c):
    return 'EU' if c in EU else c if c in ('GB', 'US') else 'OTHER'


# ---------------------------------------------------------------- eBay (official Browse API)
def ebay_token(cid, secret):
    basic = base64.b64encode(f'{cid}:{secret}'.encode()).decode()
    body = urllib.parse.urlencode({'grant_type': 'client_credentials', 'scope': 'https://api.ebay.com/oauth/api_scope'}).encode()
    return get_json(EBAY_TOKEN, data=body, headers={'Authorization': 'Basic ' + basic,
                                                     'Content-Type': 'application/x-www-form-urlencoded'})['access_token']


def number_re(c):
    local = c['local']
    if re.fullmatch(r'\d+', local) and '/' in (c['no'] or ''):
        official = c['no'].split('/')[1]
        return re.compile(r'(?<!\d)0*' + str(int(local)) + r'\s*/\s*0*' + official + r'(?!\d)')
    return re.compile(r'(?<![A-Za-z0-9])' + re.escape(local) + r'(?![A-Za-z0-9])', re.I)


def ebay_offers(items, c, fx):
    """Filter one search page to genuine raw single-card listings; -> offers sorted by landed EUR."""
    nre, out = number_re(c), []
    for it in items:
        title = it.get('title') or ''
        if BAD_TITLE.search(title) or not nre.search(title):
            continue
        price = it.get('price') or {}
        p = to_eur(price.get('value'), price.get('currency'), fx)
        if p is None:
            continue
        origin = ((it.get('itemLocation') or {}).get('country') or '').upper()
        sc = ((it.get('shippingOptions') or [{}])[0] or {}).get('shippingCost')
        ship = to_eur(sc.get('value'), sc.get('currency'), fx) if sc else None
        guessed = ship is None
        ship = SHIP_GUESS[_origin_group(origin)] if guessed else ship
        out.append({'landed': round(landed_eur(p, ship, origin, fx), 2), 'item': round(p, 2), 'ship': round(ship, 2),
                    'shipGuess': guessed, 'from': origin, 'url': it.get('itemWebUrl'), 'title': title[:120]})
    return sorted(out, key=lambda o: o['landed'])


def ebay_lookup(cands, fx, cid, secret):
    tok, calls, errors = ebay_token(cid, secret), 0, 0
    for r in cands:
        c, best, asks = r['_c'], None, []
        for market, cur in EBAY_MARKETS.items():
            lo = round(0.4 * r['tr'] * fx.get(cur, 1), 2)  # drop junk/fakes server-side
            q = urllib.parse.urlencode({'q': f"{c['name']} {c['no']}"[:100], 'category_ids': '183454', 'sort': 'price', 'limit': '50',
                                        'filter': f'buyingOptions:{{FIXED_PRICE}},deliveryCountry:RO,price:[{lo}..],priceCurrency:{cur}'})
            try:
                data = get_json(f'{EBAY_SEARCH}?{q}', headers={'Authorization': 'Bearer ' + tok,
                                                               'X-EBAY-C-MARKETPLACE-ID': market, 'X-EBAY-C-ENDUSERCTX': EBAY_CTX})
                calls += 1
            except Exception as e:
                errors += 1
                log(f'  eBay {market} {c["name"]} {c["no"]}: {e}')
                continue
            offers = ebay_offers(data.get('itemSummaries') or [], c, fx)
            for o in offers:
                o['m'] = market
            asks += [o['item'] for o in offers[:5]]
            if offers and (best is None or offers[0]['landed'] < best['landed']):
                best = offers[0]
        r['eb'] = best
        r['ebAsk'] = round(statistics.median(asks), 2) if asks else None
        r['ebN'] = len(asks)
    return {'calls': calls, 'errors': errors}


# ---------------------------------------------------------------- CardTrader (official API v2)
def cardtrader_best(listings):
    """Cheapest English Near Mint/Mint listing in EUR (item only)."""
    best = None
    for lst in (listings.values() if isinstance(listings, dict) else [listings]):
        for p in lst if isinstance(lst, list) else []:
            ph = p.get('properties_hash') or {}
            lang = str(ph.get('pokemon_language') or ph.get('language') or '').lower()
            cond = str(ph.get('condition') or '')
            price = p.get('price') or {}
            if lang not in ('en', 'english') or cond not in ('Near Mint', 'Mint') or price.get('cents') is None:
                continue
            if (price.get('currency') or 'EUR') != 'EUR':
                continue
            v = price['cents'] / 100
            best = v if best is None else min(best, v)
    return best


def cardtrader_lookup(cands, token):
    calls, errors = 0, 0
    for r in cands:
        bp = r['_c'].get('ct')
        if not bp:
            continue
        try:
            r['ct'] = cardtrader_best(get_json(f'{CT}/marketplace/products?blueprint_id={bp}',
                                               headers={'Authorization': 'Bearer ' + token}))
            calls += 1
        except Exception as e:
            errors += 1
            log(f'  CardTrader {bp}: {e}')
        time.sleep(1.1)  # documented limit for this endpoint: ~1 request/second
    return {'calls': calls, 'errors': errors}


# ---------------------------------------------------------------- output
COLS = ['k', 'id', 'kind', 'n', 's', 'no', 'v', 'img', 'avg', 'low', 'tr', 'a1', 'a7', 'a30', 'us', 'ct', 'eb', 'ebAsk', 'ebN']


def row_out(r):
    return [r.get(c) for c in COLS]


def write_history(rows, hist_dir, day):
    snap = {'d': day, 'cm': {}, 'us': {}, 'eb': {}, 'ct': {}}
    for r in rows:
        if r['tr'] >= 5:
            snap['cm'][r['k']] = r['tr']
        for f in ('us', 'ct'):
            if r.get(f):
                snap[f][r['k']] = round(r[f], 2)
        if r.get('eb'):
            snap['eb'][r['k']] = r['eb']['landed']
    hist_dir.mkdir(parents=True, exist_ok=True)
    (hist_dir / f'{day}.json').write_text(json.dumps(snap, separators=(',', ':')))


def history_series(hist_dir, keys, days=180):
    files = sorted(hist_dir.glob('*.json'))[-days:]
    snaps = [json.loads(p.read_text()) for p in files]
    dates = [s['d'] for s in snaps]
    s = {k: {f: [x[f].get(k) for x in snaps] for f in ('cm', 'us', 'eb', 'ct')} for k in keys}
    for k in s:  # drop all-empty series to keep the file small
        s[k] = {f: v for f, v in s[k].items() if any(x is not None for x in v)}
    return {'dates': dates, 's': {k: v for k, v in s.items() if v}}


def summary_md(rows, sources):
    fx_rows = sorted([r for r in rows if r.get('eb') and r['_m']['ref']],
                     key=lambda r: -((r['_m']['ref'] * 0.95 - 1) / r['eb']['landed'] - 1))[:10]
    lines = ['## Detector Pokémon', '', '| Sursă | Stare |', '|---|---|']
    lines += [f'| {k} | {v.get("status")} {v.get("note", "")} |' for k, v in sources.items()]
    if fx_rows:
        lines += ['', '### eBay → Cardmarket (ROI net estimat)', '', '| Carte | eBay adus în RO | Cardmarket ref | ROI |', '|---|---|---|---|']
        for r in fx_rows:
            roi = (r['_m']['ref'] * 0.95 - 1) / r['eb']['landed'] - 1
            lines.append(f"| {r['n']} {r['no']} | {r['eb']['landed']:.2f} € ({r['eb']['m']}) | {r['_m']['ref']:.2f} € | {roi:+.0%} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--tcgdex', required=True, help='path to tcgdex/cards-database/data')
    ap.add_argument('--out', default='docs/data')
    ap.add_argument('--history', default='history')
    a = ap.parse_args(argv)
    out, hist = Path(a.out), Path(a.history)
    out.mkdir(parents=True, exist_ok=True)
    day = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    sources = {}

    fx = parse_ecb(get(ECB))
    log('FX', {k: fx[k] for k in ('USD', 'GBP', 'RON')})
    cards, exp = load_tcgdex(a.tcgdex)
    log(f'TCGdex: {len(cards)} variante de cărți cu ID Cardmarket')

    prices = get_json(f'{CM}/priceGuide/price_guide_6.json')
    singles = get_json(f'{CM}/productList/products_singles_6.json')
    try:
        sealed = get_json(f'{CM}/productList/products_nonsingles_6.json')
    except Exception as e:
        sealed = None
        log('Cardmarket sigilate indisponibil:', e)
    rows = build_rows(prices, singles, sealed, cards, exp)
    sources['Cardmarket'] = {'status': 'ok', 'at': prices.get('createdAt'), 'note': f'{len(rows)} produse'}
    log(f'Cardmarket: {len(rows)} rânduri, prețuri din {prices.get("createdAt")}')

    try:
        groups = {r['_c']['tp_group'] for r in rows if r['_c'].get('tp_group')}
        tp = tcgplayer_prices(groups)
        for r in rows:
            if r['_c'].get('tp'):
                r['us'] = us_price(r['_c'], tp, fx)
        upd = get(f'https://tcgcsv.com/last-updated.txt').decode().strip()
        sources['TCGplayer (US)'] = {'status': 'ok', 'at': upd, 'note': f'{len(groups)} seturi'}
    except Exception as e:
        sources['TCGplayer (US)'] = {'status': 'eroare', 'note': str(e)[:200]}
    log('TCGplayer:', sources['TCGplayer (US)'])

    cands = pick_candidates(rows)
    log(f'Candidați pentru eBay/CardTrader: {len(cands)}')
    if os.environ.get('EBAY_CLIENT_ID') and os.environ.get('EBAY_CLIENT_SECRET'):
        try:
            st = ebay_lookup(cands, fx, os.environ['EBAY_CLIENT_ID'], os.environ['EBAY_CLIENT_SECRET'])
            sources['eBay DE/FR/IT/ES/UK/US'] = {'status': 'ok' if st['calls'] else 'eroare', 'at': day,
                                                 'note': f"{st['calls']} căutări, {st['errors']} erori"}
        except Exception as e:
            sources['eBay DE/FR/IT/ES/UK/US'] = {'status': 'eroare', 'note': str(e)[:200]}
    else:
        sources['eBay DE/FR/IT/ES/UK/US'] = {'status': 'lipsă cheie', 'note': 'adaugă EBAY_CLIENT_ID și EBAY_CLIENT_SECRET'}
    log('eBay:', sources['eBay DE/FR/IT/ES/UK/US'])
    if os.environ.get('CARDTRADER_TOKEN'):
        try:
            st = cardtrader_lookup(cands, os.environ['CARDTRADER_TOKEN'])
            sources['CardTrader'] = {'status': 'ok' if st['calls'] else 'eroare', 'at': day, 'note': f"{st['calls']} cărți, {st['errors']} erori"}
        except Exception as e:
            sources['CardTrader'] = {'status': 'eroare', 'note': str(e)[:200]}
    else:
        sources['CardTrader'] = {'status': 'lipsă cheie', 'note': 'adaugă CARDTRADER_TOKEN'}
    log('CardTrader:', sources['CardTrader'])

    write_history(rows, hist, day)
    for r in rows:
        r.setdefault('_m', metrics(r) if r['kind'] == 'single' else {'score': 0, 'ref': None})
    keys = [r['k'] for r in sorted((r for r in rows if r['kind'] == 'single'), key=lambda r: -r['_m']['score'])[:2500]]
    keys += [k for k in (r['k'] for r in cands) if k not in set(keys)]
    (out / 'history.json').write_text(json.dumps(history_series(hist, keys), separators=(',', ':')))
    (out / 'latest.json').write_text(json.dumps({
        'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes'), 'fx': {k: fx[k] for k in ('USD', 'GBP', 'RON')},
        'sources': sources, 'cols': COLS, 'rows': [row_out(r) for r in rows]}, separators=(',', ':'), ensure_ascii=False))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf8') as f:
            f.write(summary_md(rows, sources))
    log('Gata:', out / 'latest.json')


if __name__ == '__main__':
    sys.exit(main())
