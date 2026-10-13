# BIGSTEN Third-Party Software & Data Rights Register
Last reviewed from upstream GitHub metadata: 2026-10-12.

Purpose: make the eventual commercial SaaS legally maintainable. This is a
technical inventory, NOT legal advice or confirmation of marketplace-specific
commercial licensing. Reverify source versions at every release.

| Component / source | Role | Upstream license as observed | Integrated today? | Commercial action |
| --- | --- | --- | --- | --- |
| tcgdex/cards-database | Catalog identifiers, set and card metadata | MIT | Existing local catalog exporter | Preserve MIT copyright text; review rights to card artwork independently |
| opencv/opencv | Local contour image analysis | Apache-2.0 | Optional local_cv.py, not bundled | Pin dependencies; notices; audit transitive binaries |
| tesseract-ocr/tesseract | Printed text recognition | Apache-2.0 | Optional pytesseract wrapper and system binary | Ensure binary/system packaging and wrapper license review |
| roboflow/rf-detr (RF-DETR Nano, core) | Local optional fine-tuned card rectangle detector | Apache-2.0 core code/weight designation | Adapter, trainer and benchmark implemented, NO trained model included | Preserve Apache notices; only trusted local fine-tuned checkpoints; Plus/PML models are excluded; photos and training data require separate rights |
| rapidfuzz/RapidFuzz | Faster fuzzy text matching | MIT | NOT NEEDED: current catalog candidate suggestions use Python stdlib difflib | Optional only if profiling proves value |
| dylan7077/viridian | Inspiration for pHash/ORB and local grading experiments | MIT | NOT VENDORED, NOT IMPORTED | Can evaluate as optional future integration; preserve notices if code copied; do NOT present experimental grade as certified |
| jaredwins99/pokemon-tcg-scanner | Binder/scan ideas | No clear repo-root license identified | NO CODE COPIED | Request explicit license/permission before reusing source |
| clawdr/pokemon-scanner | Deal alert architecture inspiration | No clear repo-root license identified | NO CODE COPIED | No reuse without permission and independent API rights |

## Public research picture datasets (source metadata, not sublicensed Pokémon IP)

- Roboflow Pokémon card detector: https://universe.roboflow.com/tcg-card-dectector/pokemon-card-detector-gksmy (494 published images; dataset page CC BY 4.0).
- Roboflow Pokémon card binder: https://universe.roboflow.com/cardbinder/pokemon-card-binder (36 published images; dataset page CC BY 4.0).
- Roboflow Pokémon Scanner: https://universe.roboflow.com/pokemon-card-detection-a3etk/pokemon-scanner-bzqii (1,239 published images; dataset page CC BY 4.0).
- Wikimedia Commons Pokémon Trading Card Game category: each individual image has separate rights and attribution; the 24 listed files include logos/event photos, not all individual card photographs.

These are potential research inputs to local card-*detection* tests, not proof of individually licensed underlying artwork, authentic card identities, independent test distributions or commercial resale permissions. All actual image exports remain in gitignored private directories. See WEB_IMAGE_DATASETS.md for provenance-aware import.

## Separate source/content rights

- MIT/Apache copyright grants for software do not automatically authorize
  commercial use/redistribution of Pokémon card illustrations, logos,
  product packaging images, scanned cards from websites, API-fed commerce
  data, graded certificates, third-party listing photos, or branded assets.
- BIGSTEN may process user-supplied photographs with appropriate user rights
  and privacy terms, but must NOT copy them to a shared reference-card index
  without the required license/consent.
- Uploaded card photos in Local Alpha are processed temporarily on localhost.
  No actual user photos or receipts are committed to the public repository.
- Any SaaS price-comparison service must record specific provider contract
  status, allowable retention/cache window, geographical scope, ability to
  monetize derived comparisons and resale of raw data, and deletion rules.
- eBay developer approval does NOT automatically provide data use rights for
  commercial pricing/arbitrage analytics; require explicit permitted use.
- Avoid official-looking Pokémon or grading-company branding and descriptions
  implying endorsement.

## Commercial release checklist

[ ] Lock exact package versions, license files and hashes.
[ ] Generate software bill of materials (SBOM) and vulnerability scan.
[ ] Preserve MIT copyright and Apache attribution/NOTICE as applicable.
[ ] Verify transitive dependencies, model weight licenses and OCR distributions.
[ ] Record source and rights holder for every reference image in any pHash/ORB index.
[ ] Approve third-party market data provider terms for intended SaaS monetization.
[ ] Document GDPR privacy, retention, deletion, international transfer and vendor DPAs.
[ ] Vet product terms, customer claims, refunds, legal liability and consumer law.
[ ] Conduct penetration/security review before hosting.
[ ] Test separate customers cannot access each other's images, reports or purchases.

**Rule:** when licensing is unclear, omit the source and keep BIGSTEN functional
with permitted, verified local inputs. We can improve later without redesigning
the whole product because provider connections sit behind adapters.
