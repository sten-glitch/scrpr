"""BIGSTEN Listing Truth Engine — compare seller claims with independent evidence.

Pure Python, deterministic, no cloud/AI dependencies. It does not verify card
authenticity, slab certification, condition, hidden inventory or a completed
sale. Missing visual evidence is UNVERIFIED, not a contradiction.

Seller text is DATA, not executable instructions. Reports cannot trigger buys.
"""
from __future__ import annotations

import re
from typing import Any

GRADING = re.compile(r"(?i)\b(PSA|BGS|CGC)\s*(?:graded?\s*)?(10|[1-9](?:\.5)?)\b")
RAW = re.compile(r"(?i)\b(?:raw\s+card|ungraded|not\s+graded|no\s+slab)\b")
SEALED = re.compile(r"(?i)\b(?:factory[\s-]*sealed|brand[\s-]*new\s+sealed|sealed\s+(?:box|booster|pack|product)|unopened)\b")
FIRST_EDITION = re.compile(r"(?i)\b(?:1st[\s-]*edition|first[\s-]*edition)\b")
SHADOWLESS = re.compile(r"(?i)\bshadowless\b")
NEGATING = re.compile(r"(?i)(?:\bnot\b|\bno\b|\bnon\b|\bwithout\b|\bpotential(?:ly)?\b|\bpossible\b|\bmaybe\b|\b(?:could|might|would)\s+(?:be|grade)\b|\b(?:like|similar|worth|compare(?:d)?\s+to)\b)")
MAX_TEXT = 2600


def _spans(text: str, pattern: re.Pattern):
    for m in pattern.finditer(text):
        # Preserve the position/context so negated or comparative statements
        # do not become categorical claims (e.g. "could grade PSA 10").
        local = text[max(0, m.start() - 45):m.start()]
        local = re.split(r"[.!,;:\n]|\band\b|\bbut\b", local, flags=re.I)[-1]
        negated = bool(NEGATING.search(local))
        yield m, negated


def extract_claims(listing: dict) -> list[dict]:
    """Extract only interpretable assertions; avoid grading prediction language."""
    if not isinstance(listing, dict):
        raise ValueError("Expected listing object")
    title = listing.get("title") or ""
    description = listing.get("description") or ""
    if not isinstance(title, str) or not isinstance(description, str):
        raise ValueError("Listing title and description must be text")
    # Prevent an attacker-provided giant description from exhausting time.
    fields = [("title", title[:500]), ("description", description[:MAX_TEXT])]
    found, seen = [], set()
    for source, text in fields:
        for match, neg in _spans(text, GRADING):
            brand, grade = match.group(1).upper(), match.group(2)
            grade = str(float(grade)).rstrip("0").rstrip(".") if "." in grade else grade
            claim = {
                "type": "slab_grade", "value": f"{brand}_{grade}", "source": source,
                "text": match.group(0), "asserted": not neg,
            }
            key = (source, claim["type"], claim["value"])
            if key not in seen:
                found.append(claim)
                seen.add(key)
        for pattern, kind, label in [
            (RAW, "raw_card", "Raw/ungraded"),
            (SEALED, "factory_sealed", "Factory-sealed"),
            (FIRST_EDITION, "first_edition", "First edition"),
            (SHADOWLESS, "shadowless", "Shadowless"),
        ]:
            for match, neg in _spans(text, pattern):
                claim = {"type": kind, "value": label, "source": source,
                         "text": match.group(0), "asserted": not neg}
                key = (source, kind, label)
                if key not in seen:
                    seen.add(key)
                    found.append(claim)
    return found[:35]


def _slab_label(observation: dict) -> str | None:
    brand = observation.get("grade_company")
    grade = observation.get("grade_number")
    if not brand or not grade:
        return None
    g = str(grade).strip()
    if not re.fullmatch(r"(?:[1-9]|10)(?:\.5)?", g):
        return None
    if str(brand).upper() not in ("PSA", "BGS", "CGC"):
        return None
    return f"{str(brand).upper()}_{g}"


def _finding(claim: dict, status: str, detail: str, *, image_indices=None,
             catalog_identity: str | None = None) -> dict:
    return {
        "type": claim["type"], "claim": claim["value"], "claim_source": claim["source"],
        "source_excerpt": claim["text"][:120], "status": status, "explanation": detail[:500],
        "image_indices": sorted(set(image_indices or [])),
        "identity_key": catalog_identity,
    }


