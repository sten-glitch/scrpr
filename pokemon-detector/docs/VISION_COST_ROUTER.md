# Local-first routing and budget reservations

`VisionCostRouter(existing_workspace_db_path).analyze_listing_image(...)` is used
by the new certificate HTTP endpoint. It caches local results keyed by image hash,
canonical metadata, pipeline/model versions and external-enabled mode. Transient
OCR unavailable/failure results are not cached. The app includes Tesseract path in
the pipeline key, so installing it changes that key. Raw image bytes are not stored.

No paid adapter is configured or exposed through the HTTP endpoint. The legacy
`vision.call_vision_api` additionally requires `BIGSTEN_PAID_VISION_AUTHORIZED=1`
before a remote request; that legacy path is not this router and should not be used
for budget-controlled production ingestion.

An injected external adapter requires BOTH explicit external_authorized and a
provider-enforced hard cost ceiling. Estimates alone are insufficient. The SQLite
ledger reserves the full ceiling transactionally before any provider call, enforcing
daily, monthly, per-listing, attempt and concurrency limits. Unknown/failed call costs
are retained. Provider-reported costs reconcile; ceiling overrun disables further
paid calls. A crashed pending reservation deliberately fails closed and needs review.
All amounts use one configured accounting currency; no cross-currency conversion.

Tested using fake adapters only: cache invalidation, defaults, attempts, budget
exhaustion, concurrency, reservation retention and actual-cost reconciliation.
Local latency benchmarks are separate. Real escalation rate, token billing and
cost per 1,000 real listings are unknown. Native GPU/RAM accounting and global
cross-process OCR concurrency, adaptive expected-benefit decisions and retention
cleanup remain planned. No paid service has been activated.
