# BIGSTEN — Offline Photo Lab

Use this workflow while waiting for the eBay Browse API credentials. It can
test the decision rules, image inputs, offline observations and review reports.
**It does not produce automatic card recognition without an image-capable
model or previously saved model observations.**

## 1. Tests — completely free and offline

In the pokemon-detector directory:

    python -m unittest discover -s tests -v
    node tests/page.test.js

No AI model or marketplace credential is needed.

## 2. Analyze photographs on your own computer

A listing file looks like:

    {
      "listing_id": "manual:001",
      "asking_eur": 100,
      "kind_hint": "binder",
      "title": "Binder from a local seller",
      "image_files": ["photos/binder-front.png", "photos/binder-page2.jpg"]
    }

Use one of two options:

### A. Free offline analysis of cached annotations

Create a JSON observation document (or export one from a previous AI
analysis) with the format documented by vision.py:

    {
      "kind": "binder",
      "summary": "Two visible cards. Quantities not verified.",
      "inventory_complete": false,
      "observations": [
        {
          "image_index": 0,
          "bbox_xyxy": [0.1, 0.1, 0.45, 0.48],
          "name": "Charizard ex",
          "set": "151",
          "number": "199/165",
          "language": "en",
          "finish": "holo",
          "condition": "unknown",
          "identity_confidence": 0.75,
          "condition_confidence": 0.2,
          "photo_confidence": 0.95,
          "flags": ["back_not_visible"]
        }
      ],
      "uncertainties": ["Back unavailable; sleeve obscures edges"]
    }

Names/numbers in this illustration are fictitious visual annotations, not
claims about specific photographs or real sale prices.

Run:

    python vision.py listing.json --observation saved_observation.json --catalog vision_catalog.json --out result.json

If the trusted catalog is unavailable, leave out --catalog and the
identity will remain unresolved. Valuations also remain unknown.

### B. Actual AI photo analysis (optional; can incur cost)

Use a compatible vision API or locally hosted multimodal provider:

    export VISION_API_KEY=your_key
    export VISION_MODEL=gpt-4.1-mini
    python vision.py listing.json --catalog vision_catalog.json --out result.json

For local providers, set VISION_API_URL to your own compatible loopback
chat-completions endpoint. You are responsible for model installation and
compatibility (JSON response_format plus image data URI support).

No paid API is called by option A.

## 3. Generate a private HTML report

    python review_report.py result.json --photo-dir photos --out review.html

The HTML contains card bounding boxes, catalog matching, flags,
unknown ROI and a human inventory reconciliation checklist.

Local photos are included only when --photo-dir is specified.
The report is saved locally and is not published to GitHub Pages.
Image names are taken from the manifest; place them directly in
--photo-dir regardless of input file subfolders.

If you used image_urls instead of image_files, the report references
those external images via HTTPS and your browser may load them.

Open review.html with any modern browser.

## 4. Measure accuracy against independently labeled photos

Build a JSON dataset of cases. Each case has case_id, kind, image_count,
ground_truth with image_index/bbox_xyxy plus known identity fields,
and prediction following the vision.py observation output.

Run:

    python vision_benchmark.py labeled_cases.json --out benchmark_report.json

Report includes object precision/recall, exact identity accuracy among
spatial matches, high-confidence mistakes and risk-flag precision/recall.
An optional --min-exact-accuracy parameter returns an error if the
measured accuracy is below your chosen threshold.

Important: synthetic fixtures only test the evaluation software.
Do not claim model accuracy until labeled *real* photos are collected
across sets, printings, languages, foils, lighting conditions, binders
and sealed boxes. Keep an unseen holdout set.

## 5. Duplicate cards across photographs

The inventory_review module reports conditional min/max visible unique
copies. Example: a Charizard in photo 1 and a Charizard in photo 2
could be one physical copy photographed twice or two different copies.
One image showing two non-overlapping identical cards suggests two
separate objects *if the detections are correct*.

The review report flags ambiguous groups. Quantity_verified is
always false until physically reconciled.

Do not multiply resale price by this range as though it were inventory,
and do not treat it as proof of authenticity, rarity or grading.

## What is still required before trading real money

- Independently verified recent sold transactions and variant-matched
  comparable prices, from authorized/licensed sources.
- Correct acquisition duties, shipping and platform fee inputs.
- Authenticity/condition verification by a qualified human where material.
- Backtesting the model on real sold outcomes, not only asking prices.
- Seller/reputation checks, return policy, location and liquidity.

The program **never buys automatically**; image-only results remain REVIEW
or REJECT even if a model expresses high confidence.
