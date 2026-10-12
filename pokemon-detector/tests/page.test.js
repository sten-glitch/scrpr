// Runs docs/index.html <script id="core"> in a VM: routes, ROI, lenses. `node tests/page.test.js`
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(__dirname + '/../docs/index.html', 'utf8');
const src = html.match(/<script id="core">([\s\S]*?)<\/script>/)[1];
const ctx = {}; vm.createContext(ctx);
vm.runInContext(src + ';this.api={fromCols,metrics,rank,LENSES}', ctx);
const { fromCols, metrics, rank } = ctx.api;

const cols = ['k', 'kind', 'n', 's', 'no', 'v', 'avg', 'low', 'tr', 'a1', 'a7', 'a30', 'us', 'ct', 'eb'];
const rows = fromCols({ cols, rows: [
  ['1', 'single', 'Charizard ex', '151', '199/165', 'Normal', 120, 95, 125, 140, 130, 100, 170, 88, { m: 'EBAY_DE', landed: 84, from: 'DE', url: 'u' }],
  ['2', 'single', 'Pikachu', '151', '025/165', 'Normal', 40, 5, 40, null, 41, 40, null, null, null],
  ['3', 'sealed', 'Booster Box', '151', null, 'Sigilat', 189, 149, 182, null, null, null, null, null, null],
] });
const cfg = { fee: 5, ship: 3 };
for (const r of rows) r.m = metrics(r, cfg);

const m = rows[0].m; // sell = 125*0.95-1 = 117.75; routes CM 98, CT 91, eBay 84
assert.deepEqual(m.routes.map(x => x.m), ['Cardmarket', 'CardTrader', 'eBay DE']);
assert.equal(m.best.m, 'eBay DE');
assert.ok(Math.abs(m.roi - (117.75 / 84 - 1)) < 1e-9);
assert.ok(Math.abs(m.us - (170 / 125 - 1)) < 1e-9);
assert.ok(m.sig.some(s => s[0] === 'eBay ieftin') && m.sig.some(s => s[0] === 'Prima SUA') && m.sig.some(s => s[0] === 'Momentum'));

assert.equal(rows[1].m.suspect, true);       // only route at 8 € vs ref 40 €
assert.equal(rows[1].m.best, null);

const f = { q: '', pmin: 1, pmax: 2000, rh: true, sus: false };
assert.deepEqual(rank(rows, 'buy', f, new Set()).map(r => r.k), ['1']);
assert.deepEqual(rank(rows, 'us', f, new Set()).map(r => r.k), ['1']);
assert.deepEqual(rank(rows, 'sealed', f, new Set()).map(r => r.k), ['3']);
assert.deepEqual(rank(rows, 'score', { ...f, q: '199/165' }, new Set()).map(r => r.k), ['1']);
assert.deepEqual(rank(rows, 'watch', f, new Set(['2'])).map(r => r.k), ['2']);
// a card whose Cardmarket and US prices differ more than 3x is flagged and hidden by default
const odd = fromCols({ cols, rows: [['9', 'single', 'Gyarados', 'Evolutions', '34/108', 'Normal', 100, 80, 101, 120, 110, 18, 7.5, null, null]] })[0];
odd.m = metrics(odd, cfg);
assert.ok(odd.m.suspect && odd.m.sig.some(s => s[0] === 'Preț divergent') && odd.m.sig.some(s => s[0] === 'Salt extrem'));
assert.deepEqual(rank([odd], 'mom', f, new Set()).length, 0);
assert.deepEqual(rank([odd], 'mom', { ...f, sus: true }, new Set()).length, 1);
console.log('page core ok');
