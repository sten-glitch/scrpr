"""BIGSTEN Internet Photo Sources — rights-aware, local research imports.

Sources are public discovery material, NOT independently proven rights to
commercially sublicense Pokémon artwork. No source photo is embedded into
the public Git repository, labeled as a specific card, or treated as a
completed-sale proof.

Commands:
  python external_photo_sources.py sources
  python external_photo_sources.py commons --max-images 12
  python external_photo_sources.py roboflow --source detector
  python external_photo_sources.py roboflow --source binder

Roboflow download uses OFFICIAL SDK with ROBOFLOW_API_KEY and accessible
public dataset version. No account bypass/scraping; no credentials stored
in GitHub. Results go under private/ (gitignored).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

SOURCES = {
    "detector": {
        "title": "Pokemon card detector",
        "url": "https://universe.roboflow.com/tcg-card-dectector/pokemon-card-detector-gksmy",
        "license_displayed": "CC BY 4.0",
        "workspace": "tcg-card-dectector",
        "project": "pokemon-card-detector-gksmy",
        "version": 1,
        "task": "object_detection",
        "identity_labels": False,
        "photos_reported": 494,
        "notes": "Published 3-class box annotations; card class ID must be read from exported data.yaml",
    },
    "binder": {
        "title": "Pokemon card binder",
        "url": "https://universe.roboflow.com/cardbinder/pokemon-card-binder",
        "license_displayed": "CC BY 4.0",
        "workspace": "cardbinder",
        "project": "pokemon-card-binder",
        "version": 1,
        "task": "object_detection",
        "identity_labels": False,
        "photos_reported": 36,
        "notes": "Public dataset and version must remain accessible; boxes are NOT card identities",
    },
    "scanner": {
        "title": "Pokemon Scanner (instance segmentation)",
        "url": "https://universe.roboflow.com/pokemon-card-detection-a3etk/pokemon-scanner-bzqii",
        "license_displayed": "CC BY 4.0",
        "workspace": "pokemon-card-detection-a3etk",
        "project": "pokemon-scanner-bzqii",
        "version": 1,
        "task": "instance_segmentation",
        "identity_labels": False,
        "photos_reported": 1239,
        "notes": "Polygon masks can be reduced to provisional card bounding boxes; no exact card ID",
    },
    "commons": {
        "title": "Wikimedia Commons: Pokemon Trading Card Game",
        "url": "https://commons.wikimedia.org/wiki/Category:Pok%C3%A9mon_Trading_Card_Game",
        "license_displayed": "Per-file; inspect author/license/underlying art separately",
        "task": "unlabeled_research_photos",
        "identity_labels": False,
        "notes": "Category includes logos, people, events; discovery does NOT imply a card is visible",
    },
}

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "BigstenLocalResearch/0.2 (contact: see project github.com/sten-glitch/scrpr)"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
COMMONS_LICENSES = ("CC BY", "CC-BY", "CC0", "PUBLIC DOMAIN", "CC BY-SA", "CC-BY-SA")
ALLOWED_IMAGE_HOSTS = {"upload.wikimedia.org", "thumb.wikimedia.org"}
IMAGE_SUFFIX = {".jpg", ".jpeg", ".png", ".webp"}


class PhotoSourceError(ValueError):
    pass


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _meta_text(value):
    if isinstance(value, dict):
        value = value.get("value", "")
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(value).strip()[:400]


def _allowed_commons_license(name):
    upper = str(name or "").upper().strip()
    return (upper == "CC0" or upper in {"PUBLIC DOMAIN", "PUBLIC DOMAIN MARK"}
            or upper.startswith("CC BY ") or upper.startswith("CC-BY-")
            or upper.startswith("CC BY-SA ") or upper.startswith("CC-BY-SA-"))


def _public_commons_image_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise PhotoSourceError("Missing Commons image URL")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_IMAGE_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment):
        raise PhotoSourceError("Only official HTTPS Wikimedia image hosts are allowed")
    return url


def _request_json(url: str) -> dict:
    # Called only with self-constructed fixed Commons API URL.
    if urllib.parse.urlsplit(url).netloc != "commons.wikimedia.org":
        raise PhotoSourceError("Unexpected metadata API endpoint")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                    "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=18) as response:
        if response.status != 200:
            raise PhotoSourceError("Commons metadata API returned non-200")
        raw = response.read(3 * 1024 * 1024 + 1)
    if len(raw) > 3 * 1024 * 1024:
        raise PhotoSourceError("Oversized Commons API metadata response")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise PhotoSourceError("Invalid Commons response")
    return data


def discover_commons(limit=50) -> list[dict]:
    """Find photo candidates with attribution metadata, without auto-labeling.

    Wikimedia Commons CC licenses cover the photograph to the extent
    represented by its uploader, not necessarily embedded copyrighted art.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise PhotoSourceError("Commons limit must be 1..50")
    q = {
        "action": "query", "format": "json",
        "generator": "categorymembers",
        "gcmtitle": "Category:Pokémon Trading Card Game",
        "gcmtype": "file", "gcmlimit": "max",
        "prop": "imageinfo", "iiprop": "url|size|extmetadata",
        "iiurlwidth": "1024",
    }
    url = COMMONS_API + "?" + urllib.parse.urlencode(q)
    payload = _request_json(url)
    pages = (payload.get("query") or {}).get("pages") or {}
    results = []
    for page in pages.values() if isinstance(pages, dict) else []:
        if not isinstance(page, dict):
            continue
        title = page.get("title", "")
        if not isinstance(title, str) or Path(title).suffix.lower() not in IMAGE_SUFFIX:
            continue
        images = page.get("imageinfo") or []
        if not images or not isinstance(images[0], dict):
            continue
        item = images[0]
        ext = item.get("extmetadata") or {}
        license_text = _meta_text(ext.get("LicenseShortName"))
        if not _allowed_commons_license(license_text):
            continue
        file_url = item.get("thumburl") or item.get("url")
        try:
            _public_commons_image_url(file_url)
        except PhotoSourceError:
            continue
        # File size may exceed 5 MiB; the scaled 1024-pixel thumbnail is
        # checked separately during download. Missing metadata = review.
        source_link = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        results.append({
            "source": "commons", "source_title": title,
            "source_page": source_link, "image_url": file_url,
            "author": _meta_text(ext.get("Artist") or ext.get("Attribution")),
            "license": license_text,
            "license_url": _meta_text(ext.get("LicenseUrl")),
            "usage_terms": _meta_text(ext.get("UsageTerms")),
            "copyright_subcontents_reviewed": False,
            "attribution_review_required": True,
            "identity_confirmed": False,
            "annotation_verified": False,
            "status": "UNLABELED_LICENSED_PHOTO_CANDIDATE",
        })
    return sorted(results, key=lambda item: item["source_title"])[:limit]


