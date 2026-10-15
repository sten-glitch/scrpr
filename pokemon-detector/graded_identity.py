"""Deterministic graded-card query resolution. Seller claims remain claims."""
import re
import unicodedata
from urllib.parse import quote

from listing_truth import extract_claims

GRADERS = {"psa": "PSA", "bgs": "BGS", "beckett": "BGS", "cgc": "CGC"}
LANGUAGES = {"en": "en", "english": "en", "英語": "en", "jp": "ja", "ja": "ja",
             "japanese": "ja", "日本語": "ja"}
EXCLUDED = re.compile(r"\b(?:ungraded|raw|booster|sealed|plush|toy|replica|digital|proxy|accessories)\b|empty\s+(?:psa\s+)?slab|grading\s+(?:supplies|kit)|slab\s+(?:case|stand|protector)|未鑑定", re.I)


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def number(value):
    s = norm(value).lstrip("#").replace(" ", "")
    return "/".join(str(int(p)) if p.isascii() and p.isdigit() else p for p in s.split("/"))


def metadata_prefilter(listing):
    title = str(listing.get("title") or "")[:500]
    title = re.sub(r"\bBeckett\b", "BGS", title, flags=re.I)
    claims = extract_claims({"title": title, "description": ""})
    grades = sorted({c["value"] for c in claims if c["type"] == "slab_grade" and c["asserted"]})
    exclusion = EXCLUDED.search(title)
    if exclusion:
        return {"status": "EXCLUDED", "reason": exclusion.group(0), "grader": None, "grade": None}
    if len(grades) != 1:
        return {"status": "REVIEW", "reason": "Missing or contradictory grading evidence", "grader": None, "grade": None}
    grader, grade = grades[0].split("_")
    # Metadata establishes a candidate, never a physical certificate.
    return {"status": "CANDIDATE", "grader": grader, "grade": grade,
            "reason": "Seller title grading claim; photo confirmation required"}


