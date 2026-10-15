# Official eBay integration

`ebay_discovery.EbayClient` isolates `sandbox` and `production`:

- `EBAY_SANDBOX_CLIENT_ID`, `EBAY_SANDBOX_CLIENT_SECRET`
- `EBAY_PRODUCTION_CLIENT_ID`, `EBAY_PRODUCTION_CLIENT_SECRET`

Secrets are environment-only, never returned by the web app. `.env*` is ignored;
automatic .env loading is not implemented. Launch the process from the environment
that contains credentials. Existing generic legacy variables remain usable only
through the explicit legacy discovery path.

Endpoints: `/identity/v1/oauth2/token` (client credentials scope
`https://api.ebay.com/oauth/api_scope`), `/buy/browse/v1/item_summary/search`,
`/buy/browse/v1/item/{item_id}`. Base hosts are official production/sandbox hosts.
Token cached in each client instance with expiration margin. Redirects disabled.
401 refreshes once, retryable HTTP statuses bounded to three attempts; long
Retry-After stops instead of retrying before the provider permits. Every Browse
retry consumes the shared request budget. Response size and timeout bounded.
Pagination constructs offsets locally, never follows untrusted next URLs.

Default CLI discovery is graded + sandbox. Legacy explicit categories are retained.
Original normalizer now retains item_id, original price, condition and aspects.
Shipping costs and sold prices are not inferred. Filters select fixed-price offers
deliverable to Romania, not complete marketplace inventory.

20 deterministic tests verify this client and legacy adapter. No real endpoint was
called: credentials are unavailable to the current process, permissions unknown.
Sandbox realism and Production access cannot be inferred from tests or the user's
possession of developer keys. Image-search access has not been assumed.

References: [OAuth](https://developer.ebay.com/develop/guides/sell/authorization),
[Browse search](https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search).
