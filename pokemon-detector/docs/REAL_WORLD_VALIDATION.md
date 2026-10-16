# Real-world validation — reproducible commands

Run from `pokemon-detector` using `.venv\Scripts\python.exe`.

## Credentials

Copy `.env.example` to `.env` only when `.env` does not exist. Enter App ID (Client ID) and Cert ID (Client Secret) from the matching Sandbox/Production Application Keys. Never enter Dev ID or an OAuth token instead. `local_config.py` reads only the five eBay keys, does not interpolate/execute values and preserves existing process variables. Restart the app after changing keys already loaded into its process. Verify presence only with `python local_config.py`. `.env` is ignored and is never served by the localhost static-file allowlist. This is a local plaintext configuration protected by the user's filesystem permissions, not an encrypted secret vault.

## OCR and catalog

Run `powershell -File setup-tesseract.ps1`. Installer version is pinned; the official tessdata_fast revision and English/Japanese file SHA256 values are pinned. Windows installation may require elevation according to local policy. The actual verified installation is under Program Files. The app discovers it without a global PATH change. `BIGSTEN_TESSERACT_CMD` overrides the executable; `BIGSTEN_OCR_LANG=eng+jpn` enables both languages (default `eng` for certificate digits). No paid AI setting is loaded from the eBay file.

Run `python catalog_download.py --set en:base1 --set ja:PMCG1 --out private/catalog-en-ja.json`. This adapter supplies the existing catalog schema and resolver; it does not replace the existing TypeScript exporter. The app automatically loads this local catalog when no explicit --catalog is supplied. Each detailed edition has a distinct identity and source hash. Missing detailed variants are skipped and counted. The two-set subset does not cover all modern/promotional cards. It downloads metadata only, not artwork or slab images.

Sources: https://tcgdex.dev/rest/set and https://tesseract-ocr.github.io/tessdoc/Installation.html.

## Live API verification

After entering keys: `python validate_ebay_live.py --production-searches --out private/ebay-live-validation.json`.

This performs OAuth for both environments, tests in-memory token reuse, and caps Production Browse calls at 20 including retries. Five queries across GB/US/DE request one page of at most 20 results each. Fixed-price offers shipping to Romania only. Reports contain counters and sanitized exception types, never tokens or raw HTTP bodies. No image rights are inferred from API access. Metadata-only aggregation leaves certificates unresolved.

Token expiry, refresh, scope/header construction, 401 retry, 429 handling and page limits have offline regression tests; a successful live authentication does not prove every error scenario occurred live.

## Rights-cleared image benchmark

Prepare `private/benchmark/images` and `private/benchmark/manifest.json`. The initial manifest is intentionally empty: no fabricated images, labels or reviewers. Use at least 50 independent clear-label slab photographs, then 200+ covering glare, blur, rotated photos and multiple graders. Separate physical slabs across training and test splits. Record permission evidence separately and reference it in rights_basis.

Each case requires case_id, relative image path, sha256, grader, literal certificate_number (string preserving zeros), optional grade, clear_label, is_real, used_for_training=false, independent_group_id, rights_basis, reviewer and truth_source. The reviewer must actually transcribe and review the original photograph; do not copy the OCR prediction as truth.

Run `python certificate_benchmark.py private/benchmark/manifest.json --image-root private/benchmark/images --output private/benchmark/ocr-results.json`. Empty data fails validation. Per-grader exact match, grader recognition, optional grade recognition, failures, latency and Python allocated memory are exported. Python allocation memory excludes native OCR; the separately measured installation smoke test samples process-tree RSS.

For independently labeled duplicate pairs, prepare JSON with listings and pairs. Each pair has a and b as [marketplace,item_id], same_physical_item boolean, reviewer and truth_source. Run `python benchmark_supply.py private/benchmark/pairs.json --out private/benchmark/pair-results.json`. Ground truth must be independent from the engine's accepted certificate assertions. Precision/recall and false-merge metrics use only labeled pairs; missing denominators return null.

Canonical image identity accuracy remains unmeasured: no image-to-identity labeled holdout or trained slab/label checkpoint exists. RF-DETR remains optional and disabled by default. Do not infer production quality from parser fixtures or repeated synthetic OCR images.
