# eBay Production readiness — BIGSTEN Graded Intelligence

Date: 2026-10-16. Branch `feature/graded-unique-supply`, base `bbd3616`. Builds on
[EBAY_ACCOUNT_DELETION.md](../EBAY_ACCOUNT_DELETION.md) and the 2026-10-16 audit.
Nothing here was deployed, committed to the eBay portal, or declared to eBay.

**Bottom line.** Production access needs (1) the deletion endpoint live on public HTTPS and
subscribed in the portal, and (2) a Production keyset that eBay accepts. The code side of (1)
is ready; (2) is not caused by local configuration. Do **not** select "Not persisting eBay data":
BIGSTEN persists listing data (IDs, titles, prices, certificates) for up to the retention window.

## A. What changed in this increment

| Change | Where | Why |
|---|---|---|
| Raw `username` / `userId` / `eiasToken` / `seller` are removed from every object before persistence; only keyed HMAC aliases stay in the deletion ledger | `ebay_deletion.py` `register()`; serialization moved after it in `workspace.py` | API License 8.2.1(c) forbids storing eBay User IDs; aliases keep deletion matching working |
| eBay data expires after `BIGSTEN_EBAY_RETENTION_HOURS` (default **6**, max 720) across listings, snapshots, OCR cache rows and managed exports | `DeletionLedger.purge_expired()`; enforced on every workspace/cache connection and in the receiver worker | 8.1(c) 6-hour freshness; 3.1(b) delete intermediate copies when no longer needed |
| Acknowledged deletions are applied before any read or write | `DeletionLedger.enforce()` | Closes the window where the scanner could still serve a deleted seller's data |
| `vision.py` writes eBay-derived output only as a managed export; `review_report.py` refuses eBay-derived HTML | `vision.py`, `review_report.py` | Unmanaged copies could not be deleted |
| Generic scraper rejects eBay hosts before queueing | `bigsten-scraper/api/models.py` | Keeps eBay data out of Redis/RQ/logs; eBay data only via official API |
| Receiver accepts any `schemaVersion` string (topic still enforced) | `ebay_deletion_server.py` | A future version would otherwise get 400, stop deletions and mark the endpoint down |
| OAuth diagnostic | `ebay_auth_check.py` | Separates config faults from keyset faults without printing secrets |
| Deployment files | `deploy/Caddyfile` (validated with Caddy 2.8.4), `deploy/*.service` | Minimal HTTPS endpoint |

**Not built, on purpose:** Layer C (persisted market statistics). API License 8.1(d) requires eBay's
*express prior written permission* for any use that "enables derivation of" site-wide statistics or
aggregated seller data, and 9.5 prohibits using eBay content "to suggest or model prices". Building
it before that permission would be code that cannot lawfully run.

## B. Data architecture

| Data | Processed | Persisted | Retention | Deleted by account notification |
|---|---|---|---|---|
| Browse API response (full) | in memory only | no | request lifetime | n/a |
| Seller username / userId / eiasToken | in memory, to compute aliases | **no** (stripped) | — | — |
| HMAC aliases (seller, item, event id) + key file | ledger | yes | no expiry (needed to suppress re-ingestion) | aliases kept as tombstones by design |
| Listing id, URL, title, price, images URLs, grading claim, certificate | yes | snapshots, managed exports, listings | 6 h default | yes |
| OCR result of a photo tied to an eBay listing | yes | `vision_cache` | 6 h when registered as eBay | yes |
| OCR of a photo the user uploads directly | yes | `vision_cache` | no expiry | only if registered as eBay — the app cannot know a manual upload came from eBay |
| Supply groups / counts | yes | inside snapshots | 6 h | yes (whole report) |
| OAuth app token, public keys | memory | no | token expiry / 1 h | n/a |

Tradeoff: with 6 h retention, relisting/duplicate detection only works inside a 6-hour window.
Longer windows need either eBay's written permission or a raised retention **plus** an age
disclosure on displayed listings (8.1(c)); the UI does not show listing age today.

## C. Compliance matrix

