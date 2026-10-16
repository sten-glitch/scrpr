"""Optional free/offline image analysis: OpenCV rectangles + Tesseract OCR.

This is a *candidate generator*, NOT a card authentication, grade/edition
classifier, accurate binder counter or sale-price estimator. It does not
download external image references, use paid APIs, or save image files.

Dependencies are imported only inside analyze_local_photo so ordinary CI,
manual listing checking and offline unit tests have zero pip requirements.
"""
from __future__ import annotations

import io
import re
from typing import Any


class LocalCVError(ValueError):
    pass


def _modules():
    try:
        import cv2
        import numpy as np
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise LocalCVError(
            "Optional local computer-vision packages missing. Install requirements-local.txt; "
            "Tesseract OCR also needs its system executable."
        ) from exc
    return cv2, np, Image


def _checked_image(image_bytes: bytes):
    if not isinstance(image_bytes, bytes) or not 0 < len(image_bytes) <= 5 * 1024 * 1024:
        raise LocalCVError("Expected PNG/JPEG/WebP data up to 5 MiB")
    cv2, np, Image = _modules()
    try:
        Image.MAX_IMAGE_PIXELS = 12_000_000
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.format not in {"JPEG", "PNG", "WEBP"}:
                raise LocalCVError("Only JPEG/PNG/WebP images are supported")
            w, h = img.size
            if w < 24 or h < 24 or w * h > 12_000_000:
                raise LocalCVError("Image pixel dimensions exceed safe bounds")
            img.load()  # PIL's pixel/decompression limit applies before cv2 decode
            from PIL import ImageOps
            rgb = ImageOps.exif_transpose(img).convert("RGB")
        mat = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    except LocalCVError:
        raise
    except Exception as exc:
        raise LocalCVError("Image could not be safely decoded") from exc
    return cv2, mat


def _overlap(a: list[float], b: list[float]) -> float:
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    aa = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    bb = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return intersection / (aa + bb - intersection) if aa + bb > intersection else 0.0


def detect_card_boxes(cv2, mat, max_cards=30) -> list[list[float]]:
    """Detect card-like rectangles as untrusted candidates.

    Bounding boxes use normalized page coordinates. Perspective/orientation,
    overlapping sleeves and foil glare can create false positives/negatives.
    """
    if isinstance(max_cards, bool) or not 1 <= max_cards <= 100:
        raise LocalCVError("max_cards out of bounds")
    height, width = mat.shape[:2]
    if height < 24 or width < 24:
        return []
    gray = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY)
    # Downscale detection to bound CPU, return normalized coordinates.
    scale = min(1.0, 1200 / max(height, width))
    if scale < 1:
        gray = cv2.resize(gray, (round(width*scale),round(height*scale)), interpolation=cv2.INTER_AREA)
    h, w = gray.shape[:2]
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edge = cv2.Canny(blur, 45, 135)
    contours_result = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = contours_result[-2]
    ranked = []
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        if perimeter < 60:
            continue
        poly = cv2.approxPolyDP(contour, .025 * perimeter, True)
        if len(poly) != 4 or not cv2.isContourConvex(poly):
            continue
        x, y, cw, ch = cv2.boundingRect(poly)
        if cw < 35 or ch < 50:
            continue
        area = cv2.contourArea(poly)
        fraction = area / (w * h)
        if not 0.004 <= fraction <= .90:
            continue
        aspect = min(cw, ch) / max(cw, ch)
        if not .55 <= aspect <= .87:
            continue
        rectangularity = area / (cw * ch)
        if rectangularity < .63:
            continue
        box = [x / w, y / h, (x + cw) / w, (y + ch) / h]
        ranked.append((fraction * rectangularity, box))
    ranked.sort(reverse=True)
    chosen = []
    for _, box in ranked:
        if any(_overlap(box, b) > .60 for b in chosen):
            continue
        chosen.append(box)
        if len(chosen) >= max_cards:
            break
    chosen.sort(key=lambda b: (b[1], b[0]))
    return [[round(v, 4) for v in b] for b in chosen]