def _safe_image_download(url: str) -> bytes:
    _public_commons_image_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                    "Accept": "image/*"})
    with urllib.request.urlopen(request, timeout=25) as response:
        # Reject an unexpected redirect to a different host or scheme.
        _public_commons_image_url(response.geturl())
        if response.status != 200:
            raise PhotoSourceError("Image download failed")
        mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if mime not in ("image/png", "image/jpeg", "image/webp"):
            raise PhotoSourceError("Unexpected Wikimedia photo MIME type")
        raw = response.read(MAX_IMAGE_BYTES + 1)
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise PhotoSourceError("Image exceeds local alpha 5 MiB limit")
    if not (raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")
            or raw.startswith(b"\x89PNG\r\n\x1a\n")
            or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")):
        raise PhotoSourceError("Invalid image signature")
    return raw


def import_commons(max_images=12, root="private/web-research/commons", *, dry_run=False):
    """Store only reviewed-license photo candidates with machine attribution.

    Does NOT automatically count toward benchmark. The selected images may
    not depict individual cards, and artwork/subcontent rights need review.
    """
    if isinstance(max_images, bool) or not 1 <= max_images <= 50:
        raise PhotoSourceError("max_images must be 1..50")
    candidates = discover_commons(limit=50)
    dst = Path(root).expanduser().resolve()
    if not dry_run:
        if dst.exists() and any(dst.iterdir()):
            raise PhotoSourceError("Target folder already contains files; refusing overwrite")
        dst.mkdir(parents=True, exist_ok=True)
    saved, failed = [], []
    for item in candidates:
        if len(saved) >= max_images:
            break
        record = dict(item)
        suffix = Path(urllib.parse.urlsplit(item["image_url"]).path).suffix.lower()
        if suffix not in IMAGE_SUFFIX:
            suffix = ".jpg"
        photo_name = "commons_" + hashlib.sha256(item["source_page"].encode()).hexdigest()[:20] + suffix
        record["image_file"] = photo_name
        if dry_run:
            record["status"] = "CANDIDATE_NOT_DOWNLOADED"
            saved.append(record)
            continue
        try:
            binary = _safe_image_download(item["image_url"])
            # The photo remains only in this private local directory.
            (dst / photo_name).write_bytes(binary)
            record["photo_sha256"] = hashlib.sha256(binary).hexdigest()
            record["bytes"] = len(binary)
            record["status"] = "DOWNLOADED_UNLABELED_RESEARCH_PHOTO"
            saved.append(record)
        except (OSError, PhotoSourceError) as exc:
            failed.append({"source_page": item["source_page"],
                           "reason": str(exc)[:140]})
    meta = {
        "source": "Wikimedia Commons",
        "source_registry": SOURCES["commons"],
        "imported_at_utc": now_iso(),
        "license_disclaimer": (
            "Per-file photo license does not automatically authorize commercial "
            "reuse of Pokémon card artwork or cropped third-party content. "
            "Retain author attribution and license link; verify before reuse."
        ),
        "identity_verified": False,
        "benchmark_ready": False,
        "dry_run": bool(dry_run),
        "items": saved, "failed": failed,
    }
    if not dry_run:
        (dst / "SOURCE_ATTRIBUTION.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return meta


def download_roboflow(dataset: str, root="private/web-research"):
    """Use Roboflow's documented authenticated export SDK, not scraping.

    Requires an accessible public dataset version and ROBOFLOW_API_KEY.
    No API key is saved in the research metadata or Git repository.
    """
    if dataset not in ("detector", "binder", "scanner"):
        raise PhotoSourceError("Select detector, binder or scanner public source")
    key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    if not key:
        raise PhotoSourceError(
            "Roboflow export requires your Roboflow account/API key in "
            "ROBOFLOW_API_KEY; do not paste keys into chat or GitHub."
        )
    try:
        import roboflow
    except ImportError as exc:
        raise PhotoSourceError("Install optional official SDK: python -m pip install roboflow") from exc
    source = SOURCES[dataset]
    dest = Path(root).expanduser().resolve() / ("roboflow-" + dataset)
    if dest.exists() and any(dest.iterdir()):
        raise PhotoSourceError("Refusing to overwrite an existing Roboflow dataset export")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # The SDK handles authentication and export through the provider's
    # authorized API, including provider limits and access restrictions.
    rf = roboflow.Roboflow(api_key=key)
    project = rf.workspace(source["workspace"]).project(source["project"])
    downloaded = project.version(source["version"]).download(
        "yolov8", location=str(dest), overwrite=False
    )
    dest_path = Path(downloaded.location).resolve()
    if not dest_path.is_dir() or not (dest_path / "data.yaml").is_file():
        raise PhotoSourceError("Roboflow export is missing data.yaml")
    result = {
        "source": source, "downloaded_at_utc": now_iso(),
        "dataset_directory": str(dest_path),
        "license_published": source["license_displayed"],
        "dataset_original_artwork_rights_verified": False,
        "identity_labels": False, "benchmark_ready": False,
        "notes": "Use for card bounding-box detection only. Check data.yaml "
                 "class indices, independent splits and original content rights. "
                 "Never count raw provider labels as authenticated printing IDs.",
    }
    (dest_path / "SOURCE_ATTRIBUTION.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(
        description="BIGSTEN research image sources; rights and identities require review"
    )
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("sources", help="List verified public source descriptions")
    commons = commands.add_parser("commons", help="Fetch Commons photo candidates locally")
    commons.add_argument("--max-images", type=int, default=12)
    commons.add_argument("--out", default="private/web-research/commons")
    commons.add_argument("--dry-run", action="store_true")
    roboflow = commands.add_parser("roboflow", help="Official Roboflow authenticated dataset export")
    roboflow.add_argument("--source", choices=["detector", "binder", "scanner"], required=True)
    roboflow.add_argument("--out", default="private/web-research")
    a = p.parse_args(argv)
    if a.command == "sources":
        result = SOURCES
    elif a.command == "commons":
        result = import_commons(a.max_images, a.out, dry_run=a.dry_run)
    else:
        result = download_roboflow(a.source, a.out)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
