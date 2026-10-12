"""Offline checks for detector.py: parsing, matching, landed cost, eBay filtering, history. No network."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detector as d

FX = {'EUR': 1.0, 'USD': 1.12, 'GBP': 0.85, 'RON': 5.34}

SET_TS = '''import { Set } from '../../interfaces'
const set: Set = {
	id: "sv03.5",
	name: { de: "151", en: "151" },
	serie: serie,
	cardCount: { official: 165 },
	abbreviations: { official: "MEW", fr: "151" },
	thirdParty: { cardmarket: 5402, tcgplayer: 23237 }
}'''
CARD_VARIANTS_TS = '''const card: Card = {
	dexId: [6], set: Set,
	name: { fr: "Dracaufeu-ex", en: "Charizard ex", de: "Glurak-ex" },
	rarity: "Special illustration rare",
	attacks: [{ name: { en: "Brave Wing" }, damage: "60+" }],
	weaknesses: [{ type: "Water", value: "×2" }],
	variants: [
		{ type: 'holo', thirdParty: { cardmarket: 733794, tcgplayer: 517045, cardtrader: 261377 } },
		{ type: 'reverse', thirdParty: { cardmarket: 733794, tcgplayer: 517045 } },
	],
}'''
CARD_TOP_TS = '''const card: Card = {
	name: { en: "Farfetch'd", de: "Porenta" },
	rarity: "Common",
	weaknesses: [{ type: "Lightning" }],
	thirdParty: { cardmarket: 280879, tcgplayer: 90547 }
}'''


class Parse(unittest.TestCase):
    def test_set(self):
        s = d.parse_set(SET_TS)
        self.assertEqual((s['id'], s['name'], s['official'], s['code'], s['cm_cardmarket'], s['cm_tcgplayer']),
                         ('sv03.5', '151', 165, 'MEW', 5402, 23237))

    def test_card_variants(self):
        name, rarity, v = d.parse_card(CARD_VARIANTS_TS)
        self.assertEqual(name, 'Charizard ex')
        self.assertEqual([t for t, _ in v], ['holo', 'reverse'])
        self.assertEqual(v[0][1], {'cardmarket': 733794, 'tcgplayer': 517045, 'cardtrader': 261377})

    def test_card_top_level_ids(self):
        name, _, v = d.parse_card(CARD_TOP_TS)
        self.assertEqual(name, "Farfetch'd")
        self.assertEqual([t for t, _ in v], ['normal', 'reverse'])

    def test_load_tree(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / 'Scarlet & Violet' / '151').mkdir(parents=True)
            (root / 'Scarlet & Violet.ts').write_text('const serie = { id: "sv" }')
            (root / 'Scarlet & Violet' / '151.ts').write_text(SET_TS)
            (root / 'Scarlet & Violet' / '151' / '199.ts').write_text(CARD_VARIANTS_TS)
            cards, exp = d.load_tcgdex(root)
        c = cards[(733794, '')]
        self.assertEqual((c['no'], c['tp_group'], c['ct']), ('199/165', 23237, 261377))
        self.assertEqual(cards[(733794, '-holo')]['tp_sub'], ['Reverse Holofoil'])
        self.assertEqual(c['img'], 'https://assets.tcgdex.net/en/sv/sv03.5/199/high.webp')
        self.assertEqual(exp, {5402: '151'})

    def test_ecb(self):
        xml = b'''<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
        <Cube><Cube time="2026-10-09"><Cube currency="USD" rate="1.1206"/><Cube currency="RON" rate="5.3406"/></Cube></Cube></gesmes:Envelope>'''
        self.assertEqual(d.parse_ecb(xml), {'EUR': 1.0, 'USD': 1.1206, 'RON': 5.3406})


def sample_rows():
    prices = {'createdAt': 'x', 'priceGuides': [
        {'idProduct': 733794, 'avg': 120, 'low': 80, 'trend': 125, 'avg1': 140, 'avg7': 130, 'avg30': 100,
         'avg-holo': None, 'low-holo': None, 'trend-holo': 1.5},
        {'idProduct': 9, 'avg': 189, 'low': 149, 'trend': 182}]}
    singles = {'products': [{'idProduct': 733794, 'name': 'Charizard ex', 'idExpansion': 5402}]}
    sealed = {'products': [{'idProduct': 9, 'name': '151 Booster Bundle', 'idExpansion': 5402, 'categoryName': 'Pokémon Booster'}]}
    cards = {(733794, ''): {'name': 'Charizard ex', 'set': '151', 'no': '199/165', 'local': '199', 'tp': 517045,
                            'tp_sub': ['Holofoil', 'Normal'], 'ct': 261377, 'tp_group': 23237, 'img': 'i'}}
    return d.build_rows(prices, singles, sealed, cards, {5402: '151'})


class Rows(unittest.TestCase):
    def test_reverse_holo_and_set_name_fallbacks(self):
        prices = {'priceGuides': [{'idProduct': 5, 'trend': 10, 'trend-holo': 12}]}
        singles = {'products': [{'idProduct': 5, 'name': 'Pikachu', 'idExpansion': 77}]}
        sealed = {'products': [{'idProduct': 6, 'name': 'Terastal Festival Booster Box', 'idExpansion': 77},
                               {'idProduct': 7, 'name': 'Terastal Festival Booster', 'idExpansion': 77}]}
        cards = {(5, ''): {'name': 'Pikachu', 'no': '025/165', 'tp': 9, 'tp_sub': ['Normal', 'Holofoil']}}
        rows = d.build_rows(prices, singles, sealed, cards, {})
        rh = [r for r in rows if r['k'] == '5h'][0]
        self.assertEqual((rh['no'], rh['_c']['tp_sub']), ('025/165', ['Reverse Holofoil']))
        self.assertEqual(rows[0]['s'], 'Terastal Festival')
        self.assertEqual(cards[(5, '')]['tp_sub'], ['Normal', 'Holofoil'])  # source mapping untouched

    def test_build(self):
        rows = sample_rows()
        self.assertEqual([r['k'] for r in rows], ['733794', '9'])  # RH trend 1.5 < €2 dropped
        self.assertEqual((rows[0]['no'], rows[0]['s'], rows[1]['kind']), ('199/165', '151', 'sealed'))

    def test_metrics_and_candidates(self):
        r = sample_rows()[0]
        m = d.metrics(r)
        self.assertAlmostEqual(m['roi'], (125 * 0.95 - 1) / 83 - 1)
        self.assertAlmostEqual(m['mom'], 0.3)
        self.assertEqual(m['liq'], 3)
        self.assertEqual([x['k'] for x in d.pick_candidates([r])], ['733794'])

    def test_us_price(self):
        c = {'tp': 517045, 'tp_sub': ['Holofoil', 'Normal']}
        tp = {(517045, 'Holofoil'): {'market': 112.0, 'low': 90.0}}
        self.assertAlmostEqual(d.us_price(c, tp, FX), 100.0)
        self.assertIsNone(d.us_price({'tp': 1, 'tp_sub': ['Normal']}, tp, FX))


class Costs(unittest.TestCase):
    def test_landed(self):
        self.assertEqual(d.landed_eur(100, 5, 'DE', FX), 105)
        # non-EU under €150: (base + €3 duty) × 1.21 + 25 lei
        self.assertAlmostEqual(d.landed_eur(100, 5, 'US', FX), (108) * 1.21 + 25 / 5.34)
        self.assertAlmostEqual(d.landed_eur(300, 10, 'GB', FX), 310 * 1.027 * 1.21 + 15)

    def test_ebay_filter(self):
        c = {'name': 'Charizard ex', 'no': '199/165', 'local': '199'}
        items = [
            {'title': 'PSA 10 Charizard ex 199/165', 'price': {'value': '400', 'currency': 'EUR'}},
            {'title': 'Charizard ex 199/165 Japanese', 'price': {'value': '60', 'currency': 'EUR'}},
            {'title': 'Charizard ex 006/165 151', 'price': {'value': '20', 'currency': 'EUR'}},
            {'title': 'Pokemon Charizard ex 199/165 SIR 151 NM', 'price': {'value': '112', 'currency': 'USD'},
             'itemLocation': {'country': 'US'}, 'shippingOptions': [{'shippingCost': {'value': '20.16', 'currency': 'USD'}}], 'itemWebUrl': 'u1'},
            {'title': 'Glurak ex 199/165 deutsch', 'price': {'value': '90', 'currency': 'EUR'}, 'itemLocation': {'country': 'DE'}, 'itemWebUrl': 'u3'},
            {'title': 'Charizard ex 199/165 151 SIR', 'price': {'value': '118', 'currency': 'EUR'}, 'itemLocation': {'country': 'DE'}, 'itemWebUrl': 'u2'},
        ]
        offers = d.ebay_offers(items, c, FX)
        self.assertEqual([o['url'] for o in offers], ['u2', 'u1'])  # graded, Japanese, wrong number removed
        self.assertTrue(offers[0]['shipGuess'])
        self.assertEqual(offers[0]['landed'], 124.0)  # 118 + €6 EU shipping guess
        self.assertAlmostEqual(offers[1]['landed'], round((100 + 18 + 3) * 1.21 + 25 / 5.34, 2))

    def test_number_regex(self):
        self.assertTrue(d.number_re({'local': '006', 'no': '006/165'}).search('Charmander 6/165'))
        self.assertFalse(d.number_re({'local': '006', 'no': '006/165'}).search('Charmander 106/165'))
        self.assertTrue(d.number_re({'local': 'SWSH050', 'no': 'SWSH050'}).search('promo swsh050 pikachu'))

    def test_cardtrader_best(self):
        nm = lambda cents, **ph: {'price': {'cents': cents, 'currency': 'EUR'}, 'properties_hash': {'condition': 'Near Mint', 'pokemon_language': 'en', **ph}}
        lst = [{'price': {'cents': 9000, 'currency': 'EUR'}, 'properties_hash': {'condition': 'Played', 'pokemon_language': 'en'}},
               nm(11000), nm(10500, pokemon_language='jp'), nm(8000, pokemon_reverse=True), {**nm(7000), 'graded': True}]
        self.assertEqual(d.cardtrader_best(lst), 110.0)
        self.assertEqual(d.cardtrader_best(lst, reverse=True), 80.0)

    def test_cardtrader_lookup(self):
        rows = sample_rows()
        api = {
            '/games': {'array': [{'id': 1, 'name': 'Magic'}, {'id': 5, 'name': 'Pokemon', 'display_name': 'Pokémon'}]},
            '/expansions': [{'id': 10, 'game_id': 5}, {'id': 11, 'game_id': 1}],
            '/blueprints/export?expansion_id=10': [{'id': 261377, 'card_market_ids': [733794]}],
            '/marketplace/products?expansion_id=10&language=en': {'261377': [
                {'price': {'cents': 9900, 'currency': 'EUR'}, 'properties_hash': {'condition': 'Near Mint', 'pokemon_language': 'en'}}]},
        }
        old_get, old_sleep = d.get_json, d.time.sleep
        d.get_json = lambda url, **kw: api[url[len(d.CT):]]
        d.time.sleep = lambda s: None
        try:
            st = d.cardtrader_lookup(rows, rows[:1], 'tok')
        finally:
            d.get_json, d.time.sleep = old_get, old_sleep
        self.assertEqual(rows[0]['ct'], 99.0)
        self.assertEqual((st['game'], st['sets'], st['linked'], st['checked'], st['prices'], st['errors']), (5, 1, 1, 1, 1, 0))


class History(unittest.TestCase):
    def test_roundtrip(self):
        rows = sample_rows()
        rows[0]['us'] = 99.5
        with tempfile.TemporaryDirectory() as t:
            h = Path(t)
            d.write_history(rows, h, '2026-10-11')
            rows[0]['tr'] = 130
            d.write_history(rows, h, '2026-10-12')
            s = d.history_series(h, ['733794', 'missing'])
        self.assertEqual(s['dates'], ['2026-10-11', '2026-10-12'])
        self.assertEqual(s['s']['733794']['cm'], [125, 130])
        self.assertEqual(s['s']['733794']['us'], [99.5, 99.5])
        self.assertNotIn('missing', s['s'])


if __name__ == '__main__':
    unittest.main()
