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

from detector import _str, parse_card, parse_set

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tcgdex", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = export_catalog(args.tcgdex)
    if not result:
        raise SystemExit("TCGdex data missing or no usable variants")
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(result)} card-variant identities to {path}")


if __name__ == "__main__":
    main()
