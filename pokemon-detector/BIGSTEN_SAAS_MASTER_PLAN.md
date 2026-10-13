# BIGSTEN Commercial SaaS Master Plan — 12 October 2026

## Product decision

Build BIGSTEN Collection Intelligence as an independent commercial SaaS. Initial market is Pokémon TCG collectors, specialist dealers and small resellers; preserve a collectible-agnostic core for later expansion. Start with local alpha, then private SaaS beta, then subscription launch after explicit intellectual-property, commercial-data and security reviews.

Core promise: upload a card, binder or listing; BIGSTEN shows what is actually visible, what the seller claims, contradictions, uncertain item identity/condition/quantity, and only evidence-backed valuation. Never advertise guaranteed profitability or automatic authentication/PSA grades. No automated purchasing.

## Implementation status — 12 October 2026

**P0 built:** localhost web alpha, seller-claim checks, provisional local OCR
and contour detection, TCGdex metadata suggestions, photo review, offline
evidence/reasoning and private reports.

**P1 engineering started:** user-authorized private pHash + ORB image-reference
index, candidate matching from detected rectangles, full-frame single-card
fallback, explicit AMBIGUOUS / ABSTAIN results, synthetic offline demo and a
human-attested held-out retrieval benchmark that rejects byte-identical
train/test photos.

**Not accomplished:** no representative real trading-card dataset yet, no
reported real-world visual precision, no provider-approved commercial price
feed, no hosted accounts/billing/privacy protections, and no verified
profitable investment strategy. P1 is NOT complete until independent photo
accuracy and licensed-data gates pass. Current GitHub PR remains draft.

### P1 Ground Truth Lab — added 12 October 2026

- Local Photo Review Lab now runs at localhost port 8766, with an allowlisted
  folder of independently permissioned physical photographs and a simple
  click/drag bounding-box reviewer interface for single cards and binders.
- Human-confirmed exact catalog keys, negative/unknown cases, grader/reviewer
  reference, source photo provenance and SHA-256 integrity are retained
  atomically in a PRIVATE JSON file. No images or private annotations were
  included in the public GitHub repository.
- The independent pHash/ORB benchmark counts unique photos separately from
  per-card binder crops, rejects repeated/overlapping regions and source-file
  duplicates, and refuses changed photos when label SHA-256 is present.
- The benchmark explicitly differentiates real-world photos from generated
  synthetic test data. At least 50 distinct **real** photos, five negatives,
  three categories and reviewed provenance are a sampling gate only—not
  verified precision or authorization to monetize.
- An offline static HTML benchmark report exposes cohort errors and per-case
  wrong identities, with no third-party CDN, photo content or external links.
- The working annotation steps and test methodology are in PHOTO_REVIEW_LAB.md.

**Remaining blocker:** No real collected/permissioned 50-photo dataset has
been supplied or independently labeled yet. The P1 performance/accuracy
gate therefore remains OPEN; CI success is not proof of market performance.

### P1 research image discovery and import (12 October 2026)

Discovered three publicly listed Roboflow image datasets (494 card-detector, 36 binder, 1,239 scanner images; per-page CC BY 4.0 dataset terms) and a Commons category with 24 mixed media files. Built legal-source registry, optional official Roboflow SDK download requiring authorized credentials, Wikimedia Commons metadata/license-driven importer, YOLO card-box IoU benchmark, and private export-to-human-review sampling. The tools **do not** assert that photos have been downloaded in this environment, source labels are perfect, commercial card-art rights are cleared, or these datasets measure exact card printing identity. See WEB_IMAGE_DATASETS.md.

### P1 RF-DETR Nano pilot — 13 October 2026

Implemented an optional adapter for Apache-2.0 RF-DETR Nano, strictly
requiring a **trusted local checkpoint fine-tuned on an explicit trading-card
class**. A generic COCO pre-trained model cannot be used to claim card
detection. Added an opt-in training launcher that audits YOLO train/valid/test
splits for exact byte duplicates, user-permission attestation and a private
checkpoint destination; CPU training requires explicit opt-in. The local paired
benchmark uses exactly the same held-out YOLO photos, photo SHA-256, bounding
box labels and IoU threshold for OpenCV and RF-DETR. It records TP/FP/FN,
precision/recall/F1 and detector inference timing per image and produces a
private static HTML/JSON comparison. Simulated detections are used in CI;
**no trained card model, genuine RF-DETR performance score, verified card
identification rate or commercial artwork license exists yet**. The P1
accuracy/data license gate remains OPEN. See RFDETR_EXPERIMENT.md.

## Delivery roadmap and release gates

| Phase | Planning window | Shippable outcome | Gate |
| --- | --- | --- | --- |
| P0: code and local app | Week 1 | Truth Engine; local-only web UI; image/observation input; report; end-to-end tests; dependency policy | CI passing, contradicted PSA labels flagged, zero paid services required, no public deployment |
| P1: local vision alpha | Weeks 2–3 | OpenCV image detection, Tesseract OCR, exact TCGdex matcher, binder quantity reconciliation; optional Viridian pHash/ORB integration | 50 diverse annotated real photos; detection and identity metrics reported; no unverified automatic matches |
| P2: authenticated private beta | Weeks 4–6 | Secure accounts, per-user data isolation, scoped file storage, deletion/retention, safe queue/jobs, monitoring, usage quotas, Stripe test mode | Security/privacy/third-party-rights review and at least three pilot users |
| P3: paid SaaS pilot | Weeks 7–10 | Paid subscriptions, plan limits, support workflow, invoice/tax integration, licensed market data, calibrated reliability measures | Contract/legal gates, billing test success, measured real-world utility |
| P4: expansion | Week 11 onward | Sports cards/other collectibles, licensed data integrations, broader opportunity radar | Traction and unit economics justify expansion |

