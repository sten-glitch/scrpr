# Implementation status — 2026-10-15

## Delivered and tested locally

- Audit/dependency map before implementation; previous local changes preserved.
- Dedicated branch `feature/graded-unique-supply`, based on PR #1 head `7dbe3398`.
- Graded primary local landing page; legacy workbench retained.
- Unicode-safe exact query engine, explicit EN/JA language, ambiguous candidates.
- Local certificate reader with evidence, original text, safe decoding/orientation,
  bounded concurrency; missing engine explicit. Parsing tested on text fixtures.
- Certificate-level grouping with provenance/conflict quarantine, same-item
  dedup across eBay views, recycled-image signals, unresolved counts and bounds.
- New local endpoints and saved reports in existing workspace SQLite.
- Official eBay client with environment isolation, bounded pagination/retries,
  token expiration, request budgets, redirect blocking and coverage metadata.
- Local cache and injectable-provider cost reservation ledger; paid disabled.
- Repeatable certificate manifest benchmark and synthetic logic performance harness.

## Partial / not acceptance-complete

- Real certificate reading cannot be demonstrated without Tesseract and images.
- Catalog handling supports Japanese data; the old exporter does not yet supply it.
- Image-to-exact-query and automatic exact classification of eBay search hits are
  not connected. Search hits remain unresolved rather than counting false matches.
- Supply JSON import trusts explicit reviewer attestations. No registry verifier.
- pHash/ORB probable physical duplicate calibration and queue infrastructure pending.
- Real marketplace permissions, sold-price valuation and full query-to-supply live
  demonstration not available. No real listing count or market opportunity claimed.
- Dataset/license approval, 50-image real benchmark (then 200), dependency
  vulnerability scan, full native memory measurements and data retention controls
  remain outstanding. `pip check` passed; it is not a vulnerability scan.
- RF-DETR remains experimental; no graded weights trained or benchmarked.

## Costs and external actions

Final validation: 342 tests, 339 passed, 3 Windows symlink skips; JavaScript syntax,
dashboard core and pip dependency consistency passed. Additional system Python
run passes with 45 optional-dependency skips (335 tests). Browser verified local
query, missing Production credentials, missing OCR, synthetic 5-listing supply
import (2 certificate groups, 1 unresolved, conditional range 2–3) and JSON export.

Zero paid AI calls. No subscriptions, purchases, deployment, merge or credential
changes. Local compute cost depends on electricity and runtime; not measured in money.
Live eBay searches not run because environment credentials absent. All API tests
mocked. Existing PR #1 remains draft; new changes are local until explicitly published.

## Next engineering priorities

1. Install/configure local OCR and collect rights-cleared graded-label benchmark.
2. Configure eBay Sandbox/Production variables privately and run read-only smoke tests.
3. Import trusted English/Japanese catalog and connect reviewed photo/query candidates.
4. Resolve exact identity and cert evidence for live hits, then demonstrate observed supply.
5. Compare OCR variants and RF-DETR on identical labels; measure targets instead of assuming them.
