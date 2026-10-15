# Graded identity

Implemented: `graded_identity.resolve_query(query, catalog)` and
`metadata_prefilter(listing)`. Reuses `listing_truth.extract_claims` to reject
speculative grading claims. Main local route and discovery CLI now prioritize
graded cards; legacy workbench/raw/lot features remain explicit separate tools.

Queries accept text or named fields: name, set_id/set, number, language,
variant, grader, grade, identity_key, certification_number. A resolved canonical
key includes game, language, set, collector number, variant, grader and grade.
Incomplete inputs retain candidates even if the small local catalog has one hit.
Japanese script is preserved by `catalog_candidates._text`; it does not imply
Japanese card language. `jp` aliases normalize to `ja` in this engine.

Tested: Unicode candidates, explicit English/Japanese language, ambiguity,
wrong/contradictory grade, certificate-only query, exclusions, no network offline.
Catalog entries need existing `identity_key`, set_id, name, number, language and
finish/variant. Optional `aliases` supports bilingual names. The old TCGdex
exporter remains English-only; a complete Japanese catalog import is outstanding.
Query resolution is not proof that a live listing sells that exact card.

Planned: structured eBay specifics mapping, title aliases/negation expansion,
catalog-backed candidate selection UI and human-confirmed photo identity.
