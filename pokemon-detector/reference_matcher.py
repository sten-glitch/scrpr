"""BIGSTEN Local Reference Matcher — image pHash + OpenCV ORB (zero paid APIs).

Uses reference photos the USER owns or has licensed, stored only on their own
machine. Saves derived features into a local SQLite file. A reference match is
a *visual candidate*; it NEVER verifies authenticity, printing/foil, slab
certification, card condition, inventory, or sold prices.

Required optional packages: opencv-python-headless, numpy, Pillow.
Does NOT import/use Viridian code or third-party reference artwork.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sqlite3
import tempfile
import urllib.parse
import zlib
from pathlib import Path

from local_cv import _checked_image, LocalCVError

MAX_REFERENCES = 4000
MAX_IMAGE_PIXELS = 12_000_000
TOP_PHASH = 12
HASH_MAX_DISTANCE = 18
STRONG_PHASH_DISTANCE = 12
ORB_MIN_MATCHES = 8


class ReferenceMatchError(ValueError):
    pass


def _vision_libs():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ReferenceMatchError("Optional OpenCV and NumPy required. See requirements-local.txt") from exc
    return cv2, np


def features(bgr):
    """Compute 64-bit pHash (8x8 DCT) and ORB descriptors from one card crop."""
    cv2, np = _vision_libs()
    if bgr is None or getattr(bgr, "ndim", None) != 3 or bgr.shape[2] != 3:
        raise ReferenceMatchError("Expected a decoded 3-channel image")
    height, width = bgr.shape[:2]
    if min(height, width) < 48:
        raise ReferenceMatchError("Card crop too small for useful reference matching")
    if height * width > MAX_IMAGE_PIXELS:
        raise ReferenceMatchError("Card image exceeds pixel limit")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(gray))
    region = dct[:8, :8].flatten()
    middle = float(np.median(region[1:]))
    # Stable 64-bit signedness-free representation.
    fingerprint = 0
    for k, value in enumerate(region):
        if k > 0 and float(value) > middle:
            fingerprint |= 1 << (63 - k)
    blur = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 480.0 / max(height, width))
    if scale < 1:
        blur = cv2.resize(blur, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(nfeatures=750)
    _, desc = orb.detectAndCompute(blur, None)
    return {"phash": format(fingerprint, "016x"), "descriptors": desc}


def _encode_descriptors(desc) -> bytes | None:
    if desc is None or len(desc) == 0:
        return None
    # OpenCV ORB descriptors have exactly 32 uint8 columns.
    if desc.ndim != 2 or desc.shape[1] != 32 or len(desc) > 750:
        raise ReferenceMatchError("Invalid ORB descriptor shape")
    return zlib.compress(desc.tobytes(), level=6)


def _decode_descriptors(blob):
    if not blob:
        return None
    cv2, np = _vision_libs()
    decompressor = zlib.decompressobj()
    data = decompressor.decompress(blob, 750 * 32 + 1)
    if (not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail
            or len(data) == 0 or len(data) % 32 != 0 or len(data) > 750 * 32):
        raise ReferenceMatchError("Invalid stored ORB descriptor data")
    return np.frombuffer(data, dtype=np.uint8).reshape((-1, 32)).copy()


def _good_orb_matches(a, b):
    if a is None or b is None or len(a) < 3 or len(b) < 3:
        return 0
    cv2, np = _vision_libs()
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(a, b, k=2)
    return sum(1 for pair in pairs if len(pair) == 2 and pair[0].distance < 0.74 * pair[1].distance)


def _safe_reference(root: Path, filename: str) -> Path:
    if not isinstance(filename, str) or not filename or len(filename) > 260:
        raise ReferenceMatchError("Invalid reference image file")
    raw = Path(filename)
    if raw.is_absolute() or ".." in raw.parts or raw.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ReferenceMatchError("Reference images must be relative JPEG/PNG/WebP files inside image-root")
    root = root.expanduser().resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ReferenceMatchError("Reference cannot escape the approved image root") from exc
    if not path.is_file():
        raise ReferenceMatchError("Reference image file missing")
    return path


def build_reference_index(manifest: dict, image_root: str | Path,
                          output: str | Path, catalog: list[dict]) -> dict:
    """Build index only from explicit, rights-reviewed photos of exact catalog items.

    Manifest format:
    {"references":[{"reference_id":"...", "identity_key":"tcgdex:...",
    "image_file":"card.jpg", "rights_basis":"user_owned|licensed",
    "permission_reference":"written-receipt-or-agreement-id"}]}

    Rights fields are user attestations, NOT independently verified by program.
    """
    if not isinstance(manifest, dict) or not isinstance(manifest.get("references"), list):
        raise ReferenceMatchError("Expected manifest with references array")
    records = manifest["references"]
    if not 1 <= len(records) <= MAX_REFERENCES:
        raise ReferenceMatchError("Expected 1..4000 reference photos")
    if not isinstance(catalog, list):
        raise ReferenceMatchError("A trusted catalog JSON array is required")
    known_keys = {c.get("identity_key") for c in catalog
                  if isinstance(c, dict) and isinstance(c.get("identity_key"), str)}
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise ReferenceMatchError("Index already exists: refusing to overwrite a reviewed reference database")
    if not target.parent.is_dir():
        raise ReferenceMatchError("Index destination directory must already exist (use private/)")
    entries, seen = [], set()
    for entry in records:
        if not isinstance(entry, dict):
            raise ReferenceMatchError("Each reference must be an object")
        ref_id = entry.get("reference_id")
        identity = entry.get("identity_key")
        basis = entry.get("rights_basis")
        proof = entry.get("permission_reference")
        if (not isinstance(ref_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{4,100}", ref_id)
                or ref_id in seen):
            raise ReferenceMatchError("Every reference_id must be unique, 4..100 safe characters")
        if identity not in known_keys:
            raise ReferenceMatchError("Reference identity must be present in trusted catalog")
        if basis not in ("user_owned", "licensed") or not isinstance(proof, str) or not proof.strip() or len(proof) > 150:
            raise ReferenceMatchError("Every reference needs explicit photo-rights basis and reference")
        seen.add(ref_id)
        path = _safe_reference(Path(image_root), entry.get("image_file"))
        if path.stat().st_size > 5 * 1024 * 1024:
            raise ReferenceMatchError("Reference image exceeds 5 MiB")
        try:
            _, image = _checked_image(path.read_bytes())
            result = features(image)
        except (LocalCVError, ReferenceMatchError) as exc:
            raise ReferenceMatchError(f"Invalid/undecodable image for reference {ref_id}: {exc}") from exc
        entries.append((ref_id, identity, result["phash"], _encode_descriptors(result["descriptors"]), basis, proof))
    fd, tmpfile = tempfile.mkstemp(prefix=".bigsten-index-", suffix=".sqlite", dir=str(target.parent))
    os.close(fd)
    try:
        with sqlite3.connect(tmpfile) as db:
            db.execute("CREATE TABLE reference_features (reference_id TEXT PRIMARY KEY, identity_key TEXT NOT NULL, phash TEXT NOT NULL, orb BLOB, rights_basis TEXT NOT NULL, permission_reference TEXT NOT NULL)")
            db.execute("CREATE INDEX ref_by_identity ON reference_features(identity_key)")
            db.executemany("INSERT INTO reference_features VALUES (?,?,?,?,?,?)", entries)
            db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.executemany("INSERT INTO metadata VALUES (?,?)", [
                ("schema_version","1"),("created_utc",dt.datetime.now(dt.timezone.utc).isoformat()),
                ("index_classification","LOCAL_PRIVATE_USER_ATTESTED_REFERENCES"),
            ])
            db.commit()
        os.replace(tmpfile, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(tmpfile):
            os.remove(tmpfile)
    return {
        "status":"PRIVATE_REFERENCE_FEATURE_INDEX", "reference_count":len(entries),
        "unique_identities":len({e[1] for e in entries}),
        "rights_verified_by_software":False,
        "note":"Reference images not copied into database; license permissions are human attestations",
    }


class ReferenceMatcher:
    """Read-only bounded local index. No network, no cloud, no original images."""
    def __init__(self, index_path: str | Path):
        path = Path(index_path).expanduser().resolve()
        if not path.is_file() or path.stat().st_size > 120 * 1024 * 1024:
            raise ReferenceMatchError("Missing or oversized private reference index")
        # mode=ro guarantees image-matching cannot mutate reviewed records.
        uri = path.as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True) as db:
                meta = dict(db.execute("SELECT key,value FROM metadata"))
                if meta.get("schema_version") != "1":
                    raise ReferenceMatchError("Unsupported reference index schema")
                rows = list(db.execute("SELECT reference_id, identity_key, phash, orb FROM reference_features LIMIT ?", (MAX_REFERENCES+1,)))
        except sqlite3.Error as exc:
            raise ReferenceMatchError("Could not read local reference index") from exc
        if len(rows) > MAX_REFERENCES:
            raise ReferenceMatchError("Reference index too large")
        self.records = []
        for ref_id, identity, code, orb in rows:
            if not isinstance(code, str) or not re.fullmatch("[0-9a-f]{16}",code):
                raise ReferenceMatchError("Invalid reference hash")
            self.records.append((ref_id, identity, int(code,16), orb))
        self.reference_count = len(self.records)
        self.identity_count = len({item[1] for item in self.records})

    def match_bgr(self, bgr, *, top_n=5) -> dict:
        if isinstance(top_n,bool) or not 1 <= top_n <= 10:
            raise ReferenceMatchError("top_n must be 1..10")
        current = features(bgr)
        fingerprint = int(current["phash"],16)
        ranked = sorted(((hash_int ^ fingerprint).bit_count(), ref_id, identity, orb)
                         for ref_id, identity, hash_int, orb in self.records)[:TOP_PHASH]
        if not ranked or ranked[0][0] > HASH_MAX_DISTANCE:
            return {"status":"ABSTAIN","reason":"No sufficiently close reference image",
                    "candidates":[],"matched_identity_key":None}
        ranked_by_id = {}
        for distance, ref_id, ident, blob in ranked:
            try:
                agreement = _good_orb_matches(current["descriptors"], _decode_descriptors(blob))
            except (zlib.error, ReferenceMatchError):
                agreement = 0
            score = {
                "identity_key":ident, "reference_id":ref_id,
                "phash_distance":distance, "orb_good_matches":agreement,
                "status":"CANDIDATE_NOT_VERIFIED",
            }
            previous = ranked_by_id.get(ident)
            if previous is None or (score["orb_good_matches"], -score["phash_distance"]) > (previous["orb_good_matches"], -previous["phash_distance"]):
                ranked_by_id[ident] = score
        candidates = sorted(ranked_by_id.values(),
                            key=lambda a:(-a["orb_good_matches"],a["phash_distance"],a["identity_key"]))
        candidates = candidates[:top_n]
        best = candidates[0]
        # ORB is the geometric second stage. pHash alone is intentionally not
        # enough to assert an image-to-catalog identity.
        if best["phash_distance"] > STRONG_PHASH_DISTANCE or best["orb_good_matches"] < ORB_MIN_MATCHES:
            reason = "Only a weak pHash or ORB signal; manual identity confirmation required"
            status = "ABSTAIN"
        elif len(candidates) > 1 and (
            candidates[1]["orb_good_matches"] >= best["orb_good_matches"] - 3
            and candidates[1]["phash_distance"] <= best["phash_distance"] + 3
        ):
            reason = "Different printed identities have nearly equal reference similarity"
            status = "AMBIGUOUS"
        else:
            status = "VISUAL_CANDIDATE"
            reason = "pHash and ORB support this reference; printing, foil, authenticity and grade remain unverified"
        return {"status":status,"reason":reason,
                "matched_identity_key":best["identity_key"] if status=="VISUAL_CANDIDATE" else None,
                "candidates":candidates}

    def match_entire_photo(self, image_bytes: bytes) -> dict:
        """Photo-closeup fallback when no contours were detected.

        This never becomes a verified object detection. It merely offers an
        independently reviewable whole-frame reference-image candidate.
        """
        _, mat = _checked_image(image_bytes)
        return self.match_bgr(mat)

    def match_observations(self, images: list[bytes], observations: list[dict]) -> list[dict]:
        if not isinstance(images,list) or not isinstance(observations,list) or len(images)>8 or len(observations)>100:
            raise ReferenceMatchError("Too many images or observations")
        loaded = []
        for image in images:
            _, mat = _checked_image(image)
            loaded.append(mat)
        result = []
        for obs_index, obs in enumerate(observations):
            if not isinstance(obs,dict):
                continue
            idx, box = obs.get("image_index"), obs.get("bbox_xyxy")
            if (type(idx) is not int or not 0 <= idx < len(loaded) or
                    not isinstance(box,list) or len(box)!=4 or
                    not all(isinstance(v,(float,int)) and not isinstance(v,bool) and 0<=v<=1 for v in box) or
                    not box[0]<box[2] or not box[1]<box[3]):
                result.append({"observation_index":obs_index,"status":"ABSTAIN",
                               "reason":"Missing or invalid visible image region",
                               "matched_identity_key":None,"candidates":[]})
                continue
            mat=loaded[idx]
            height,width=mat.shape[:2]
            x1,y1,x2,y2=int(box[0]*width),int(box[1]*height),int(box[2]*width),int(box[3]*height)
            crop=mat[y1:y2,x1:x2]
            if crop.size==0 or min(crop.shape[:2])<80:
                result.append({"observation_index":obs_index,"image_index":idx,
                               "status":"ABSTAIN", "reason":"Card crop too small or empty",
                               "matched_identity_key":None,"candidates":[]})
                continue
            try:
                matches=self.match_bgr(crop)
            except ReferenceMatchError as exc:
                matches={"status":"ABSTAIN","reason":str(exc),
                         "matched_identity_key":None,"candidates":[]}
            result.append({"observation_index":obs_index,"image_index":idx,"bbox_xyxy":box,**matches})
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description="BIGSTEN local user-authorized image reference index; no internet")
    commands=parser.add_subparsers(dest="command",required=True)
    build=commands.add_parser("build",help="Create a local private reference index")
    build.add_argument("--manifest",required=True)
    build.add_argument("--image-root",required=True)
    build.add_argument("--catalog",required=True)
    build.add_argument("--out",default="private/card_references.sqlite")
    match=commands.add_parser("match",help="Identify a candidate card against your private reference index")
    match.add_argument("--index",default="private/card_references.sqlite")
    match.add_argument("--image",required=True)
    args=parser.parse_args(argv)
    if args.command=="build":
        catalog=json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        manifest=json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        result=build_reference_index(manifest,args.image_root,args.out,catalog)
    else:
        matcher=ReferenceMatcher(args.index)
        _, bgr = _checked_image(Path(args.image).read_bytes())
        result=matcher.match_bgr(bgr)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=="__main__":
    main()
