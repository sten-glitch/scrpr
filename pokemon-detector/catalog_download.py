"""Fetch an explicit, bounded TCGdex catalog subset; never download card images."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.request


def fetch(path):
    url = 'https://api.tcgdex.net/v2/' + path
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError('Catalog response too large')
    return json.loads(raw), hashlib.sha256(raw).hexdigest(), url


def card_entries(card, language, source_url, digest):
    entries = []
    for variant in card.get('variants_detailed') or []:
        if not variant.get('variantId') or not variant.get('type'):
            continue
        # Include all edition dimensions in the query label, preserving separate identities.
        labels = [variant['type']]
        labels += [str(variant[k]) for k in ('subtype', 'size') if variant.get(k)]
        labels += sorted(variant.get('stamp') or [])
        entries.append({
            'identity_key': f"tcgdex:{language}:{card['id']}:{variant['variantId']}",
            'name': card['name'], 'set': card['set']['name'], 'set_id': card['set']['id'],
            'number': card['localId'], 'language': language, 'finish': ' '.join(labels),
            'source_url': source_url, 'source_sha256': digest,
            'source_variant': {k:v for k,v in variant.items() if k != 'pricing'},
        })
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--set', action='append', required=True, dest='sets', help='en:base1 or ja:PMCG1')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    jobs, sources = [], []
    for spec in dict.fromkeys(args.sets):
        if not re.fullmatch(r'(en|ja):[A-Za-z0-9.-]+', spec):
            parser.error('Invalid language:set')
        lang, set_id = spec.split(':')
        data, digest, url = fetch(f'{lang}/sets/{set_id}')
        sources.append({'url':url, 'sha256':digest, 'cards':len(data['cards'])})
        jobs += [(lang, c['id']) for c in data['cards']]
    if len(jobs) > 2000:
        raise ValueError('Use smaller batches, at most 2000 cards')
    def load(job):
        lang, card_id = job
        if not re.fullmatch(r'[A-Za-z0-9.-]+', card_id):
            raise ValueError('Invalid source card id')
        card, digest, url = fetch(f'{lang}/cards/{card_id}')
        return card_entries(card, lang, url, digest)
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(load, jobs))
    rows = sorted([row for batch in batches for row in batch], key=lambda r:r['identity_key'])
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'retrieved_at':datetime.now(timezone.utc).isoformat(), 'sources':sources,
              'cards_requested':len(jobs), 'cards_without_detailed_variants':sum(not b for b in batches),
              'identities':len(rows), 'languages':{lang:sum(r['language']==lang for r in rows) for lang in ('en','ja')},
              'catalog_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'images_downloaded':0, 'coverage':'Explicit requested sets only; not a complete Pokemon catalog'}
    target.with_suffix('.provenance.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))

if __name__ == '__main__':
    main()