def resolve_query(query, catalog):
    if isinstance(query, str):
        query = {"text": query}
    if not isinstance(query, dict):
        raise ValueError("Query must be text or an object")
    allowed = {"text", "name", "set", "set_id", "number", "language", "variant", "grader", "grade", "certification_number", "identity_key"}
    if set(query) - allowed or any(not isinstance(v, str) or len(v) > 500 for v in query.values()):
        raise ValueError("Invalid query fields")
    text = unicodedata.normalize("NFKC", query.get("text", "")).strip()
    if not text and not any(query.values()):
        raise ValueError("Enter a graded card query")
    fields = {k: v.strip() for k, v in query.items() if k != "text" and v.strip()}
    conflicts = []
    assertions = {c["value"] for c in extract_claims({"title":re.sub(r"\bBeckett\b", "BGS", text, flags=re.I)})
                  if c["type"] == "slab_grade" and c["asserted"]}
    if len(assertions) > 1:
        conflicts.append("contradictory_grading_claims")
    prefilter = metadata_prefilter({"title": text})
    if prefilter["status"] == "EXCLUDED":
        return {"status": "OUT_OF_SCOPE", "fields": fields, "candidates": [], "queries": [], "reason": prefilter["reason"]}
    if fields.get("grader"):
        fields["grader"] = GRADERS.get(norm(fields["grader"]), "unsupported")
    if fields.get("language"):
        fields["language"] = LANGUAGES.get(norm(fields["language"]), "unsupported")
    for key in ("grader", "grade"):
        value = prefilter.get(key)
        if value and fields.get(key) and norm(fields[key]) != norm(value):
            conflicts.append(key)
        elif value:
            fields[key] = value
    brands = {GRADERS[m.casefold()] for m in re.findall(r"\b(PSA|BGS|Beckett|CGC)\b", text, re.I)}
    if len(brands) > 1 or (brands and fields.get("grader") and fields["grader"] not in brands):
        conflicts.append("grader")
    elif len(brands) == 1:
        fields.setdefault("grader", next(iter(brands)))
    langs = {v for k, v in LANGUAGES.items() if k not in {"en", "ja", "jp"} and re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", norm(text))}
    if len(langs) > 1:
        conflicts.append("language")
    elif langs:
        language = langs.pop()
        if fields.get("language") and fields["language"] != language:
            conflicts.append("language")
        fields.setdefault("language", language)
    nums = re.findall(r"#\s*([A-Za-z]*\d+(?:/\d+)?)", text)
    if len(set(map(number, nums))) > 1:
        conflicts.append("number")
    elif nums:
        if fields.get("number") and number(fields["number"]) != number(nums[0]):
            conflicts.append("number")
        fields.setdefault("number", nums[0])
    cert = re.fullmatch(r"\s*(PSA|BGS|Beckett|CGC)\s+(\d{6,16})\s*", text, re.I)
    if cert:
        if fields.get("certification_number") and fields["certification_number"] != cert.group(2):
            conflicts.append("certification_number")
        fields.setdefault("certification_number", cert.group(2))
    if fields.get("grade") and not re.fullmatch(r"(?:10|[1-9](?:\.5)?)", fields["grade"]):
        conflicts.append("grade")
    if fields.get("grader") == "unsupported" or fields.get("language") == "unsupported":
        conflicts.append("unsupported grader/language")
    if fields.get("certification_number") and not re.fullmatch(r"[0-9]{6,16}", fields["certification_number"]):
        conflicts.append("certificate format requires review")
    candidates = []
    for row in catalog:
        if not isinstance(row, dict) or row.get("kind") == "sealed":
            continue
        lang = LANGUAGES.get(norm(row.get("language")))
        variant = row.get("variant") or row.get("finish")
        if not all((row.get("identity_key"), row.get("set_id"), row.get("number"), lang, variant)):
            continue
        checks = {"identity_key": row["identity_key"], "set_id": row["set_id"], "set": row.get("set"),
                  "language": lang, "variant": variant}
        if any(fields.get(k) and norm(fields[k]) != norm(v) for k, v in checks.items()):
            continue
        if fields.get("number"):
            wanted, actual = number(fields["number"]), number(row["number"])
            if wanted != actual and ("/" in wanted or wanted != actual.split("/")[0]):
                continue
        names = [row.get("name", "")] + list(row.get("aliases") or [])
        if fields.get("name") and norm(fields["name"]) not in map(norm, names):
            continue
        explicit_anchor = any(fields.get(k) for k in ("identity_key", "name", "set_id", "set", "number"))
        name_in_text = any(norm(n) and re.search(r"(?<!\w)" + re.escape(norm(n)) + r"(?!\w)", norm(text)) for n in names)
        if not explicit_anchor and not name_in_text:
            continue
        candidates.append({"identity_key": row["identity_key"], "name": row.get("name"),
                           "set_id": row["set_id"], "set": row.get("set"), "number": row["number"],
                           "language": lang, "variant": variant})
    unique = {c["identity_key"]: c for c in candidates}
    candidates = sorted(unique.values(), key=lambda c: c["identity_key"])
    # A single catalog hit is insufficient when omitted set/variant may be absent from this catalog.
    exact = len(candidates) == 1 and all(fields.get(k) for k in ("language", "grader", "grade")) and (
        fields.get("identity_key") or ((fields.get("set_id") or fields.get("set")) and fields.get("number") and fields.get("variant")))
    status = "CONFLICT" if conflicts else "RESOLVED_QUERY" if exact else "CERTIFICATE_QUERY" if cert or fields.get("certification_number") else "NEEDS_CLARIFICATION"
    canonical = None
    if status == "RESOLVED_QUERY":
        c = candidates[0]
        canonical = "|".join(quote(str(v), safe="") for v in ("pokemon", c["language"], c["set_id"], number(c["number"]), c["variant"], fields["grader"], fields["grade"]))
    queries = []
    if status == "CERTIFICATE_QUERY" and fields.get("grader"):
        queries = [f"Pokemon {fields['grader']} {fields['certification_number']}"]
    elif status == "RESOLVED_QUERY":
        c = candidates[0]
        phrase = f"Pokemon {c['name']} {c['set'] or c['set_id']} {c['number']} {c['variant']} {fields['grader']} {fields['grade']} {'Japanese' if c['language']=='ja' else 'English'}"
        queries = [phrase]
    return {"status": status, "fields": fields, "canonical_identity": canonical,
            "candidates": candidates[:30], "candidate_count": len(candidates), "queries": queries,
            "conflicts": conflicts, "missing": [k for k in ("set_id", "number", "language", "variant", "grader", "grade") if not fields.get(k)],
            "note": "Query identity is user/catalog evidence; listing language does not establish card language or authenticity"}