| # | Requirement (source) | Implementation | Test evidence | Status | Remaining action |
|---|---|---|---|---|---|
| 1 | Subscribe to deletion notifications or opt out; keyset activated only after (deletion guide) | receiver + ledger | — | **BLOCKED** | Owner: deploy + portal (section F) |
| 2 | Opt-out only if "not persisting any eBay data" | — | audit + section B | **NOT ELIGIBLE** | Never select the exemption |
| 3 | HTTPS, no localhost/internal IP, GET+POST | `validate_config`, `deploy/Caddyfile` | `test_challenge_exact_url`, `caddy validate` | PASS (code) / BLOCKED (deploy) | Deploy |
| 4 | Token 32–80 chars `[A-Za-z0-9_-]` | `validate_config` | `test_challenge_exact_url` | PASS | Generate token |
| 5 | Challenge: SHA-256(code+token+endpoint), 200, `application/json`, JSON library | `challenge`, `Handler.reply` | `test_challenge_exact_url`, HTTP test | PASS | Live portal check |
| 6 | Verify `X-EBAY-SIGNATURE` with getPublicKey, cache ~1 h, 412 on failure | `verify_signature`, `PublicKeys` | `test_signature_valid_and_tampered`, `test_key_outage_and_rotation` | PASS (synthetic keys) | Live "Send Test Notification" |
| 7 | ACK with 200/201/202/204 immediately; durable before ACK | 202 after SQLite commit | `test_http_ack_only_after_commit_and_invalid_signature` | PASS | — |
| 8 | Idempotent processing, retries | event HMAC id, pending retry | `test_duplicate_event_restart_and_no_raw_inbox`, `test_failed_cleanup_retries_without_false_success` | PASS | — |
| 9 | Remove all user data for the notified user | ledger cleanup + `enforce()` | `test_selective_deletion…`, `test_raw_seller_ids_never_stored…`, `test_acknowledged_deletion_applied_before_next_read` | PASS (managed stores) | — |
| 10 | Deletion irreversible "even [by] the highest system privilege" | `secure_delete`, WAL truncate, VACUUM | ledger tests | **NEEDS REVIEW** | Backups/SSD snapshots: see F.6 |
| 11 | Don't store eBay User IDs (License 8.2.1(c)) | stripped in `register()` | `test_raw_seller_ids_never_stored…` | PASS | HMAC aliases are pseudonymous derivatives kept only for deletion — confirm acceptable with eBay if asked |
| 12 | Listing data ≤ 6 h old when displayed (8.1(c)) | retention default 6 h | `test_retention_purges_expired_ebay_data_only` | PASS at default | Keep ≤ 6 h unless age disclosure is added |
| 13 | Delete intermediate copies (3.1(b)) | retention + managed exports | as above, CLI test | PASS | — |
| 14 | No derivation of statistics / price modelling without written permission (8.1(d), 9.5, 8.5.3) | Layer C not built | — | **BLOCKED** | Owner: ask eBay (F.7). "Undervalued listing" scoring on eBay asking prices may itself fall under 9.5 — legal review |
| 15 | No unmanaged copies of eBay data | vision CLI managed, HTML refused, scraper blocks eBay | `test_cli_exports…`, `bigsten-scraper/tests/test_models.py` | PASS | — |
| 16 | Historical copies (Git history, Pages, downloads, backups) | eBay publishing already disabled | audit (history snapshot `eb` empty) | NEEDS REVIEW | Owner inventory (F.6) |
| 17 | Alert email for endpoint failures | portal field | — | BLOCKED | Owner |
| 18 | Monitoring | `/healthz` (503 while deletions pending/failing) | `test_http_ack…` | PASS (local) | Optional external uptime check |
| 19 | Production OAuth works | `ebay_auth_check.py` | 5 tests; offline check on owner's `.env` | **BLOCKED** | Section E |

## D. Production deployment guide

**Constraint:** the receiver must share the SQLite file (and its `.deletion-key`) with the scanner,
and must be reachable 24/7 — after 24 h without ACK eBay marks the endpoint down, and after 30 days
the app is non-compliant.

**Recommended — one small VPS running both (Hetzner, already used by BIGSTEN).** Smallest shared
plan; Hetzner repriced its cloud in June 2026 and some cheap plans show "not available", so confirm
the price on hetzner.com/cloud before ordering (expect roughly €5–20/month + €0.50 IPv4). Requires approval.

1. Ubuntu server, user `bigsten`, `git clone` the repo to `/srv/bigsten/scrpr`, venv at `/srv/bigsten/venv`:
   `pip install -r requirements-local.txt -r requirements-deletion.txt`.
2. DNS A/AAAA record, e.g. `ebay-hook.<your-domain>` → server IP. Install Caddy, copy `deploy/Caddyfile`
   (edit hostname) to `/etc/caddy/Caddyfile`. Firewall: allow 22, 80, 443 only.
3. `/etc/bigsten/ebay.env` (`chmod 600`, owner `bigsten`):
   ```
   EBAY_PRODUCTION_CLIENT_ID=...
   EBAY_PRODUCTION_CLIENT_SECRET=...
   EBAY_DELETION_ENDPOINT=https://ebay-hook.<your-domain>/api/ebay/marketplace-account-deletion
   EBAY_DELETION_VERIFICATION_TOKEN=<python -c "import secrets;print(secrets.token_urlsafe(48)[:64])">
   BIGSTEN_EBAY_RETENTION_HOURS=6
   ```
