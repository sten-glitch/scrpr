# BIGSTEN Private Reference Index — pHash + ORB (P1 alpha)

This module matches local photographs against a catalog of *user-authorized*
reference photos using pHash to shortlist and OpenCV ORB to verify visual
similarity. No OpenAI, Claude, external AI API, eBay API or Internet call is
required at runtime.

**Important distinction:** a visual match is a CARD IMAGE CANDIDATE, NOT
verified card printing, foil, exact variant, authentic physical item, PSA slab,
condition or resale value. Similar art across rare/normal/reverse prints can
look nearly identical; those require manual examination.

## 60-second synthetic demo (no Pokémon card art)

If you only want to SEE the pHash + ORB engine before collecting lawful card
reference photos, install the optional packages once and run:

    .venv\Scripts\python.exe demo_reference_lab.py
    .venv\Scripts\python.exe local_app.py --port 8765 --catalog private/demo_catalog.json --reference-index private/demo_cards.sqlite

Open http://127.0.0.1:8765, choose "Single card", enter any title and a
positive placeholder EUR price, then upload:

    private/demo_queries/demo_query_A.png

The local application will show the visual match candidate. These are
machine-generated geometric test patterns, NOT genuine Pokémon cards.
A good match here does not demonstrate accuracy on real trading cards.
Generated demo files remain inside the gitignored private folder, never
committed to the repository. Re-running the generator refuses to overwrite.

## Preparation on Windows

Download the branch feature/pokemon-deal-reasoning-v1 of sten-glitch/scrpr,
open a PowerShell terminal inside the pokemon-detector directory.

    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements-local.txt

To use OCR, also install the Tesseract executable on Windows; place its
installation directory on PATH. OpenCV/pHash/ORB require no OCR executable.

Prepare your local trusted TCGdex metadata catalog (no artwork downloaded):

    git clone https://github.com/tcgdex/cards-database.git tcgdex
    .venv\Scripts\python.exe catalog_export.py --tcgdex tcgdex/data --out vision_catalog.json

The card catalog must include the exact identity_key and print/variant for
every reference photo. You can query vision_catalog.json to find a record
using a local text editor or script.

## Create YOUR OWN rights-cleared photos

Create directories inside pokemon-detector:

    private/
      reference-photos/
        my-photo-001.jpg
        my-photo-002.jpg
      reference-manifest.json

Only use your own card photos where you have sufficient rights for the
intended private/commercial use or photos explicitly licensed for indexing.
Simply owning a picture file, a card, or access to a website does not
necessarily grant commercial IP rights in the underlying artwork.

Write private/reference-manifest.json (replace IDs with exact entries from
vision_catalog.json):

    {
      "references": [
        {
          "reference_id": "myphoto_001",
          "identity_key": "tcgdex:sv03.5-199-holo-en-raw",
          "image_file": "my-photo-001.jpg",
          "rights_basis": "user_owned",
          "permission_reference": "SELF_PHOTO_001"
        },
        {
          "reference_id": "myphoto_002",
          "identity_key": "tcgdex:sv03.5-199-reverse-en-raw",
          "image_file": "my-photo-002.jpg",
          "rights_basis": "licensed",
          "permission_reference": "LICENSE_AGREEMENT_002"
        }
      ]
    }

Example IDs above are illustrative. Verify the chosen card and finish.
The program records your rights claim, but does not independently verify
permission or ownership.

Create the local feature database:

    .venv\Scripts\python.exe reference_matcher.py build --manifest private/reference-manifest.json --image-root private/reference-photos --catalog vision_catalog.json --out private/card_references.sqlite

The command refuses to overwrite an existing index; back up and delete the
old index yourself before rebuilding. Do NOT commit private/ or photos/.
The database contains only reference IDs, pHash codes, compressed ORB
descriptors, identity keys and human-entered rights provenance. No original
reference image files are stored in the database.

## Match a single card photo from your computer

    .venv\Scripts\python.exe reference_matcher.py match --index private/card_references.sqlite --image private/my-test-photo.jpg

Results:

- VISUAL_CANDIDATE: visual features favor one reference, NOT proof of print.
- AMBIGUOUS: more than one different card/variant looks similarly close.
- ABSTAIN: inadequate visual agreement; BIGSTEN will not guess a card ID.

All results require independent physical verification, especially if
multiple cards share artwork, have foil differences, slabs, stamps or
different languages.

