# BIGSTEN — Online Pokémon Image Datasets (12 October 2026)

## Verified public sources

| Source | Listed images | License shown | Use |
| --- | ---: | --- | --- |
| [Roboflow: Pokémon card detector](https://universe.roboflow.com/tcg-card-dectector/pokemon-card-detector-gksmy) | 494 | CC BY 4.0 | Card bounding-box detection |
| [Roboflow: Pokémon card binder](https://universe.roboflow.com/cardbinder/pokemon-card-binder) | 36 | CC BY 4.0 | Multiple cards in binder pages |
| [Roboflow: Pokémon Scanner](https://universe.roboflow.com/pokemon-card-detection-a3etk/pokemon-scanner-bzqii) | 1,239 | CC BY 4.0 | Segmentation polygons, convertible to card boxes |
| [Wikimedia Commons: Pokémon Trading Card Game](https://commons.wikimedia.org/wiki/Category:Pok%C3%A9mon_Trading_Card_Game) | 24 mixed media | Individual CC licenses | Scene photos, negatives, hard examples |

These are source-reported totals, NOT downloaded and individually verified
real Pokémon images, unique products, or independent ground-truth card IDs.
Dataset export may be gated by the publisher's account/API permissions.
Published photo licenses do not automatically license embedded copyrighted
Pokémon artwork for commercial redistribution, and do not cover card pricing
or marketplace data.

BIGSTEN source code:
- external_photo_sources.py: Wikimedia Commons MediaWiki discovery/private
  download and official Roboflow authenticated dataset export.
- external_detection_benchmark.py: evaluate local OpenCV detector against
  YOLOv8 card-box annotations; also accepts segmentation polygons as boxes.
- prepare_web_photo_review.py: sample up to 50 source images from held-out
  TEST or VALID folders for independent photo/variant labeling.
- photo_review_server.py: human-reviewed card identity annotation on localhost.
- reference_benchmark.py: separate exact-card identity benchmark for pHash/ORB.

**The source images are never committed to the public repository.** Store all
photos/annotation files in the ignored private directory.

## Small no-account sample already exercised on GitHub Actions

A one-time public-source smoke test successfully fetched and processed
**seven genuine online photographs** (four licensed Commons candidates
and three public Roboflow example thumbnails), yielding **two provisional
card-like contours**. See the [GitHub Actions run](https://github.com/sten-glitch/scrpr/actions/runs/38279892391).
The images were discarded when the runner exited. Those two detections are
NOT manually verified cards; this is NOT a recognition precision score.
The one-time network step was removed from ongoing CI afterwards.

To collect the same three public Roboflow preview thumbnails locally
without creating a Roboflow account:

    py -3 external_photo_sources.py previews --dry-run
    py -3 external_photo_sources.py previews

They are saved privately to private/web-research/roboflow-previews alongside
a SOURCE_ATTRIBUTION.json manifest. They are small public thumbnails and
are NOT a substitute for full-resolution, licensed, expert-labeled photos.
The dataset-page CC BY notice does not automatically clear embedded card art.
On Windows, start-web-photo-research.bat now attempts these three previews
and Commons research photos in sequence.

## A. Download Commons photographs — no account required

In the pokemon-detector folder on Windows:

    py -3 external_photo_sources.py sources
    py -3 external_photo_sources.py commons --max-images 12 --dry-run
    py -3 external_photo_sources.py commons --max-images 12

Potential JPG/PNG/WebP photos and author/license attribution are stored under:

    private/web-research/commons/
      commons_*.jpg
      SOURCE_ATTRIBUTION.json

The script uses Wikimedia Commons official JSON API and Wikimedia HTTPS
image hosts only, filters recognized CC BY/CC BY-SA/CC0/public-domain
photo licenses, retains author and license metadata, and downloads files
with size/signature limits. It makes NO claim that each photo actually
contains one readable Pokémon card; the category includes events, people,
collecting scenes and logos.

Some Commons photos have copyright notices for card-art content that is
considered only de minimis within the *original* scene. Cropping around
Pokémon artwork may lose that exception. Review every image page and
embedded IP permissions before commercial use.

To label an approved local set independently:

    py -3 photo_review_server.py --photos private/web-research/commons --out private/commons-photo-holdout.json --port 8766

If Wikimedia blocks/rate-limits a request, do not circumvent restrictions.

## B. Larger Roboflow datasets — official provider export

Use the provider's account/API authorization; the SDK is a separate
optional install and export availability depends on provider permissions.
No unauthenticated scraping or bypassing access restrictions.

    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements-local.txt
    .venv\Scripts\python.exe -m pip install roboflow

In PowerShell, set YOUR key for this shell session; do not share it in chat
or commit it to GitHub:

    $env:ROBOFLOW_API_KEY = Read-Host "Paste your own Roboflow API key"

Now choose one public source:

    .venv\Scripts\python.exe external_photo_sources.py roboflow --source detector
    .venv\Scripts\python.exe external_photo_sources.py roboflow --source binder
    .venv\Scripts\python.exe external_photo_sources.py roboflow --source scanner

The importer uses the documented official Roboflow SDK to fetch public
dataset version 1 as YOLOv8 under private/web-research/roboflow-<source>.
Try detector first. The download refuses to overwrite existing datasets.
If the provider requires a plan or denies access, stop and respect it.

Expected export structure (publisher may vary slightly):

    private/web-research/roboflow-detector/
      data.yaml
      test/images/
      test/labels/
      train/images/
      train/labels/

Some exports have only valid rather than test; choose the split that exists.

## C. Test actual card detections

The detection benchmark compares OpenCV card contour predictions with the
publisher's YOLO bounding-box labels at IoU >= 0.50 and reports recall,
precision, missed cards and false detections. It never claims card ID,
edition, foil, slab authenticity or reliable financial data.

    .venv\Scripts\python.exe external_detection_benchmark.py private/web-research/roboflow-detector --source detector --split test --max-images 400 --out private/detector-box-accuracy.json --html private/detector-box-accuracy.html

Open private/detector-box-accuracy.html locally for the case-by-case audit.
You can use --source binder or --source scanner with the corresponding
downloaded folder. The scanner's segmentation polygons are reduced to
bounding rectangles; polygon-mask accuracy is not measured.

Only test/valid splits are accepted; train images are refused. The program
checks exact-image train/test duplicates, but near-duplicate augmented
images can remain and require manual inspection. Publisher labels themselves
may be wrong; this is an external annotation benchmark, not a calibrated
independent certification.

## D. Prepare up to 50 web images for human card-identity review

Copy a deterministic sample of photo files from the independent provider
holdout split, while retaining source provenance and not inventing IDs:

    .venv\Scripts\python.exe prepare_web_photo_review.py private/web-research/roboflow-detector --source detector --split test --count 50 --out private/web-photo-review

Images remain inside private/web-photo-review. Existing nonempty folders
are protected. Source photos byte-identical to train examples are skipped.
The source boxes are NOT an authority for exact card printing identity.
A provider photo license is NOT an automatic right to commercially
redistribute Pokémon art.

Start manual identity review:

    py -3 photo_review_server.py --photos private/web-photo-review --out private/web-photo-holdout.json --port 8766

Open http://127.0.0.1:8766 and validate each card's physical identity,
edition, language, finish and condition using independent evidence. If
unknown/not represented in the reference index, mark Negative. Avoid
auto-confirmation using seller title or metadata. A binder is multiple
objects inside ONE photograph, not multiple independent photos.

## Important status distinction

- Found online: public sources reporting 494 + 36 + 1,239 images and
  Commons category reporting 24 media files.
- Built: acquisition scripts, source/provenance tracking, private sampling,
  box detector benchmark, human labeling workflow.
- NOT yet performed here: actual photo binary acquisition (execution
  environment blocks direct image downloads), visual inspection of individual
  downloaded photos, independently verified product IDs and **real-world
  card-recognition accuracy**.
- Commercial SaaS launch still requires legal/rights review, real photo
  holdout calibration, and authorized price datasets.

No dataset's online image count is a model accuracy score.
