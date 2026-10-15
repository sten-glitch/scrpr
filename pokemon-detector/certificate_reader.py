"""Bounded, local slab-label OCR. Evidence is provisional, never authentication.

The caller should supply a single upright slab image/crop. Region proposals are
geometric hypotheses, not a trained label detector. No network or image storage.
"""
from __future__ import annotations

import hashlib
import re
import threading
from typing import Callable

from local_cv import _checked_image

_OCR_SLOTS = threading.BoundedSemaphore(2)

_GRADERS = {
    "PSA": r"\bPSA\b|PROFESSIONAL SPORTS AUTHENTICATOR",
    "BGS": r"\bBGS\b|\bBECKETT\b",
    "CGC": r"\bCGC\b|CERTIFIED GUARANTY COMPANY",
}
_PREFIX = re.compile(
    r"\b(?:CERT(?:IFICATE|IFICATION)?\.?|SERIAL)\s*(?:NUMBER|NO\.?)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9./-]*)(?![A-Z0-9])",
    re.I,
)


def parse_certificate_text(text: str, grader_hint: str | None = None, *,
                           allow_label_layout: bool = False) -> dict:
    """Parse literal OCR text; scores are heuristic evidence strength, not accuracy.

    Layout fallback is opt-in for label crops and requires a visible grader plus
    a separate all-digit line. It never receives the explicit-prefix confidence.
    No O/0, I/1 replacement, padding or certification-length assumptions are made.
    """
    if not isinstance(text, str) or len(text) > 16000:
        raise ValueError("Certificate text must be a string up to 16000 characters")
    hint = grader_hint.upper() if isinstance(grader_hint, str) else grader_hint
    if hint == "BECKETT":
        hint = "BGS"
    if hint is not None and hint not in _GRADERS:
        raise ValueError("Unsupported grader hint")
    visible = [name for name, pattern in _GRADERS.items() if re.search(pattern, text, re.I)]
    conflict = len(visible) > 1 or bool(hint and visible and hint not in visible)
    grader = None if conflict else (visible[0] if visible else hint)
    candidates = []
    for match in _PREFIX.finditer(text):
        token = match.group(1)
        # Non-digits may be OCR ambiguity. Preserve them as evidence; abstain.
        if any(char.isdigit() for char in token):
            candidates.append({"value": token, "method": "explicit_prefix",
                               "evidence": match.group(0), "numeric": token.isascii() and token.isdigit()})
    if not candidates and allow_label_layout and len(visible) == 1 and not conflict:
        for line in text.splitlines():
            token = line.strip()
            # Exclude years, grades, and small card numbers from layout inference.
            if re.fullmatch(r"[0-9]+", token) and len(token.lstrip("0")) > 4:
                candidates.append({"value": token, "method": "isolated_label_line",
                                   "evidence": line, "numeric": True})
    values = {c["value"] for c in candidates}
    # A small integer/year is weak label evidence even after an explicit prefix.
    # This is an ambiguity filter, not a universal official certificate grammar.
    selected = candidates[0] if (len(values) == 1 and candidates[0]["numeric"]
                                and len(candidates[0]["value"].lstrip("0")) > 4 and grader) else None
    score = (.65 if selected["method"] == "explicit_prefix" else .35) if selected else 0.0
    grade = None
    # Require a grade marker, quality label, or grader directly before the grade.
    grade_pattern = r"(?:\bGRADE\s*[:#]?|\bGEM\s*(?:MT|MINT)|\bMINT|\bPRISTINE|\bPSA|\bBGS|\bCGC)\s+(10|[1-9](?:\.5)?)(?![\d.])\b"
    grades = set(re.findall(grade_pattern, text, re.I))
    if len(grades) == 1 and not conflict:
        grade = next(iter(grades))
    number = re.search(r"\bCARD\s*(?:NO\.?|NUMBER)\s*[:#]?\s*([A-Z0-9]+(?:/[A-Z0-9]+)?)", text, re.I)
    year = re.search(r"\b(?:19|20)[0-9]{2}\b", text)
    language_clues = []
    if re.search(r"\b(?:JAPANESE|JPN)\b|日本語", text, re.I):
        language_clues.append("ja")
    if re.search(r"\b(?:ENGLISH|ENG)\b", text, re.I):
        language_clues.append("en")
    # Names/sets require explicit field labels; unstructured lines stay evidence.
    def field(label):
        match = re.search(rf"(?im)^\s*{label}\s*:\s*(.+)$", text)
        return match.group(1).strip() if match else None
    errors = []
    if conflict:
        errors.append("grader_conflict")
    if len(values) > 1:
        errors.append("conflicting_certificate_candidates")
    if any(not c["numeric"] for c in candidates):
        errors.append("ambiguous_certificate_characters")
    if any(c["numeric"] and len(c["value"].lstrip("0")) <= 4 for c in candidates):
        errors.append("certificate_candidate_too_short")
    return {"grader": grader, "grader_source": "visible_text" if visible else ("hint" if hint else None),
            "certificate_number": selected["value"] if selected else None,
            "certificate_confidence": score, "confidence_kind": "heuristic_uncalibrated",
            "grade": grade, "card_name": field("(?:CARD NAME|NAME)"),
            "card_number": number.group(1) if number else None, "set": field("SET"),
            "year": year.group(0) if year else None, "language_clues": language_clues,
            "original_text": text, "candidates": candidates, "errors": errors,
            "verification_status": "unavailable", "authenticity": "unknown"}