These windows are targets, not delivery guarantees.

## Initial commercial offer

ICP: collectors, EU/UK Pokémon resellers and niche shops. Initial features: photo upload, catalog identification, seller-claim validation, risk/unknowns, buyer review checklist, reference pricing only when provenance permits, private reports. Distinguish sellers asking price, guide price, auction hammer price, buyer-inclusive realized price and actually documented comparable sale. No inference of market-wide sell-through from a small sample of sales.

Pilot pricing hypotheses (not committed pricing): Collector 9–15 EUR/month; Pro 25–49 EUR/month; Dealer quota-based custom. Interview 3–5 prospects before locking pricing. Track time saved, corrections made, false positives, scans per active user and cost per processed photo.

## Technical architecture

- Browser web frontend: local alpha first, then secure commercial UI.
- API layer: typed validation, explicit costs and retention, authentication/tenant checks for SaaS.
- Vision worker: OpenCV contours, optional Tesseract OCR, reference-image matching; paid multimodal only after pilot benchmark demonstrates need.
- TCGdex catalog: exact printing, number, foil, language, raw vs graded. Catalog identity must not be mistaken for authenticity.
- Listing Truth Engine: title/description claims vs independent visual/catalog evidence; contradiction, inconclusive, consistent, missing information.
- Market Evidence: independently authorized/licensed completed sales; proper provenance and date windows.
- Reasoning Engine: cost waterfall, risk blockers, fair price confidence, ROI only when enough verified evidence. Human approval required.
- Storage: local read-only/in-memory for alpha; per-tenant PostgreSQL and private object storage for SaaS.
- Operations: observable async jobs, idempotent task keys, upload limits, budget caps, rate limits, incident controls.

Suggested hosted stack: React/Next.js, Python FastAPI, Postgres, managed authentication, secure object storage and monitored queue; evaluate Railway when moving to private beta. None of these are a dependency of the local alpha.

## Open source, licensing and IP

Licenses verified on GitHub October 12, 2026:
- TCGdex cards-database: MIT
- Viridian: MIT
- RapidFuzz: MIT
- OpenCV: Apache-2.0
- Tesseract: Apache-2.0
Keep license texts/third-party attribution when distributing their software. Recheck versions, transitive dependencies, weights and commercial permission before packaging; document software bill of materials.
Other publicly visible card-scanner repositories without an identified license are study references only, not code to copy.
A GitHub software/data license does NOT automatically license Pokémon artwork, logos, card scans, marketplace data or third-party photographs. Keep user-owned photos private; secure appropriate permission/licensing for commercial feeds, price history, imagery, caching and derived analytics. Verify eBay-specific intended commercial use in writing before enabling any paid SaaS arbitrage pricing feature. Use BIGSTEN branding; no false official Pokémon affiliation. Engage qualified legal review before public launch.

## Repository boundary before commercialization

The existing sten-glitch/scrpr repository is PUBLIC. Source code in this
draft PR, including the alpha and domain-logic design, is therefore visible
to anyone, even if it is not an open-source license grant. Never commit
proprietary private datasets, buyer information, receipts, model weights
with limited distribution, keys or competitive internal roadmap details.
Before developing customer accounts, billing and hosted proprietary modules,
split the product into a PRIVATE BIGSTEN application repository, and leave
scrpr as a public research/detector or demo repository. Reuse verified
components with appropriate license notices.

Commercial SaaS backend and user data must not be deployed from the public
alpha directly. A separate private deployment and access-control review are
release gates. Changing repository visibility alone does NOT remove prior
publicly accessible code history.

## Security and privacy release gates

Local alpha binds ONLY to localhost; no accounts, no remote hosting and no claim that its storage is multi-tenant-safe.
Before commercial SaaS: enforce auth and ownership checks for every image/report, segregate tenant data, protect secrets, TLS, malware and decompression/pixel limits, upload and AI spending quotas, EXIF handling, provider legal terms, deletion/retention, audit logs without personal-data leaks, encrypted backups, HTTPS, verified terms/privacy policy, GDPR data-subject processes, DPA and applicable consumer cancellation/payment rules. Test penetration/abuse paths and recoverability.

## Acceptance criteria

- P0: offline tests demonstrate that listing title mentioning PSA 10 cannot override raw image or missing slab evidence; non-Pokémon contexts do not trigger naive false positives; unknown fields never become verified. User can run a local end-to-end manual listing evaluation, without eBay or paid AI.
- P1: at least 50 independently labelled representative real photos, with separate holdout; report false positive/negative identity, OCR errors, risk recall and quantity uncertainty by single/binder/sealed/graded. Do not claim model accuracy from synthetic fixtures.
- P2: three to five design partners actually complete ten reviews each, no commercial data rights ambiguity, validated auth/tenant isolation and user-data deletion.
- P3: documented willingness to pay and usable unit economics. Do not monetize before source rights and legal/privacy/security checks.

## Immediate engineering plan (branch feature/pokemon-deal-reasoning-v1, draft PR #1)

1. New pure-python Listing Truth Engine with evidence-aware graded, sealed and quantity mismatch rules and no invented assertions.
2. Wire Truth Engine to existing vision.py and read-only review_report.py.
3. Localhost-only proof-of-flow browser alpha taking seller claim plus normalized observations (manual or previously obtained), returning truth findings and reasoning, without spending on AI.
4. Tests and developer usage guide. Keep scanner production branch unchanged and PR draft.

## Business actions

Recruit 3–5 collectors/dealers (preferably EU, English), obtain permission to test de-identified images, ask for ten annotated listings per partner. Request commercial data terms from candidate providers and create a written source rights register. Interview for pricing rather than guessing. Measure actual saved time and specific detected mistakes.
