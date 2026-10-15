# BIGSTEN Pokémon — Visual Intelligence + Marketplace Discovery V2

Status: draft PR and offline-tested foundation, NOT deployed or validated on real card photos. No automated purchase.

## Implemented

- Existing detector.py and dashboard: Cardmarket/TCGplayer price trends, CardTrader and eBay when configured; not a verified sold-sales database.
- ebay_discovery.py: fixed-price eBay Browse API search across singles, graded cards, binders, lots and sealed products, six regional marketplaces; optional full listing images.
- vision.py: image interpretation using configurable OpenAI-compatible vision service, with visual bounding boxes, visible defects and cautious condition labels.
- catalog_export.py: TCGdex identity index including set, card number, language and variant; optional Cardmarket sealed-product index.
- reasoning.py: rejects missing or unmatched sold comparables, rejects explicit counterfeit/reseal flags, prices conservatively and requires manual approval.
- No cloud AI calls by default. A visual observation alone can never trigger BUY_CANDIDATE: no proven sold comps, authenticity, grading or verified costs.

## Test

From pokemon-detector directory:

    python -m unittest discover -s tests -v
    node tests/page.test.js

## Run manually in GitHub

The workflow file is .github/workflows/pokemon-marketplace-manual.yml.
It becomes manually runnable from the Actions tab after merging to the repository default branch.
Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET as GitHub Actions secrets with official Browse API access.
Run the Pokémon Marketplace workflow with regions and maximum offers.
Choose vision_top=0 first: no image AI cost.
Download the pokemon-marketplace-scan artifact (scan.json).
For optional AI image analysis, set VISION_API_KEY and choose vision_top=1 (then up to 3).
The workflow is NOT scheduled and has not yet been tested against live marketplace credentials.

## Run locally

Obtain tcgdex/cards-database checkout alongside pokemon-detector first.

    python catalog_export.py --tcgdex ../tcgdex/data --include-sealed --out vision_catalog.json
    python ebay_discovery.py --markets EBAY_DE,EBAY_GB --categories single,graded,binder,lot,sealed --max-offers 20 --details --vision-top 0 --catalog vision_catalog.json --out artifacts/scan.json

To analyze photo URLs from an input listing (remote provider, potentially billable):

    python vision.py listing.json --catalog vision_catalog.json --out result.json

To check cached model observations offline without calling a provider:

    python vision.py listing.json --observation cached_observation.json --catalog vision_catalog.json --out result.json

Input listing JSON must include asking_eur and 1..8 public image_urls.
See vision.py and tests/test_vision.py for the structured observation JSON schema.

Vision provider settings:
- VISION_API_KEY: secret for paid/hosted endpoint.
- VISION_MODEL: configured image-capable model (default gpt-4.1-mini).
- VISION_API_URL: defaults to https://api.openai.com/v1/chat/completions; localhost HTTP allowed for a compatible self-hosted model.

Provider support for image URLs and JSON object responses must be checked.
A local model is not necessarily capable of reading small binder photos accurately.

## Deliberate limits

- Never authenticate cards, seal quality, PSA grade or contents using image alone.
- Name-only matching is forbidden for singles. Exact variant and printing matter.
- A slab requires independent serial and grading verification.
- For lots/binders, a hidden unknown inventory placeholder prevents falsely complete inventory.
- Model outputs cannot provide verified sold prices, verified shipping fees, or authorization to buy.
- Shipping/taxes/fees are not guessed where the marketplace does not supply them.
- Image URLs must be public HTTPS. Seller listing text is treated as untrusted data.
- GitHub Actions stores scans as private workflow artifacts, not on the public Pages site.
- Only fixed-price eBay Browse listings are searched so far. No automatic purchases.
- Currently no documented accuracy benchmark against real images or actual resale outcomes.

## Next hard requirements before calling this a reliable buying radar

1. Integrate authorized completed-sales data with actual timestamps and proof of sale.
2. Calibrate photo model, exact card matching and scoring on human-annotated listings.
3. Add seller risk, verified tax/import schedules, return terms and realistic sell-through time.
4. Instrument monitoring, deduplication, expiration and alerts while complying with marketplace terms.
5. Build a dashboard that shows listing photograph, evidence, conservative profit and review checklist.

A good price quote or attractive modeled ROI is not proof of a profitable resale.