def _tesseract_ocr(image) -> str:
    import pytesseract
    return pytesseract.image_to_string(image, config="--psm 6", timeout=3)


def read_slab_certificate(image: bytes, grader_hint: str | None = None, *,
                          ocr: Callable | None = None) -> dict:
    """Safely decode <=5 MiB image and OCR at most two bounded label proposals.

    Injectable ``ocr`` receives a grayscale numpy crop and returns original text.
    Decoder errors are raised. Missing engine/timeouts return explicit evidence
    errors and an empty result; they must not masquerade as a successful reading.
    """
    with _OCR_SLOTS:
        return _read_slab_certificate(image, grader_hint, ocr=ocr)


def _read_slab_certificate(image: bytes, grader_hint: str | None = None, *, ocr=None) -> dict:
    parse_certificate_text("", grader_hint)  # validate before expensive image work
    cv2, matrix = _checked_image(image)
    height, width = matrix.shape[:2]
    read = ocr or _tesseract_ocr
    regions = [("upper_label", [0, 0, 1, .32]), ("lower_label", [0, .75, 1, 1])]
    evidence, texts, errors = [], [], []
    for name, box in regions:
        crop = matrix[int(box[1]*height):max(int(box[3]*height), 1), :]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        scale = min(2.0, 1200 / max(gray.shape))
        gray = cv2.resize(gray, (max(1, round(width*scale)), max(1, round(gray.shape[0]*scale))))
        entry = {"region": name, "bbox_xyxy": box, "proposal": "geometry_only",
                 "crop_sha256": hashlib.sha256(gray.tobytes()).hexdigest(),
                 "processed_size": [gray.shape[1], gray.shape[0]], "original_text": "", "error": None}
        try:
            text = read(gray)
            if not isinstance(text, str) or len(text) > 8000:
                raise ValueError("Invalid OCR output")
            entry["original_text"] = text
            texts.append(text)
        except Exception as exc:
            name = type(exc).__name__
            code = "ocr_unavailable" if isinstance(exc, ImportError) or name == "TesseractNotFoundError" else "ocr_failed"
            entry["error"] = code
            errors.append(code)
        evidence.append(entry)
        if entry["error"] == "ocr_unavailable":
            break
    result = parse_certificate_text("\n".join(texts), grader_hint, allow_label_layout=True)
    result.update({"image_sha256": hashlib.sha256(image).hexdigest(), "crops": evidence,
                   "engine": "injected" if ocr else "tesseract",
                   "status": "partial" if errors and texts else ("unavailable" if errors else
                             ("completed" if result["certificate_number"] else "no_certificate")),
                   "limitations": ["Requires an upright single-slab crop; label regions are geometric hypotheses",
                                   "No certificate registry verification; OCR accuracy has not been benchmarked"]})
    result["errors"] = list(dict.fromkeys(result["errors"] + errors))
    return result