## Use the full BIGSTEN browser app

    .venv\Scripts\python.exe local_app.py --port 8765 --catalog vision_catalog.json --reference-index private/card_references.sqlite

Open:

    http://127.0.0.1:8765

Upload your own photo(s). BIGSTEN will:
1. Detect likely card rectangles using OpenCV.
2. Read provisional text and collector numbers with Tesseract (if available).
3. Compare card crops to your private pHash + ORB reference index.
4. Show visual candidates and disagreement/abstention, separately from catalog
   textual suggestions, Listing Truth Engine findings and the financial
   Evidence/Reasoning assessment.

If one close-up photo contains no detected rectangle and the listing is
single/graded, the app now attempts a **whole-image** reference comparison.
This does NOT claim a card was detected; it only provides a possible match.

## Cost, throughput and rights

- No usage-based image model fees. CPU, laptop RAM and electricity are yours.
- pHash/ORB does not require subscription access but large reference
  libraries need performance benchmarking and consistent high-quality photos.
- Current reference index limit: 4,000 photos, top-12 hash retrieval, ORB
  verification, one image per canonical key or multiple with distinctive
  reference IDs. Not tuned for millions of card variants or real marketplace
  imaging conditions.
- Reference photos remain in private/reference-photos; the database stores
  derived features only.
- No licensing shortcut: private test photographs are not automatically
  commercially redistributable. Software MIT/Apache license does not grant
  Pokémon artwork or marketplace data rights.

## Accuracy evaluation still required

- At least 50 independently labeled real listing photos to start the pilot,
  including front/back, binder pages, graded slabs, blurry/rotated/glare,
  different foil prints with identical artwork and non-Pokémon negatives.
- Maintain a separate unseen holdout set; measure recall at an explicit
  wrong-identification limit, abstention rate and confusion of foil/stamps.
- Use vision_benchmark.py for object/identity measures and add a reference
  retrieval benchmark on human-labeled photos before public launch.
- No source-specific price ingestion from eBay until authorized commercial
  rights and API access have been confirmed.

## Relevant code

reference_matcher.py — private index and candidate retrieval
local_cv.py — OpenCV/OCR provisional detection
catalog_candidates.py — catalog OCR suggestion (not automatically verified)
local_app.py — localhost-only web API
local_app/index.html and app.js — browser interface
tests/test_reference_matcher.py — synthetic pHash+ORB tests
tests/test_local_cv_detection.py — synthetic binder-contour tests


## Run an honest held-out retrieval benchmark

Collect *different physical photographs* from your reference photos. Do not
reuse, resize or copy the indexed reference photos as test input. Put them in
private/evaluation-photos (private paths are excluded from public Git).

Create private/reference-holdout.json, for example:

    {
      "cases": [
        {
          "case_id": "independent-positive-001",
          "kind": "single",
          "split": "holdout",
          "image_file": "my-other-photo-001.jpg",
          "expected_identity_key": "tcgdex:sv03.5-199-holo-en-raw",
          "annotation_verified": true,
          "annotation_reference": "my-physical-inspection-record-001"
        },
        {
          "case_id": "independent-negative-001",
          "kind": "negative",
          "split": "holdout",
          "image_file": "unrelated-item-photo.jpg",
          "expected_identity_key": null,
          "annotation_verified": true,
          "annotation_reference": "my-inspection-record-002"
        }
      ]
    }

All example card references are illustrative. Enter the exact real identity
only after examining the physical card/printing. Add separate cases for
visually near-identical reverse/normal/holo variants. For a binder image,
you may supply bbox_xyxy normalized crop coordinates to test one reviewed
card in a page.

Execute:

    .venv\Scripts\python.exe reference_benchmark.py private/reference-holdout.json --index private/card_references.sqlite --query-root private/evaluation-photos --reference-manifest private/reference-manifest.json --reference-image-root private/reference-photos --out private/reference_accuracy.json

Outputs known-card recall, wrong-identity rate, false-match rate on negatives,
accepted-candidate precision and ABSTAIN / AMBIGUOUS frequency, with a separate
category breakdown. A byte-identical reference/query image is rejected to
reduce training/test leakage; this does not detect resized or rephotographed
near-duplicates, so labeling and split discipline are still essential.

The benchmark deliberately **does not** produce a certified success rate, a
valuation accuracy claim, or an investment recommendation. Actual market
performance requires authorized completed-sale and real resale outcome data.
