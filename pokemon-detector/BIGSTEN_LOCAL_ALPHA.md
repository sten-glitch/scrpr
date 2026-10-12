# BIGSTEN Local Alpha — run it on your own computer

**Status:** private, single-user proof of concept inside the DRAFT branch.
This is NOT a public SaaS, cannot safely be hosted on Railway/Internet, has
no login, no tenant isolation, billing or consumer-data deletion workflow.

The application provides the first full local flow:
seller listing -> title/description claims -> optional photo candidate analysis
-> Listing Truth Engine -> conservative Evidence/Reasoning -> browser report.

No marketplace API credentials or paid image model are required. The alpha
never submits photographs to a cloud service; the browser sends them only to
its loopback server at 127.0.0.1. Temporary copies are destroyed after each
request and are never committed or uploaded to GitHub.

## 1. Windows — start with zero paid services

Download/clone the repository and switch to the feature branch. In PowerShell:

    git clone https://github.com/sten-glitch/scrpr.git
    cd scrpr
    git fetch origin feature/pokemon-deal-reasoning-v1
    git switch feature/pokemon-deal-reasoning-v1
    cd pokemon-detector
    py -3 local_app.py --port 8765

Open in the browser:

    http://127.0.0.1:8765

You can also run the included Windows start-bigsten.bat script from inside
pokemon-detector if your Python launcher is available.

WITHOUT optional CV packages, BIGSTEN still checks claims in text and can
process manual or cached observations; it transparently marks photographs
as not automatically scanned. A detected absence of slab label is never
treated as proof that the item is raw.

## 2. Free local computer vision + OCR

All third-party dependencies are opt-in and FREE open-source packages.
In PowerShell, in the pokemon-detector folder:

    py -3 -m venv .venv
    .venv\Scripts\Activate.ps1
    python -m pip install -r requirements-local.txt

If PowerShell execution policy prevents venv activation, run the virtualenv
Python directly:

    .venv\Scripts\python.exe -m pip install -r requirements-local.txt
    .venv\Scripts\python.exe local_app.py --port 8765

OCR also requires the separately installed Tesseract executable. It must be
installed by the user and available in PATH. If Tesseract is unavailable
the app still runs OpenCV rectangle detection; OCR names/numbers stay unknown.

The local_cv engine is intentionally provisional: it finds card-like
quadrilaterals, tries to read visible name and number, but does NOT confidently
determine exact set/foil, edition, grading, authenticity or rarity. Boxes can
be missed, duplicated or mistaken for sleeve/packaging. A complete graded
identification or image-indexed pHash/ORB matching is **future work**.

## 3. Optional TCGdex metadata-only identity index

The app starts without a catalog. If you have the authorized TCGdex source
checkout, export a local JSON catalog:

    git clone https://github.com/tcgdex/cards-database.git tcgdex
    python catalog_export.py --tcgdex tcgdex/data --out vision_catalog.json
    python local_app.py --port 8765 --catalog vision_catalog.json

Card printing, number, language and finish must ALL match before an exact
identity can be attached. A fuzzy match or OCR guess is never enough.
Do not automatically rehost copyrighted card artwork.

## 4. Use the interface

1. Enter seller title, listing type, description and EUR asking price.
2. Upload up to four JPG/PNG/WebP photographs (max 5 MiB each, 8 MiB total
   recommended in the browser). You may also run text-only evaluation.
3. Optional: paste an observation JSON obtained from separately reviewed
   photographs or local image model. This bypasses OpenCV for reproducible
   tests. The observation is NOT an authentication certificate.
4. Click Analyze evidence. Review contradictions, unknowns and missing
   completed-sale cost/provenance. Browser export downloads a JSON report
   directly from browser memory.
5. To stop, press Ctrl+C in the terminal. No user account or cloud storage
   exists. Don't use it from an untrusted shared PC.

A photograph showing a raw/unencapsulated card can contradict an asserted PSA
grade **only when slab_visible=false is explicitly established**. Missing
slab metadata is merely unverified; a matching photographed slab label is
visually consistent but does NOT establish PSA certificate authenticity.

The financial section returns UNKNOWN when no independently attested
like-for-like completed sales are available. No buy is ever automatic.

## 5. Developer tests

    python -m unittest discover -s tests -v
    node --check local_app/app.js
    node tests/page.test.js

No network or optional computer vision package is needed for the core
regression suite; unit tests mock optional vision dependencies.

## 6. Roadmap and launch gates

Read BIGSTEN_SAAS_MASTER_PLAN.md for full phase plan:
P0 local alpha -> P1 image accuracy pilot -> P2 authenticated private SaaS beta
-> P3 paid launch. Beta needs authorization, user accounts, data segregation,
secure storage/retention, a legally licensed commercial dataset, provider terms,
GDPR support, subscriptions, quotas, and a real-image accuracy benchmark.

Do not run this local alpha behind an internet-accessible proxy, through
Railway or by opening port 8765 on your router. localhost only.