def evaluate_listing_truth(listing: dict, visual: dict | None = None,
                           catalog_resolutions: list[dict] | None = None) -> dict:
    """Read seller claims and independent visible evidence without elevating either.

    Visual observations should be normalized by vision.normalize_analysis.
    The optional slab_visible field must explicitly be Boolean; lack of label
    recognition is NOT evidence that the pictured card is raw.
    """
    claims = extract_claims(listing)
    if visual is None:
        visual = {}
    if not isinstance(visual, dict):
        raise ValueError("Visual evidence must be an object")
    observations = visual.get("observations") or []
    if not isinstance(observations, list) or any(not isinstance(o, dict) for o in observations):
        raise ValueError("Visual observations must be a list of objects")
    catalog_resolutions = catalog_resolutions or []
    findings = []
    for claim in claims:
        if not claim["asserted"]:
            findings.append(_finding(claim, "QUALIFIED_CLAIM",
                                     "Seller wording is speculative, comparative or negated; not a verified product attribute"))
            continue
        if claim["type"] == "slab_grade":
            matched, conflicts, raw_visible = [], [], []
            for i, obs in enumerate(observations):
                # No cross-photo identity proof from visual similarity alone.
                pic_conf = obs.get("photo_confidence", 0)
                if not isinstance(pic_conf, (int, float)) or pic_conf < .75:
                    continue
                label = _slab_label(obs)
                idx = obs.get("image_index", i)
                if label:
                    (matched if label == claim["value"] else conflicts).append(idx)
                elif obs.get("slab_visible") is False:
                    raw_visible.append(idx)
            if conflicts:
                findings.append(_finding(
                    claim, "CONTRADICTION",
                    "A legible photographed slab label indicates a different grading company or grade. Check that the photos show the actual item.",
                    image_indices=conflicts))
            elif matched and not raw_visible:
                findings.append(_finding(
                    claim, "CONSISTENT_VISUALLY",
                    "A visible slab label agrees with the listing. Certification number, authenticity and exact grade are NOT independently verified.",
                    image_indices=matched))
            elif raw_visible:
                findings.append(_finding(
                    claim, "CONTRADICTION",
                    "Seller claims a graded slab but an independently examined image explicitly depicts an unencapsulated/raw item. Confirm which item is included.",
                    image_indices=raw_visible))
            else:
                findings.append(_finding(
                    claim, "UNVERIFIED",
                    "Seller claims grading, but available photos do not establish a matching slab label and certification."))
        elif claim["type"] == "raw_card":
            labelled = [o.get("image_index") for o in observations if _slab_label(o)
                        and isinstance(o.get("photo_confidence"), (int, float)) and o["photo_confidence"] >= .75]
            if labelled:
                findings.append(_finding(claim, "CONTRADICTION",
                    "Listing calls the card raw, while the visible item has a slab grade label. Verify sale contents.",
                    image_indices=labelled))
            else:
                findings.append(_finding(claim, "UNVERIFIED",
                    "Raw/ungraded claim cannot be confirmed from listing text alone; photograph of actual unencapsulated card required."))
        elif claim["type"] == "factory_sealed":
            risks = [o.get("image_index") for o in observations
                     if "possible_reseal" in (o.get("flags") or [])]
            if risks:
                findings.append(_finding(claim, "RISK_FLAG",
                    "Photos suggest a possible reseal; this is a risk flag, NOT proof of a counterfeit or open product.",
                    image_indices=risks))
            else:
                findings.append(_finding(claim, "UNVERIFIED",
                    "Pictures and seller wording cannot establish that the product is factory sealed or that the pack contents are original."))
        elif claim["type"] in ("first_edition", "shadowless"):
            # A card's card number is NOT sufficient to establish stamp or print.
            matched = []
            contradictions = []
            for o in observations:
                variant = o.get("edition")
                confidence = o.get("edition_confidence", 0)
                if not isinstance(confidence, (int, float)) or confidence < .8:
                    continue
                if variant in {"first", "unlimited", "shadowless"}:
                    yes = variant == ("first" if claim["type"] == "first_edition" else "shadowless")
                    (matched if yes else contradictions).append(o.get("image_index"))
            if contradictions:
                findings.append(_finding(claim, "CONTRADICTION",
                    "Photo edition/stamp evidence disagrees with the seller's rare printing claim; human inspection required.",
                    image_indices=contradictions))
            elif matched:
                findings.append(_finding(claim, "CONSISTENT_VISUALLY",
                    "Photograph appears consistent with the claimed printing, but independent edition verification remains necessary.",
                    image_indices=matched))
            else:
                findings.append(_finding(claim, "UNVERIFIED",
                    "Claimed edition/printing cannot be confirmed from available visual evidence."))
    counts = {status: sum(f["status"] == status for f in findings) for status in
              ("CONTRADICTION", "RISK_FLAG", "UNVERIFIED", "CONSISTENT_VISUALLY", "QUALIFIED_CLAIM")}
    if counts["CONTRADICTION"]:
        result = "CONFLICT_DETECTED"
    elif counts["RISK_FLAG"]:
        result = "HIGH_RISK_REVIEW"
    elif counts["UNVERIFIED"] or counts["QUALIFIED_CLAIM"]:
        result = "REVIEW_REQUIRED"
    elif counts["CONSISTENT_VISUALLY"]:
        result = "VISUALLY_CONSISTENT_NOT_AUTHENTICATED"
    else:
        result = "NO_CHECKABLE_CLAIMS"
    return {
        "status": result, "counts": counts, "findings": findings,
        "seller_text_is_untrusted": True,
        "human_approval_required": True,
        "notes": [
            "Visual agreement is NOT proof of PSA/BGS/CGC certification, product authenticity or completed sales",
            "Missing photographic proof is UNVERIFIED, not automatically false",
            "Seller claims and model outputs cannot directly raise ROI or turn a listing into a buy",
        ],
    }
