# Unique observed certificate identities

`unique_supply.aggregate_supply(listings)` is deterministic and network-free.
Input rows require marketplace and item_id. Optional exact identity_key, grade,
certificate {grader,number,evidence_status,source,provenance}, image_sha256 and
price {amount,currency} are documented in the module. Supply review is available
through `/api/graded/supply` and a local JSON upload at `/graded`.

eBay item IDs collapse across known marketplace views, retaining view provenance.
Confirmed certificate groups require an explicit human_confirmed or
verified_consistency attestation with photographed_label or grader_registry source.
These are caller attestations, not independent validation performed by this engine.
Seller claims and OCR confidence alone cannot pass this gate.

Same certificate with contradictory card/grade or conflicting observations of one
item is quarantined. Different certificates stay separate. Identical image hashes
flag photograph reuse; differing certificates on one image add a conflict flag.
No visual similarity is silently subtracted from inventory. Existing pHash/ORB
is retained but not calibrated as physical-slab evidence.

Counts separate raw observations, unique listings, accepted certificate groups,
duplicate listings and unresolved cases. Bounds are CONDITIONAL on one item per
listing and truthful certificates: lower=max(accepted groups,1 if nonempty),
upper=accepted groups+unresolved listings. They are not authenticated physical
inventory. Multi-quantity/lot listings require separate treatment before use.
Asking-price summaries are per currency and do not estimate market sale value.

Tests cover same certificate x3, different certs, conflicts, repeated item views,
missing/weak evidence, reused image conflicts, price currencies and invalid grades.
Real inventory precision/false-merge rate remains unmeasured.
