# BIGSTEN Pokémon Deal Intelligence — Decision Engine V1

Standalone deterministic decision engine intended for integration with `sten-glitch/scrpr/pokemon-detector`.

## What it does
- Supports `single`, `sealed`, `lot` and `binder` offers, as long as an upstream adapter provides normalized item identities, sale comps and evidence.
- Uses **only verified, traceable, recent completed sales** of exactly matching identity, language and condition (minimum three per recognized item). Discards stale, unmatched and duplicated comps.
- Uses observed lower quartile as conservative resale price; calculates acquisition, resale marketplace fees, shipping, and projected net ROI.
- Produces `BUY_CANDIDATE`, `REVIEW` or `REJECT` plus confidence, diagnostics and evidence links. It does not automatically buy.
- Excludes unpriced lot components from projected resale; refuses to estimate full ROI when priced coverage <90% (or <100% for singles/sealed).

A BUY_CANDIDATE additionally requires explicit `costs_verified: true` from a trusted cost-validation adapter; omitted costs are not considered verified. This flag must never come from an unreviewed language-model guess.

## What it cannot do yet
It does **not** connect to marketplaces, retrieve sold listings, scan images, confirm condition, authenticate cards, infer missing items in binder images, or validate import taxes. These must be built upstream. `BUY_CANDIDATE` means human review is still mandatory.

## Run
```bash
python reasoning.py example.json
python -m unittest discover -s tests -v
```

## Integrating into `scrpr`
Connect an evidence pipeline:
1. Discover marketplace listings with permitted official APIs and persist listing IDs, image URLs and seller metadata.
2. Run image identification for each card or sealed product; capture OCR, edition, number, language, foil/variant, PSA/raw and visual condition with source image evidence.
3. Match **completed sales**, not active ask prices, by exact printing/language/condition; carry canonical sale URLs + timestamp.
4. Convert all prices to EUR and calculate actual inbound duties/VAT and seller costs separately.
5. Call `evaluate_deal` to obtain deterministic net profit + risk flags; surface reasoning with 'unknown' and manual review options.

The existing Cardmarket/Tcgplayer trend metrics are useful *discovery signals*; they must not be passed off as verified sold comparables or actual liquidity counts.

## Example input
See `example.json`.