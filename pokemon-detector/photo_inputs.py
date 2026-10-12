"""Safe image inputs for BIGSTEN Pokémon visual analysis.

Supports PUBLIC image URLs OR explicit local card photos, not both. Local
photos are encoded as data URIs only when a vision API call is requested.
This module does not authenticate Pokémon products or make buying decisions.
"""
from __future__ import annotations

import base64
import ipaddress
import os
import re
import urllib.parse
from pathlib import Path

MAX_IMAGES = 8
MAX_BYTES_PER_FILE = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024

class PhotoInputError(ValueError):
    pass


def _public_url(url: str) -> str:
    """Basic SSRF-sensitive endpoint hygiene; remote model/provider fetches image."""
    if not isinstance(url, str) or len(url) > 2048:
        raise PhotoInputError("Expected a short HTTPS image URL")
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.fragment):
            raise PhotoInputError("Only public HTTPS image URLs are accepted")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or "." not in host:
            raise PhotoInputError("Image hostname is invalid")
        if host.lower().endswith((".local", ".localhost", ".internal", ".invalid", ".test")):
            raise PhotoInputError("Local or internal image hosts are forbidden")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise PhotoInputError("Direct-IP images are not accepted")
        return url
    except ValueError as exc:
        raise PhotoInputError("Invalid HTTPS image URL") from exc


def _mime_from_signature(path: Path, data: bytes) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg") and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return "image/jpeg"
    if suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if suffix == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise PhotoInputError("Unsupported or malformed image (JPG/PNG/WebP only)")


def prepare_photo_inputs(listing: dict, *, encode_local: bool = False) -> dict:
    """Image provider messages + safe display metadata.

    Supports listing.image_urls or listing.image_files. Reads local files from
    disk only when explicitly named. The provider image payload is generated
    only with encode_local=True, preventing unnecessary base64/costs in offline
    cached-observation tests.
    """
    if not isinstance(listing, dict):
        raise PhotoInputError("Listing must be an object")
    urls = listing.get("image_urls") or []
    files = listing.get("image_files") or []
    if urls and files:
        raise PhotoInputError("Choose image_urls OR image_files, not both")
    sources = files if files else urls
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_IMAGES:
        raise PhotoInputError("Expected 1..8 image URLs or local image files")
    if any(not isinstance(x, str) or not x.strip() for x in sources):
        raise PhotoInputError("Image sources must be non-empty strings")
    messages, manifest = [], []
    total = 0
    if urls:
        for idx, value in enumerate(urls):
            url = _public_url(value)
            messages.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
            manifest.append({"index": idx, "source_type": "url", "reference": url})
    else:
        for idx, value in enumerate(files):
            path = Path(value).expanduser()
            try:
                if not path.is_file():
                    raise PhotoInputError("Local image does not exist")
                if path.stat().st_size > MAX_BYTES_PER_FILE:
                    raise PhotoInputError("Local image exceeds 5 MiB")
                # Only load a bounded number of bytes and reject oversized files.
                data = path.read_bytes()
                mime = _mime_from_signature(path, data)
            except OSError as exc:
                raise PhotoInputError("Unable to read local image") from exc
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise PhotoInputError("Local images exceed aggregate 16 MiB limit")
            manifest.append({"index": idx, "source_type": "local", "reference": path.name,
                             "mime": mime, "bytes": len(data)})
            if encode_local:
                b64 = base64.b64encode(data).decode("ascii")
                messages.append({"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64,{b64}", "detail": "high"}})
    return {"image_count": len(sources), "image_messages": messages,
            "manifest": manifest, "local": bool(files)}