4. Copy both `deploy/*.service` to `/etc/systemd/system/`, then `systemctl enable --now bigsten-ebay-deletion bigsten-scanner caddy`.
5. Check: `curl -s 127.0.0.1:8766/healthz` → `{"ready": true}`; from outside,
   `curl "https://ebay-hook.<domain>/api/ebay/marketplace-account-deletion?challenge_code=test"` → JSON with `challengeResponse`.
6. Use the scanner via SSH tunnel: `ssh -L 8765:127.0.0.1:8765 bigsten@SERVER`, open http://127.0.0.1:8765.
   Never open port 8765 publicly (no authentication).

**Zero-cost alternative — your Windows PC + Cloudflare Tunnel.** Same DB as today's scanner, no
server bill, but the PC must be on: >24 h offline (holidays, crashes) triggers eBay's alert and
starts the 30-day non-compliance clock. Acceptable only as a temporary step.

Environment variables: `EBAY_PRODUCTION_CLIENT_ID`, `EBAY_PRODUCTION_CLIENT_SECRET`,
`EBAY_SANDBOX_CLIENT_ID`, `EBAY_SANDBOX_CLIENT_SECRET`, `EBAY_ENVIRONMENT`,
`EBAY_DELETION_ENDPOINT`, `EBAY_DELETION_VERIFICATION_TOKEN`, `BIGSTEN_EBAY_RETENTION_HOURS`.

## E. Authentication report (`401 invalid_client`)

Verified 2026-10-16, offline, on the owner's `.env` (values never printed): both keysets present,
App ID carries the matching `-PRD-`/`-SBX-` marker, Cert ID starts with the matching prefix, no
whitespace/quotes, not swapped, no `:` in App ID, HTTP Basic encoding round-trips, correct token
endpoint (`https://api.ebay.com/identity/v1/oauth2/token`) and scope (`https://api.ebay.com/oauth/api_scope`).
On 2026-10-15 Sandbox authenticated successfully and Production returned `401 invalid_client`.

**Conclusion:** the request is well-formed, so eBay is rejecting the Production keyset itself.
Most likely: the Production keyset is not activated (eBay activates new keysets only after the
deletion subscription or opt-out), or the Cert ID was reset in the portal after being copied.
Not verified: this cloud session and the linked machine's VM cannot reach api.ebay.com.
Code changes cannot activate a keyset.

Remaining diagnostics, on Windows in `pokemon-detector`:
`.venv\Scripts\python.exe ebay_auth_check.py --live` — also detects a Windows environment variable
silently overriding `.env` (not checkable from the VM).

## F. Owner checklist (eBay Developer Portal)

1. Approve hosting (D) and a domain name.
2. After deployment, confirm step D.5 passes.
3. Portal → **Alerts & Notifications** (Application Keys page, Production keyset) → Marketplace Account Deletion:
   leave **"Not persisting eBay data" OFF**; enter alert email, the exact endpoint URL from
   `EBAY_DELETION_ENDPOINT`, and the same verification token → **Save** (eBay sends the challenge).
4. Click **Send Test Notification**; then on the server: `/healthz` returns ready and
   `ebay_deletion_events` has one `complete` row.
5. Portal → Application Keys: confirm the Production keyset shows enabled. If the Cert ID was ever
   reset, copy the current one into `/etc/bigsten/ebay.env` and your local `.env`; rerun
   `ebay_auth_check.py --live`.
6. Inventory and decide on old copies: Git history / Pages, downloaded JSON files, PC backups/OneDrive,
   any CI artifacts. Backups containing eBay data need a deletion/expiry procedure before Production use.
7. Ask eBay Developer Support in writing whether BIGSTEN's intended use (asking-price comparison,
   unique-supply counts, "undervalued" flags) is allowed under 8.1(d)/9.5, before enabling such features
   on Production data or building Layer C.

## G. Test report

- `pokemon-detector`: `python -m unittest discover -s tests` → **377 passed, 0 failed, 0 skipped** (Linux, all optional deps incl. `cryptography`, OpenCV, Tesseract).
  On Windows, 3 symlink tests skip without Developer Mode (unchanged).
- `bigsten-scraper`: 1 passed. `node tests/page.test.js` and `node --check local_app/*.js`: pass.
- Scanner smoke test (live local server): exact identity, certificate OCR (synthetic label), supply grouping;
  stored snapshots contain no seller identifiers.
- `caddy validate` on `deploy/Caddyfile`: valid.
- New tests: seller minimization, retention, pending-deletion reads, CLI/HTML export guards, scraper eBay block,
  schema version, OAuth diagnostics (5).
- **Not tested (external):** live eBay OAuth, live challenge and signed notification from eBay, TLS issuance on a
  real domain, real slab photos, deletion from backups.
