"""BIGSTEN Catalog Candidates — safe offline metadata suggestions, NEVER auto-identification.

Suggests possible TCGdex card printings after OCR/visual observations. Uses
Python standard library only (SequenceMatcher); optional fuzzy libraries can
later accelerate large catalogs, but candidates are NEVER treated as verified
card identities, authentic physical inventory or fair market prices.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher


def _text(value):
    if not isinstance(value,str):
        return ""
    normalized=unicodedata.normalize("NFKD",value).casefold()
    return " ".join(re.findall(r"[^\W_]+","".join(ch for ch in normalized if not unicodedata.combining(ch)), flags=re.UNICODE))


def _number(value):
    if not isinstance(value,str):
        return ""
    value=value.strip().upper().replace(" ","")
    halves=value.split("/")
    if len(halves)==2 and all(x.isdecimal() for x in halves):
        return str(int(halves[0]))+"/"+str(int(halves[1]))
    return value


class CatalogCandidateIndex:
    """Metadata-only index of exact variants. Trusted only as a catalog."""
    def __init__(self,catalog:list[dict]):
        if not isinstance(catalog,list):
            raise ValueError("Catalog must be an array")
        self.entries=[]
        self.by_number=defaultdict(list)
        self.by_first_word=defaultdict(list)
        for row in catalog:
            if not isinstance(row,dict):
                continue
            key=row.get("identity_key")
            if not isinstance(key,str) or not key.strip():
                continue
            if row.get("kind")=="sealed":
                continue
            name=_text(row.get("name"))
            number=_number(row.get("number"))
            if not name or not number:
                continue
            idx=len(self.entries)
            self.entries.append((row,name,number))
            self.by_number[number].append(idx)
            self.by_first_word[name.split()[0]].append(idx)

    def suggest(self,observation:dict, *, limit:int=5) -> list[dict]:
        if not isinstance(observation,dict) or not 1<=limit<=10:
            raise ValueError("Invalid suggestion request")
        name=_text(observation.get("name"))
        number=_number(observation.get("number"))
        if not name and not number:
            return []
        if number and number in self.by_number:
            indices=self.by_number[number]
        elif name:
            indices=self.by_first_word.get(name.split()[0],[])[:1200]
        else:
            return []
        results=[]
        for idx in indices[:1200]:
            row, reference_name, reference_number=self.entries[idx]
            exact_number=number==reference_number and bool(number)
            score=SequenceMatcher(None,name,reference_name).ratio() if name else 0
            if name and score < .65:
                continue
            if number and not exact_number:
                # An OCR collector number contradiction makes this candidate
                # unsuitable regardless of name similarity.
                continue
            if not exact_number and score < .90:
                continue
            results.append((int(exact_number),score,str(row["identity_key"]),row))
        results.sort(key=lambda r:(r[0],r[1],r[2]),reverse=True)
        return [{
            "identity_key":row["identity_key"],
            "name":row.get("name"),
            "set":row.get("set"),
            "number":row.get("number"),
            "finish":row.get("finish"),
            "language":row.get("language"),
            "name_similarity":round(similarity,3),
            "collector_number_matches":bool(number_matches),
            "status":"CANDIDATE_NOT_VERIFIED",
            "requires_manual_confirmation":True,
        } for number_matches,similarity,_,row in results[:limit]]


def suggest_for_observations(catalog:list[dict],observations:list[dict], *, limit:int=5):
    if not isinstance(observations,list):
        raise ValueError("Observations must be an array")
    index=CatalogCandidateIndex(catalog)
    return [{
        "observation_index":i,
        "image_index":o.get("image_index"),
        "candidates":index.suggest(o,limit=limit),
        "note":"OCR name/number and catalog suggestions are not proof of edition, foil or authenticity",
    } for i,o in enumerate(observations) if isinstance(o,dict)]
