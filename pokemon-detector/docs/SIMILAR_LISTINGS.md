# Similar listings

Main local page `/` (also `/graded`) provides query interpretation, explicit eBay
search, local certificate reading and reviewed-observation grouping. Original
workbench is `/workspace`; original card/lot photo lab is `/analyze`.

`similar_listings.search_similar` reuses the canonical resolver and `EbayClient`.
Ambiguous queries stop before network calls. Certificate queries can search
without inventing set/variant. Default mode is local-only; explicit UI search
selects sandbox or production. UK/US/DE use two pages each, 20 items/page, shared
12-request cap including retries. Marketplace hits deduplicate global eBay IDs.

Live search hits remain `UNRESOLVED_SEARCH_HIT`. `exact_match_supply` is null
until exact identity and certificate evidence are reviewed. Search terms alone do
not prove a match. Raw hits, excluded candidates, views, errors and partial coverage
are reported. No global coverage or confirmed physical stock claim.

Reports persist in the existing workspace DB `supply_snapshots`; local image bytes
are transient. JSON export and snapshot retrieval are implemented. Default local
database currently has no real card catalog. Launch with existing `--catalog` to
use an authorized catalog JSON. No external image upload is performed.

Pending: image-to-query connection via existing reference matcher, automated
specifics enrichment, listing image retrieval, reviewed hit-to-supply workflow,
incremental search caching and live end-to-end proof with credentials/data.
