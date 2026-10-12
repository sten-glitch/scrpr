# Detector Pokémon

> **NEW — BIGSTEN Collection Intelligence (draft branch only).**
> The new single-user, offline-first web alpha is separate from the live daily
> price radar and not yet deployed. On Windows, run start-bigsten.bat from the
> pokemon-detector directory (or python local_app.py --port 8765), then open
> http://127.0.0.1:8765. A normal browser and Python 3.12+ suffice for
> text-only checks; optional OpenCV/Tesseract enable provisional local photo
> processing. Do not publicly expose this unauthenticated alpha.
>
> Documentation: [Local Alpha guide](BIGSTEN_LOCAL_ALPHA.md) ·
> [Commercial SaaS Master Plan](BIGSTEN_SAAS_MASTER_PLAN.md) ·
> [Third-party rights](THIRD_PARTY_RIGHTS.md) ·
> [Offline Photo Lab](OFFLINE_PHOTO_LAB.md) ·
> [Sales Evidence Lab](SALES_EVIDENCE_LAB.md).
>
> **NEW P1:** [Private Photo Ground Truth Lab](PHOTO_REVIEW_LAB.md) — run
> `start-photo-lab.bat` on Windows after placing permissioned photos into
> `private/evaluation-photos`. Label card regions, exact printing and negative
> cases locally. Benchmark with `reference_benchmark.py --html ...` to review
> real photo errors; no real photo dataset has been added to this public repo.
> **No provider's marketplace data or Pokémon artwork rights are assumed merely
> because open-source code or a developer API is available.**


Detector zilnic de oportunități pentru cărți Pokémon. Compară Cardmarket, CardTrader, eBay (DE, FR, IT, ES, UK, SUA) și TCGplayer (SUA), calculează prețul adus în România și clasează cărțile după momentum, marjă și lichiditate.

Rulează singur în fiecare dimineață la 07:30 (ora României) prin GitHub Actions și publică rezultatul pe GitHub Pages (ramura `gh-pages`): `https://sten-glitch.github.io/scrpr/`.

## Surse (fără scraping)

| Piață | Regiune | Ce citim | Acces |
|---|---|---|---|
| Cardmarket | UE | ghidul public zilnic: trend, cea mai ieftină ofertă, medii 24h/7z/30z | public, fără cheie |
| CardTrader | UE | cea mai ieftină ofertă EN Near Mint | token gratuit din cont |
| eBay DE/FR/IT/ES/UK/SUA | UE, UK, SUA | anunțuri „Cumpără acum” prin Browse API, adus în RO | cheie gratuită developer.ebay.com |
| TCGplayer (prin tcgcsv.com) | SUA | prețul de piață | public, fără cheie |
| TCGdex (GitHub, MIT) | toate | leagă aceeași carte între piețe | public |

Vinted, Kleinanzeigen și paginile eBay de vânzări finalizate nu au API și interzic scraping-ul, deci nu sunt incluse.

## Pornire (o singură dată)

1. **GitHub Pages:** site-ul se publică pe ramura `gh-pages`. Dacă pagina nu apare, Settings → Pages → Source: **Deploy from a branch** → `gh-pages` / root.
2. **eBay (recomandat):**
   1. Fă cont gratuit pe [developer.ebay.com](https://developer.ebay.com) și creează un keyset **Production**.
   2. La Alerts & Notifications → Marketplace Account Deletion alege „I do not persist eBay data” (exceptare), altfel cheile rămân blocate.
   3. Copiază App ID (Client ID) și Cert ID (Client Secret).
   4. În repo: Settings → Secrets and variables → Actions → New repository secret: `EBAY_CLIENT_ID` și `EBAY_CLIENT_SECRET`.
3. **CardTrader (opțional):** pe cardtrader.com → Settings → API → copiază tokenul în secretul `CARDTRADER_TOKEN`.
4. **Prima rulare:** Actions → „Detector Pokémon — actualizare zilnică” → Run workflow. După ~5 minute pagina are date.

Fără chei, detectorul rulează doar cu Cardmarket și TCGplayer și arată pe pagină ce lipsește.

## Ce rulează zilnic

`detector.py` (doar biblioteca standard Python) descarcă sursele, potrivește cărțile prin ID-urile TCGdex, alege ~150 de candidați (scor mare sau momentum) pentru căutări eBay și CardTrader, scrie `docs/data/latest.json`, `docs/data/history.json` și salvează un instantaneu zilnic în `history/`. Graficele cresc zi de zi din acest istoric.

Costuri de import folosite (UK și SUA → RO): TVA 21%, taxă vamală UE €3 pe colet ≤ €150 (din 1.07.2026), taxa logistică RO de 25 lei. Peste €150: 2,7% taxă vamală (neverificat în TARIC) și ~€15 brokeraj. Se schimbă în `detector.py`, sus.

## Teste

```bash
python -m unittest discover -s tests -v
node tests/page.test.js
```

Nu e sfat financiar. Verifică oferta (limbă, stare, vânzător) înainte să cumperi.
