# eBay Marketplace Account Deletion — deployment runbook

Implemented for a private workspace database and its managed exports. Production
subscription and erasure of historical/cloud/offline copies are NOT established
by these local tests. Do not declare "I do not persist eBay data".

## Required deployment boundary

Scanner and receiver MUST use the same durable SQLite file and adjacent
`.deletion-key`, on an always-on host. An isolated cloud receiver cannot erase an
offline laptop. Keep Scanner private. Publish ONLY the dedicated callback through
an HTTPS reverse proxy; never expose `local_app.py` publicly. Stop old writers
before switching to this revision.

Inventory existing databases, downloads, images, Redis/RQ, logs, CI artifacts,
Git/Pages history and backups before Production. The generic `bigsten-scraper`
is outside this registry and must not process eBay. Scanner uses official Browse
API requests. No remote purge of historical stores is performed by this code.

## Installation and secrets

In the existing Python >=3.11 virtual environment:

```text
python -m pip install -r requirements-deletion.txt
```

Set the following in ignored `.env` or a host secret manager:

```dotenv
EBAY_DELETION_ENDPOINT=https://YOUR-HOST/api/ebay/marketplace-account-deletion
EBAY_DELETION_VERIFICATION_TOKEN=YOUR_RANDOM_TOKEN
```

Token: 32–80 alphanumeric, underscore or hyphen characters. Generate locally with
`secrets.token_urlsafe(32)`; never paste it in chat or commit it. Public-key calls
use existing `EBAY_PRODUCTION_CLIENT_ID` / `EBAY_PRODUCTION_CLIENT_SECRET`.
The configured URL must exactly match the portal URL. Use separate callback
configurations (preferably separate workspaces) for Sandbox and Production.

From `pokemon-detector`, with the SAME absolute DB path used by Scanner:

```text
python ebay_deletion_server.py --db /absolute/private/bigsten_workspace.sqlite --environment production --host 127.0.0.1 --port 8766
```

Run under a supervisor with restart. Configure TLS, a 64 KiB body limit, bounded
concurrency/rate limits and no body/signature/query-string logging at the proxy.
Preserve raw body bytes and X-EBAY-SIGNATURE. Monitor receiver uptime and
`/healthz`: non-200 indicates pending/failed work. Alert on sustained failures.
The worker retries automatically; logs contain only sanitized failure messages.

## Portal activation after deployment approval

1. Verify persistent storage, restart and external HTTPS health.
2. In Application Keys → Notifications → Marketplace Account Deletion, turn
   off any no-persistence exemption. Configure alert email, URL and token.
3. Save and pass the GET challenge, then Send Test Notification.
4. Check signature verification, committed receipt, completed cleanup and health.
   Passing challenge alone is not an end-to-end deletion test.
5. Verify Production OAuth/public-key access; prior credential failures are not
   fixed just by installing this code. Restart Scanner on this revision.

No hostname, real token, portal subscription, paid hosting or public deployment
was created during local implementation.

## Implemented behavior

- GET hashes challenge + token + exact endpoint with SHA256.
- POST validates ECDSA using the official Notification API public key and
  caches keys for one hour. SHA1 matches the official SDK; SHA256 is accepted
  only when header and official key metadata agree. Bytes are not normalized.
- Invalid signatures: 412. Key/storage failure: 503 for upstream retry. Only a
  verified notification committed to SQLite receives 202.
- Inbox and tombstones retain HMAC identifiers, not raw notification payloads.
  HMAC values are pseudonymous, not anonymous: restrict access and document
  their purpose/retention. Protect the adjacent key; do not independently rotate
  it or restore only an old copy of the deletion ledger.
- Known aliases are expanded before ACK. All controlled writes register in the
  same SQLite transaction. Long analyses reject stale commits after a deletion.
- Target listings plus events/scenarios/trades are removed. Mixed snapshots,
  duplicate groups, evidence and statistics are invalidated as whole reports
  and must be regenerated. Known unrelated records remain available.
- Old/unmapped listings, unindexed snapshots/caches and incomplete ownership
  records are invalidated conservatively. Username alone is not assumed to be
  immutable userId. After a deletion, unresolved ownership cannot be persisted
  in that environment. This can discard other unmapped results. Reconcile
  identities through permitted official data; never synthesize a userId.
- Vision budget amounts remain, but unindexed listing references are cleared.
  Paid AI remains disabled by default.
- CLI exports and graded UI exports go to `managed_ebay_exports` beside the DB.
  CLI `--out` is now a filename. Files are registered before writing and removed
  by cleanup. Whole-workspace browser downloads containing eBay are refused.
- New eBay Git/Pages publication and the manual CI scan/upload job are disabled
  pending deletion propagation. Other market data still works. Historical
  published/downloaded copies are NOT erased by disabling these writers.
- Failed cleanup stays pending. secure_delete, VACUUM and WAL checkpoint/truncate
  must complete before status becomes complete. File unlink and SQLite cleanup
  cannot prove physical erasure from SSD remnants or volume/provider backups.
  Use encrypted storage and a documented backup/erasure process.

## Restore procedure and external copies

Stop all access. Preserve the CURRENT deletion tables and original key. Restore
only application data into that ledger, then run:

```text
python ebay_deletion_server.py --db /absolute/private/bigsten_workspace.sqlite --replay
```

Inspect results before reopening data. This command is not an automatic backup
merger. Restoring an old full DB would lose newer tombstones; recover a current
ledger/key from an independent protected copy. Manual copies, downloads,
external providers, legally retained records and hosted history require an
operator-owned inventory and deletion process. No universal erasure is claimed.

## Verification

```text
python -m unittest discover -s tests -p test_ebay_deletion.py -v
python -m unittest discover -s tests -q
node tests/page.test.js
```

Tests cover generated signatures, tampering, challenge, HTTP ACK after commit,
key outage/change, restart, retries, alias matching, environment isolation,
two sellers, mixed snapshots, cache deletion, stale analysis, managed export
cleanup, missing keys and replay. The official eBay SDK public signature fixture
was also verified locally. These tests do not replace the live portal test or
external-storage inventory.

References:
- https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion
- https://github.com/eBay/event-notification-nodejs-sdk
- https://developer.ebay.com/api-docs/static/data-handling-update.html
