"""Conservative, deterministic grouping of observed single-card listings.

aggregate_supply accepts JSON objects with required nonempty string marketplace
and item_id. Known eBay marketplace views share the eBay ID namespace; other
marketplaces retain separate ID namespaces. Members preserve observed markets.
Optional fields:
  identity_key: exact catalog variant identity, grade: string or number;
  certificate: {grader, number, evidence_status, source, provenance};
  image_sha256: exact image SHA256, price: {amount, currency}.
Certificate numbers must be strings to preserve leading zeroes. Evidence source
must be photographed_label or grader_registry; provenance is a nonempty reference
to that evidence (image/crop ID, registry response ID, or review record). Only an
upstream explicit human_confirmed or verified_consistency status is accepted by
default. A status is a caller attestation, not independently verified here.
Groups therefore report verification_status=unavailable; confirmed groups use
confidence_kind=explicit_attestation, never a calibrated confidence score.
Seller title/text, OCR confidence alone, and shared images cannot confirm a cert.
identity_key and grade must describe that same evidence, not inferred seller text.

Bounds are conditional observed identities, assuming one item per listing,
complete coverage of the supplied observations and truthful, distinct accepted
certificates. They are NOT physical supply, authenticity, inventory or population
estimates. Prices summarize distinct listing offers, separately by currency.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import statistics


DEFAULT_EVIDENCE_STATUSES = frozenset({'human_confirmed', 'verified_consistency'})
EVIDENCE_SOURCES = frozenset({'photographed_label', 'grader_registry'})
EBAY_MARKETPLACES = frozenset({'ebay', *(f'ebay_{country}' for country in (
    'at', 'au', 'be', 'ca', 'ch', 'de', 'es', 'fr', 'gb', 'hk', 'ie', 'it',
    'my', 'nl', 'ph', 'pl', 'sg', 'us'))})


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _grade(value):
    if isinstance(value, bool):
        return ''
    try:
        number = Decimal(str(value))
        return format(number.normalize(), 'f') if number.is_finite() and 0 < number <= 10 else ''
    except InvalidOperation:
        return ''


def _certificate(row, statuses):
    cert = row.get('certificate')
    if not isinstance(cert, dict):
        return None
    grader, number = _text(cert.get('grader')).upper(), _text(cert.get('number'))
    grader = {'BECKETT': 'BGS', 'BECKETT GRADING SERVICES': 'BGS'}.get(grader, grader)
    identity, grade = _text(row.get('identity_key')), _grade(row.get('grade'))
    if (grader not in {'PSA', 'BGS', 'CGC'} or not re.fullmatch(r'[0-9]+', number)
            or not identity or not grade
            or _text(cert.get('evidence_status')) not in statuses
            or _text(cert.get('source')) not in EVIDENCE_SOURCES
            or not _text(cert.get('provenance'))):
        return None
    return (grader, number), (identity, grade)


def aggregate_supply(listings, *, accepted_evidence_statuses=DEFAULT_EVIDENCE_STATUSES):
    """Return JSON-safe groups, evidence conflicts, counts and conditional bounds.

    Duplicate item IDs collapse even if repeated observations conflict; those
    conflicts and explicitly invalid grades remain visible and prevent
    certificate merging. Missing item IDs
    raise ValueError rather than silently collapsing unrelated observations.
    Caller-supplied evidence statuses must be a subset of supported explicit
    attestations; this prevents enabling seller_claim/OCR-only evidence by error.
    """
    if not isinstance(listings, list) or any(not isinstance(r, dict) for r in listings):
        raise ValueError('listings must be a list of objects')
    statuses = frozenset(accepted_evidence_statuses)
    if not statuses <= DEFAULT_EVIDENCE_STATUSES:
        raise ValueError('unsupported certificate evidence status')
    items = defaultdict(list)
    markets = defaultdict(set)
    for row in listings:
        market, item = _text(row.get('marketplace')).lower(), _text(row.get('item_id'))
        if not market or not item:
            raise ValueError('each listing requires string marketplace and item_id')
        key = ('ebay' if market in EBAY_MARKETPLACES else market, item)
        items[key].append(row)
        markets[key].add(market)

    cert_variants, cert_items = defaultdict(set), defaultdict(set)
    candidates, reasons = {}, defaultdict(set)
    evidence = defaultdict(set)
    images = defaultdict(set)
    item_prices = {}
    for key, rows in sorted(items.items()):
        accepted, variants = set(), set()
        prices = defaultdict(set)
        for row in rows:
            identity, grade = _text(row.get('identity_key')), _grade(row.get('grade'))
            if row.get('grade') not in (None, '') and not grade:
                reasons[key].add('invalid_grade_observation')
            if identity and grade:
                variants.add((identity, grade))
            found = _certificate(row, statuses)
            if found:
                cert, variant = found
                accepted.add(cert)
                cert_variants[cert].add(variant)
                cert_items[cert].add(key)
                e = row['certificate']
                evidence[key].add((e['evidence_status'], e['source'], e['provenance'],
                                   _text(row.get('marketplace')).lower()))
            digest = _text(row.get('image_sha256')).lower()
            if re.fullmatch(r'[0-9a-f]{64}', digest):
                images[digest].add(key)
            price = row.get('price')
            if isinstance(price, dict) and not isinstance(price.get('amount'), bool):
                currency = _text(price.get('currency')).upper()
                try:
                    amount = Decimal(str(price.get('amount')))
                    if (re.fullmatch(r'[A-Z]{3}', currency) and amount.is_finite()
                            and amount >= 0 and math.isfinite(float(amount))):
                        prices[currency].add(amount)
                except InvalidOperation:
                    pass
        if len(accepted) > 1 or len(variants) > 1:
            reasons[key].add('conflicting_item_observations')
        if not accepted:
            reasons[key].add('missing_accepted_certificate_evidence')
        candidates[key] = accepted
        for currency, amounts in prices.items():
            if len(amounts) == 1:
                item_prices[(key, currency)] = next(iter(amounts))
            else:
                reasons[key].add('conflicting_price_observations')

    unsafe = {cert for cert, variants in cert_variants.items() if len(variants) > 1}
    # A conflicting repeated item can implicate otherwise consistent certificates.
    unsafe.update(cert for key, certs in candidates.items()
                  if reasons[key] & {'conflicting_item_observations', 'invalid_grade_observation'}
                  for cert in certs)
    for cert in unsafe:
        for key in cert_items[cert]:
            reasons[key].add('certificate_conflict')

    grouped = defaultdict(list)
    for key, certs in sorted(candidates.items()):
        safe = len(certs) == 1 and not (certs & unsafe)
        group_key = ('certificate', *next(iter(certs))) if safe else ('unresolved', *key)
        grouped[group_key].append(key)

    def member(key):
        return {'marketplace': key[0], 'item_id': key[1],
                'observed_marketplaces': sorted(markets[key])}

    groups = []
    for group_key, members in sorted(grouped.items()):
        confirmed = group_key[0] == 'certificate'
        stable = json.dumps([group_key, members], ensure_ascii=True, separators=(',', ':'))
        group = {'group_id': hashlib.sha256(stable.encode()).hexdigest()[:24],
                 'status': 'confirmed_certificate_identity' if confirmed else 'unresolved',
                 'verification_status': 'unavailable',
                 'confidence_kind': 'explicit_attestation' if confirmed else 'insufficient_evidence',
                 'members': [member(k) for k in members],
                 'reasons': sorted({r for k in members for r in reasons[k]}),
                 'evidence': [dict(member(k), evidence_status=e[0], source=e[1],
                                   provenance=e[2], evidence_marketplace=e[3])
                              for k in members for e in sorted(evidence[k])]}
        if confirmed:
            cert = tuple(group_key[1:])
            identity, grade = next(iter(cert_variants[cert]))
            group.update(certificate={'grader': cert[0], 'number': cert[1]},
                         identity_key=identity, grade=grade)
        groups.append(group)

    reused = [{'image_sha256': digest, 'status': 'reused_photo_only',
               'different_certificate_conflict': len({cert for k in keys for cert in candidates[k]}) > 1,
               'members': [member(k) for k in sorted(keys)]}
              for digest, keys in sorted(images.items()) if len(keys) > 1]
    currency_prices = defaultdict(list)
    for (_, currency), amount in item_prices.items():
        currency_prices[currency].append(amount)
    confirmed = sum(g['status'] == 'confirmed_certificate_identity' for g in groups)
    unresolved = len(groups) - confirmed
    return {
        'schema_version': 1,
        'counts': {'raw_observations': len(listings), 'unique_listings': len(items),
                   'repeated_item_observations': len(listings) - len(items),
                   'confirmed_certificate_groups': confirmed,
                   'certificate_duplicate_listings': len(items) - len(groups),
                   'unresolved_listings': unresolved,
                   'conflicting_certificate_ids': len(unsafe)},
        'groups': groups, 'reused_photos': reused,
        'prices_by_currency': {currency: {'listing_count': len(prices),
                                         'cheapest_asking_price': float(min(prices)),
                                         'median_asking_price': float(statistics.median(prices))}
                               for currency, prices in sorted(currency_prices.items())},
        'price_conflict_listings': [member(k) for k in sorted(items)
                                   if 'conflicting_price_observations' in reasons[k]],
        'conditional_observed_identity_bounds': {
            'lower': max(confirmed, int(bool(items))), 'upper': confirmed + unresolved,
            'assumptions': ['Each listing offers exactly one item.',
                            'Accepted certificate evidence is truthful and identifies distinct items.',
                            'Unresolved listings may overlap any observed identity.'],
            'scope': 'Supplied observations only; not physical supply, authenticity or market population.'},
    }