def _ocr_card(cv2, mat, box: list[float]) -> tuple[str | None, str | None]:
    """Opt-in OCR on detected card crop; never trust alone for rare edition."""
    try:
        import pytesseract
    except ImportError:
        return None, None
    h, w = mat.shape[:2]
    x1,y1,x2,y2 = int(box[0]*w), int(box[1]*h), int(box[2]*w), int(box[3]*h)
    crop = mat[y1:y2,x1:x2]
    if crop.size == 0:
        return None,None
    # Deliberately read less than whole image to bound expensive OCR.
    try:
        crop = cv2.resize(crop, (420, max(240, round(crop.shape[0]*420/crop.shape[1]))))
        upper = crop[:max(1, round(crop.shape[0]*.30))]
        lower = crop[round(crop.shape[0]*.68):]
        name_line = pytesseract.image_to_string(upper, config="--psm 6", timeout=3)
        number_line = pytesseract.image_to_string(lower, config="--psm 6", timeout=3)
    except Exception:
        return None,None
    lines = [re.sub(r"[^a-zA-Z0-9 .'À-ÿ-]", "", text).strip()
             for text in name_line.splitlines()]
    name = next((line[:90] for line in lines if 3 <= len(line) <= 65
                 and re.search(r"[A-Za-zÀ-ÿ]{3}", line)), None)
    matches = re.findall(r"\b(\d{1,4}\s*/\s*\d{1,4})\b", number_line)
    number = matches[0].replace(" ", "") if matches else None
    return name,number


def analyze_local_photo(image_bytes: bytes, *, image_index: int=0, max_cards=30,
                        catalog: list[dict] | None=None, run_ocr=True, detector=None) -> dict:
    """Return normalized-observation-compatible provisional visible objects.

    If card rectangles cannot be found or OCR is missing, abstain instead of
    claiming an unseen card. The catalog can suggest names, not verify print.
    """
    cv2, image = _checked_image(image_bytes)
    boxes = detector(image) if detector is not None else detect_card_boxes(cv2,image,max_cards=max_cards)
    engine = "RF-DETR" if detector is not None else "OpenCV"
    observations = []
    for box in boxes:
        name, number = _ocr_card(cv2,image,box) if run_ocr else (None,None)
        observations.append({
            "image_index": image_index, "bbox_xyxy": box, "name": name,
            "set": None, "number": number,
            "language": "unknown", "finish": "unknown",
            "condition": "unknown", "grade_company": None,
            "grade_number": None, "slab_visible": None,
            "identity_confidence": .25 if name and number else (.1 if name or number else 0),
            "condition_confidence": 0.0, "photo_confidence": .52,
            "edition": "unknown", "edition_confidence": 0.0,
            "flags": ["condition_unclear","back_not_visible"]
              + (["number_unreadable"] if not number else [])
              + (["set_unreadable"] if not name else []),
        })
    return {"kind": "binder" if len(observations) > 1 else "single",
            "summary": f"Local {engine} candidate rectangles: {len(boxes)}. OCR is provisional; exact print not verified.",
            "inventory_complete": False, "observations": observations,
            "uncertainties": [
                "Detection can mistake sleeves, stickers, photos and packaging for cards",
                "OCR can misread card names/numbers; set, foil, authenticity and edition remain unverified",
                "Photo quantity is not proof of unique physical cards",
            ]}


def combine_local_observations(images: list[bytes], *, run_ocr=True, detector=None) -> dict:
    if not isinstance(images, list) or not 1 <= len(images) <= 8:
        raise LocalCVError("1–8 images expected")
    observations, uncertainties = [], []
    for idx, data in enumerate(images):
        result = analyze_local_photo(data, image_index=idx, run_ocr=run_ocr, detector=detector)
        observations.extend(result["observations"])
        uncertainties.extend(result["uncertainties"])
    if len(observations) > 100:
        observations = observations[:100]
        uncertainties.append("Detection count truncated to 100 provisional objects")
    return {
        "kind": "binder" if len(observations)>1 else "single",
        "summary": f"{'RF-DETR' if detector is not None else 'OpenCV'} provisional detections in {len(images)} images: {len(observations)} objects",
        "inventory_complete": False, "observations": observations,
        "uncertainties": list(dict.fromkeys(uncertainties)),
    }
