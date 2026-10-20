# BIGSTEN Photo Ground Truth Lab — real-picture validation (P1)

**Purpose:** annotate independent user-authorized card photos, compare the local
pHash/ORB reference matcher to those human-attested labels and measure real
mistakes. NO commercial AI, eBay API, automatic paid dataset or public upload.

**IMPORTANT: No real Pokémon photos were uploaded to GitHub or tested in this
branch.** Synthetic CI tests show that the software runs; they are NOT a
real-world accuracy benchmark.

## 1. Start labeling on Windows

Get the branch:

    git clone --branch feature/pokemon-deal-reasoning-v1 https://github.com/sten-glitch/scrpr.git
    cd scrpr\pokemon-detector

Create a PRIVATE photo directory and add photographs you captured yourself,
or obtained with appropriate permission. Do not add secrets, buyer names or
confidential receipts to these folders:

    mkdir private\evaluation-photos

Copy JPG, PNG or WebP images into that folder; each file <= 5 MiB.
Images can be of one card, graded slabs, binder pages, lots or unknown objects.
All filenames must be DIRECT children of that folder, without symlinks.
No photographs are shipped inside this source-code repository.

Run the annotator (Python 3.12+; viewing/labeling photos does not require
OpenCV, Tesseract or any paid AI):

    py -3 photo_review_server.py --photos private/evaluation-photos --out private/reference-holdout.json --port 8766

Open:

    http://127.0.0.1:8766

For exact Pokémon variant suggestions, supply your **local metadata-only**
catalog with --catalog vision_catalog.json. The catalog itself can be
generated with catalog_export.py from the TCGdex repository; see
PRIVATE_REFERENCE_MATCHING.md.

The server binds to 127.0.0.1 and uses same-origin checks. It does not
expose photos to the cloud or save them in GitHub. It only reads approved
files; human labels are written atomically to private/reference-holdout.json.
The application has NO login and MUST NOT be publicly deployed or tunneled.

## 2. Label each photograph and card

1. Select the photo in the browser.
2. For a binder, drag a rectangle around one card. Save each distinct card
   region as a separate case with its own case_id and non-overlapping box.
   For an isolated close-up photo, leave the box blank to use the entire image.
3. Choose single / binder / lot / graded / sealed / negative.
4. Mark **Real photograph** if it is an independent real-world photo, or
   **Synthetic demo** if generated. Unclassified photos never pass the
   real-photo validation milestone.
5. Enter the **EXACT expected identity_key**, determined independently after
   examining the actual item, grade/foil/edition and card catalog. Do not
   choose from AI predictions or trusting the seller title. If the card is
   outside the approved reference index or is unknown/non-Pokémon, choose
   Negative and leave expected identity NULL.
6. Enter reviewer name/ID, the independent inspection record reference and
   notes. Explicitly check the human verification checkbox.
7. Save. BIGSTEN records SHA-256 of the original photo. The page shows
   annotated cases and lets you edit/review them again. Existing annotations
   are NOT silently accepted if photo bytes later change.
8. Choose the next photo; the progress bar counts **distinct real photos**
   separately from card labels. A binder with nine cards counts as one photo,
   not nine independent test photographs.

The manifest is compatible with reference_benchmark.py. It has the schema:

    {
      "cases": [
        {
          "case_id": "physical_card_001",
          "image_file": "front-photo-001.jpg",
          "kind": "single",
          "split": "holdout",
          "photo_origin": "real_photo",
          "expected_identity_key": "EXACT_CANONICAL_KEY",
          "bbox_xyxy": null,
          "annotation_verified": true,
          "reviewer": "reviewer_001",
          "annotation_reference": "inspection_001",
          "photo_sha256": "computed by BIGSTEN"
        }
      ]
    }

For a negative case, set expected_identity_key to JSON null. For a binder
crop, use normalized bbox_xyxy [left, top, right, bottom] with 0–1 coordinates.
The Web UI writes this JSON: don't manually copy the illustrative hash above.

## 3. Run the independent visual benchmark

You need a separate PRIVATE index of authorized **reference** card photos,
already built using reference_matcher.py. See PRIVATE_REFERENCE_MATCHING.md.
Do NOT include any held-out photo in that reference index. Do not create
hold-out images by merely resizing, brightening or cropping original
reference photos; those would invalidate reported real-world performance.

Install optional free vision dependencies for the **benchmark**:

    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements-local.txt

Now execute (the full command can be put on one line):

    .venv\Scripts\python.exe reference_benchmark.py private/reference-holdout.json --index private/card_references.sqlite --query-root private/evaluation-photos --reference-manifest private/reference-manifest.json --reference-image-root private/reference-photos --out private/reference_accuracy.json --html private/reference_accuracy.html

Open private/reference_accuracy.html in your browser after the benchmark
finishes. The report has offline cards, breakdowns and a case-by-case mistake
list. It does not load scripts or download any external images.

Results include:
- known-card recall, wrong identity rate and candidate precision
- false-match rate on images outside the indexed reference set
- ABSTAIN and AMBIGUOUS rates, rather than quietly excluding unknown cases
- distinct evaluated REAL photographs vs total card regions/cases
- breakdown by photo kind (raw single, slab, binder, sealed, negative)
- changed photo detection (SHA-256), duplicate-region rejection, and
  exact reference/query image duplicate rejection
- a P1 sampling gate: at least 50 distinct real photos, >=5 negative cases,
  at least 3 categories and all photo origins reviewed.

Passing that minimum sampling gate yields SAMPLE_READY_FOR_MANUAL_REVIEW, NOT
a claim that BIGSTEN is accurate, certified, or ready for commercial launch.
Unseen distribution shift, selection bias, near-duplicate leakage and
counterfeit risk still require manual expert review.

## 4. Real-photo capture protocol

Build a representative pilot set of **50 or more independent photographs**.
Do not cherry-pick only photos in which BIGSTEN appears to work. Include:
- modern and vintage raw singles, both easy and difficult editions/variants
- visually near-identical normal, holo, reverse and alternate-language cards
- slabbed PSA/BGS/CGC with labels, reflections and oblique angles
- multi-card binder pages with per-card boxes and partly obscured cards
- sealed products and packaging; do not infer contents/authenticity
- at least five negatives: products not in the reference index, non-Pokémon
  items, misleading advertisements or unknown collectibles
- glare, blur, tilted photos and low-quality marketplace-like framing

Annotate independent of the scanner's output; ideally a second reviewer
checks high-value or disputed labels. Keep proof of authorization for
marketplace-derived photos and do not share copyright material to the
public repository. Each physical product/photo capture session should be
tracked outside the dataset to avoid inflated confidence from correlated
images. Treat identity and grade labels as claims requiring expert review.

## 5. Release gates

At least 50 real distinct photos is only the BEGINNING:
- no false authenticity or grade certifications
- conservative treatment of unclear editions/foil
- predeclared thresholds for wrong-identity and false-match rates, assessed on
  an untouched holdout, not endlessly tuned to a reused test set
- documented source/image/data rights for a commercial SaaS
- authorized data feeds, real logged costs and verified resale outcomes
- independent privacy/security review before any public deployment

Never commit files in private/; the directory is gitignored. Keep backup
copies securely and observe actual provider/photographer rights.
