"""Export strict English Pokémon card variants from the TCGdex cards-database.

Run in scrpr's existing GitHub Action working directory:
python catalog_export.py --tcgdex ../tcgdex/data --out docs/data/vision_catalog.json

Catalog is an *identity index*, not a listing, proof of an edition from a
photograph, or evidence of market sales. Only trusted exact matches are used.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from detector import parse_card, parse_set, CM, get_json, sealed_set_names

VARIANT = {"normal": "normal", "holo": "holo", "reverse": "reverse"}


def export_catalog(root: str | Path) -> list[dict]:
    root = Path(root)
    series = {}
    for path in root.glob("*/*.ts"):
        parsed = parse_set(path.read_text(encoding="utf-8"))
        series[(path.parent.name, path.stem)] = parsed
    entries = []
    seen = set()
    for p in sorted(root.glob("*/*/*.ts")):
        setinfo = series.get((p.parent.parent.name, p.parent.name))
        if not setinfo:
            continue
        name, rarity, variants = parse_card(p.read_text(encoding="utf-8"))
        if not name or not variants:
            continue
        code, local = setinfo["id"], p.stem
        total = setinfo["official"]
        number = f"{local}/{total}" if total and re.fullmatch(r"\d+", local) else local
        for typ, ids in variants:
            if typ not in VARIANT or not ids.get("cardmarket"):
                continue
            key = f"tcgdex:{code}-{local}-{typ}-en-raw"
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "identity_key": key, "set": setinfo["name"], "set_id": code,
                "name": name, "number": number, "finish": VARIANT[typ],
                "language": "en", "rarity": rarity,
                "cardmarket_id": ids["cardmarket"],
                "tcgplayer_id": ids.get("tcgplayer"),
                "cardtrader_id": ids.get("cardtrader"),
            })
    return entries


def export_sealed_products(products: list[dict]) -> list[dict]:
    """Catalog *identity only*; never treats product name as seal authentication."""
    names = sealed_set_names(products)
    result = []
    for p in products:
        pid, name = p.get("idProduct"), p.get("name")
        if not isinstance(pid, int) or not isinstance(name, str) or not name.strip():
            continue
        result.append({
            "identity_key": f"cardmarket:sealed:{pid}", "kind": "sealed",
            "name": name.strip(), "set": names.get(p.get("idExpansion")) or "",
            "cardmarket_id": pid,
        })
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tcgdex", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--include-sealed", action="store_true", help="Download public Cardmarket sealed product catalog")
    args = ap.parse_args()
    result = export_catalog(args.tcgdex)
    if args.include_sealed:
        try:
            data = get_json(f"{CM}/productList/products_nonsingles_6.json")
            result.extend(export_sealed_products(data.get("products", [])))
        except Exception as exc:
            print(f"Warning: sealed products unavailable ({type(exc).__name__}); continuing with singles")
    if not result:
        raise SystemExit("TCGdex data missing or no usable variants")
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(result)} card-variant identities to {path}")


if __name__ == "__main__":
    main()
