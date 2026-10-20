# BIGSTEN Pokémon — Sale Evidence + Flip Calibration (without eBay API)

This is a **local-only** process for turning independently reviewed real
completed-sale transactions into conservative valuation evidence, and tracking
whether predicted profitable flips actually achieve their estimated ROI.

**No automatic scraping, no eBay credentials, no model-invented sold prices.**
A proof screenshot of an ACTIVE OFFER or a seller's asking price is NOT
evidence of a completed transaction.

## 1. Real completed-sale evidence

Create a **private** CSV named private/sales.csv in the pokemon-detector
directory. Use information that you own or are licensed/authorized to use:
your actual purchase/sale settlement exports, documented receipts, or
independently reviewed transaction records. Inspect proof yourself.

The exact CSV columns are:

    source,transaction_id,source_url,sold_at,price_eur,currency,identity_key,language,condition,sale_status,proof_type,proof_reference,reviewer,reviewed_at,identity_verified,condition_verified,price_verified,settlement_verified,match_confidence

For each record:
- source: the authorized source of actual transaction records.
- transaction_id: one UNIQUE original completed transaction ID, never a
  repeated listing or an invented pseudotransaction.
- source_url: HTTPS link to the original transaction/record (may be private;
  NEVER commit or publish the output containing it).
- sold_at: sale date in YYYY-MM-DD format, within the last 90 days.
- price_eur: realized payment (normalized to EUR before import), not the
  seller's asking price. Document FX conversions and taxes separately.
- currency: EUR, only. No implicit FX conversion.
- identity_key: exact edition, card number, language, foil/print, and raw/graded
  identity. Must match the target item's canonical key exactly.
- language: en, jp, de, fr, it, es, pt, ko, zh.
- condition: NM, LP, MP, HP, DMG, sealed or PSA_10-style graded label.
- sale_status: completed, not offered, cancelled, listed or sold-unverified.
- proof_type: settlement_record, platform_transaction_export, buyer_receipt,
  or seller_receipt.
- proof_reference: unique reference to a supporting receipt or statement,
  which MUST have been examined and which you retain privately.
- reviewer: person who confirmed the sale, exact printing, condition, final
  price and settlement.
- reviewed_at: review date, never before sale or later than analysis date.
- identity_verified, condition_verified, price_verified, settlement_verified:
  yes ONLY after checking underlying evidence.
- match_confidence: reviewer-assessed comparison certainty from 0.90 to 1.00;
  it is not a calibrated probability.

IMPORTANT: A manually entered yes / verified status is only a HUMAN
ATTESTATION. The code cannot prove that a platform really settled a sale.
A fake row could be manually created; do not enter unreviewed source data.

## 2. Evaluate a candidate from sales CSV

Prepare a private listing JSON with normalized items and separately entered
acquisition/resale costs. Example field structure:

    {
      "kind": "single",
      "currency": "EUR",
      "asking_eur": 65,
      "items": [{
        "identity_key": "tcgdex:sv03.5-199-holo-en-raw",
        "language": "en",
        "condition": "NM",
        "quantity": 1,
        "evidence": {
          "identity_confidence": 0.9,
          "condition_confidence": 0.8,
          "photo_confidence": 0.95,
          "authenticity_confidence": 0
        }
      }],
      "acquisition": {"shipping_eur": 6, "taxes_eur": 0},
      "sale": {
        "marketplace_fee_pct": 12,
        "outbound_shipping_eur": 4,
        "packaging_eur": 1
      }
    }

Those figures are an EXAMPLE, not a recommended acquisition. A cost or
authenticity confidence of zero may mean not yet verified, not confirmed free
of charge or genuine.

Run:

    python sales_evidence.py private/sales.csv --listing private/listing.json --out private/sale_evaluation.json

The importer gives **accepted** and **quarantined** row counts, each with
specific reasons. It joins ONLY exact identity/language/condition records
to each item. Then it calls reasoning.evaluate_deal.

For safety, the import explicitly sets costs_verified=false and
inventory_verified=false regardless of what the listing claims. Therefore
this CSV-only workflow NEVER emits BUY_CANDIDATE, even for highly attractive
estimated returns. Human-approved cost verification remains a separate gate.

Recent comps: the evaluator requires at least 3 comparable sales within 90
days per priced item; a fast BUY_CANDIDATE also requires at least 2 of those
observed in the last 14 days. This is a conservative heuristic, NOT a
statistically proven sell-through rate or market-wide number of transactions.

For binder/lot: physical inventory must additionally be reconciled and
validated before a BUY_CANDIDATE can be emitted by the underlying evaluator.

## 3. Audit actual purchase and resale outcomes

Keep forecast records even if you never buy. Log purchases still in stock
so that an unsold position is not silently excluded from your exit-time
report. Example history JSON (all fictional):

    [
      {
        "deal_id":"manual:001",
        "forecast_at":"2026-09-28",
        "decision":"BUY_CANDIDATE",
        "forecast_roi":0.35,
        "bought_at":"2026-09-29",
        "purchase_cost_eur":100,
        "purchase_reviewed":true,
        "purchase_proof_reference":"FICTIONAL-purchase-1",
        "closed_at":"2026-10-07",
        "net_sale_eur":126,
        "sale_reviewed":true,
        "sale_proof_reference":"FICTIONAL-sale-1"
      },
      {
        "deal_id":"manual:002",
        "forecast_at":"2026-09-28",
        "decision":"REVIEW",
        "forecast_roi":0.45,
        "bought_at":"2026-09-29",
        "purchase_cost_eur":100,
        "purchase_reviewed":true,
        "purchase_proof_reference":"FICTIONAL-purchase-2",
        "closed_at":null
      }
    ]

Execute:

    python flip_outcomes.py private/trades.json --horizon-days 14 --target-roi 0.25 --out private/flip_audit.json

Metrics include forecast ROI MAE/bias, realized ROI ONLY on closed trades,
realized target-ROI hit rate, quantity of open/overdue positions, and share
of purchases that actually exited within the stated horizon. An item still
held in inventory has no realized ROI and remains a non-exit for the horizon.

These metrics cannot establish model accuracy or trading profitability
without independent real transaction proof, adequate sample size and
consideration of selection bias, fees, taxes and unsuccessful positions.

## 4. Calibrating before spending meaningful funds

Build at least 50 independently annotated diverse real listing photos
(single, graded, sealed, binder, lot; known easy, rare and ambiguous prints).
Use vision_benchmark.py on a held-out set; do not tune and validate on the
same photos.

Track actual outcomes across at least 30 documented purchases, with full
recorded costs and open inventory, before interpreting hit-rate and average
ROI as useful indicators. **These are minimum pilot targets, not statistical
guarantees.**

Until actual photo/sale evidence is available, test fixtures only confirm
that the software's integrity guards behave as intended.

## Security and data hygiene

- Never upload receipts, buyer addresses, personally identifiable data,
  hidden transaction URLs or licensed datasets into the public GitHub repository.
- The new .gitignore ignores private/, local-data/, photos/, and routine
  report files, but other filenames could still be tracked. Check git status
  before every commit.
- All actual evidence files stay offline or in explicitly private storage.
- Do not commit API credentials, retailer cookies or marketplace account tokens.
- An AI vision result cannot provide documented sold prices or validated costs.
- Review transaction fees and applicable import taxes manually per region.
- BIGSTEN makes **no automatic purchases**.
