"""BIGSTEN Local Alpha — safe localhost-only web interface (no paid AI / eBay).

Run from pokemon-detector/: python local_app.py --port 8765
Open http://127.0.0.1:8765

This is a single-user local development alpha, NOT a deployable SaaS:
no authentication, tenancy, billing, persistent cloud storage or API rights.
Never expose it to the public internet, ngrok, Railway or a reverse proxy.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import json
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from listing_truth import evaluate_listing_truth
from local_cv import combine_local_observations, LocalCVError
from reference_matcher import ReferenceMatcher, ReferenceMatchError
from photo_inputs import MAX_TOTAL_BYTES
from vision import analyze_listing, VisionError

STATIC_DIR = Path(__file__).resolve().parent / "local_app"
MAX_REQUEST = 11 * 1024 * 1024
MAX_UPLOADS = 4

class AlphaInputError(ValueError):
    pass


def _user_text(value, label, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise AlphaInputError(f"{label}: expected text up to {limit} characters")
    return value.strip()


def _decode_uploads(images):
    if not isinstance(images, list) or len(images) > MAX_UPLOADS:
        raise AlphaInputError("Upload up to four photos per local review")
    result, size = [], 0
    extensions = {"image/jpeg":".jpg", "image/png":".png", "image/webp":".webp"}
    for i, entry in enumerate(images):
        if not isinstance(entry, dict):
            raise AlphaInputError("Each photo must have a data object")
        mime = entry.get("mime")
        if mime not in extensions:
            raise AlphaInputError("Only JPG, PNG and WebP are allowed")
        data = entry.get("base64")
        if not isinstance(data, str) or len(data) > 7_000_000:
            raise AlphaInputError("Oversized or missing base64 photo")
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError,binascii.Error):
            raise AlphaInputError("Invalid photo base64")
        if not raw or len(raw) > 5 * 1024 * 1024:
            raise AlphaInputError("Each photo must be at most 5 MiB")
        if mime == "image/jpeg" and not (raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")):
            raise AlphaInputError("JPEG signature mismatch")
        if mime == "image/png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AlphaInputError("PNG signature mismatch")
        if mime == "image/webp" and not (raw[:4]==b"RIFF" and raw[8:12]==b"WEBP"):
            raise AlphaInputError("WebP signature mismatch")
        size += len(raw)
        if size > MAX_TOTAL_BYTES:
            raise AlphaInputError("Total photo bytes exceed limit")
        result.append((f"image_{i+1}{extensions[mime]}",raw))
    return result


def analyze_request(payload: dict, catalog: list[dict] | None = None,
                    matcher: ReferenceMatcher | None = None) -> dict:
    """Pure entrypoint for local UI and tests; never sends remote requests."""
    if not isinstance(payload, dict):
        raise AlphaInputError("Expected JSON object")
    title = _user_text(payload.get("title",""), "title", 300)
    description = _user_text(payload.get("description",""), "description", 1800)
    kind = payload.get("kind") or "single"
    if kind not in {"single","graded","sealed","lot","binder"}:
        raise AlphaInputError("Invalid product category")
    asking = payload.get("asking_eur")
    if isinstance(asking,bool) or not isinstance(asking,(int,float)) or not 0 < asking < 1_000_000:
        raise AlphaInputError("Asking price must be a positive EUR amount")
    listing = {
        "listing_id": "local:temporary", "title": title, "description": description,
        "asking_eur": asking, "kind_hint": kind,
    }
    images = _decode_uploads(payload.get("images",[]))
    if not images:
        truth = evaluate_listing_truth(listing)
        return {
            "status": "TEXT_ONLY_NO_VISUAL_PROOF",
            "listing_truth": truth,
            "assessment": None,
            "image_analysis": {"mode": "none", "images":0,"observations":0},
            "open_questions": ["Add photos to check seller claims against actual objects",
                               "No proof of authenticity or completed sale was evaluated"],
        }
    observation = payload.get("observation")
    if observation is not None and not isinstance(observation, dict):
        raise AlphaInputError("Manual observation must be a structured JSON object")
    status = "manual_observations" if observation is not None else "opencv_offline"
    notes = []
    if observation is None:
        try:
            observation = combine_local_observations([raw for _,raw in images], run_ocr=True)
            notes.append("OpenCV and Tesseract, where available, are only provisional object/OCR candidates")
        except LocalCVError as exc:
            observation = {"kind":kind,"observations":[],"inventory_complete":False,
                           "uncertainties":["No local card recognition completed"]}
            status = "cv_unavailable"
            notes.append(str(exc))
    # Allow caller's generic raw/graded kind only when model does not assert
    # a more cautious multi-card classification. Never infer PSA from the title.
    if observation.get("kind") == "unknown":
        observation = {**observation, "kind":kind}
    with tempfile.TemporaryDirectory(prefix="bigsten-alpha-") as workspace:
        locations=[]
        for name,content in images:
            target=Path(workspace)/name
            target.write_bytes(content)
            locations.append(str(target))
        listing["image_files"]=locations
        result = analyze_listing(listing, catalog or [], observation=observation)
    if matcher is not None:
        try:
            result["visual_reference_matches"] = matcher.match_observations(
                [raw for _, raw in images], result["visual_evidence"]["observations"])
        except (ReferenceMatchError, LocalCVError) as exc:
            result["visual_reference_matches"] = []
            notes.append(f"Local reference matching unavailable: {exc}")
    else:
        result["visual_reference_matches"] = []
        notes.append("No private image-reference index configured; no pHash/ORB matching performed")
    result["image_analysis"] = {
        "mode": status, "images": len(images),
        "observations": len(result["visual_evidence"]["observations"]),
        "costs_verified": False,
        "notes": notes,
    }
    # No private image content or original local paths in returned JSON.
    return result


class AlphaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, port: int, catalog: list[dict], matcher: ReferenceMatcher | None = None):
        self.catalog = catalog
        self.matcher = matcher
        super().__init__(("127.0.0.1",port), AlphaHandler)


class AlphaHandler(BaseHTTPRequestHandler):
    server_version = "BIGSTENLocalAlpha/0.1"

    def _common(self):
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; img-src 'self' blob: data:; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self'; "
                         "connect-src 'self'; base-uri 'none'; form-action 'self'")

    def _send(self, status, content, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self._common()
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json(self,status,doc):
        raw=json.dumps(doc,ensure_ascii=False,allow_nan=False).encode()
        self._send(status,raw)

    def _valid_origin(self):
        port=self.server.server_address[1]
        expected={"127.0.0.1:"+str(port),"localhost:"+str(port)}
        host=self.headers.get("Host","").lower()
        if host not in expected:
            return False
        origin=self.headers.get("Origin")
        if origin:
            parsed=urlsplit(origin)
            if parsed.scheme!="http" or parsed.netloc.lower() not in expected:
                return False
        return True

    def do_GET(self):
        if not self._valid_origin():
            return self._json(403,{"error":"Only localhost access is permitted"})
        if self.path in ("/","/index.html"):
            path=STATIC_DIR/"index.html"
            ctype="text/html; charset=utf-8"
        elif self.path=="/app.js":
            path=STATIC_DIR/"app.js"
            ctype="application/javascript; charset=utf-8"
        elif self.path=="/api/health":
            return self._json(200,{"status":"local_alpha","public_deployment_allowed":False,
                                   "catalog_items":len(self.server.catalog)})
        else:
            return self._json(404,{"error":"Not found"})
        try:
            contents=path.read_bytes()
        except OSError:
            return self._json(500,{"error":"Local UI file missing"})
        self._send(200,contents,ctype)

    def do_POST(self):
        if not self._valid_origin():
            return self._json(403,{"error":"Only localhost access is permitted"})
        if self.path!="/api/analyze":
            return self._json(404,{"error":"Not found"})
        if self.headers.get("Content-Type","").split(";")[0].strip().lower()!="application/json":
            return self._json(415,{"error":"application/json required"})
        try:
            length=int(self.headers.get("Content-Length","0"))
        except (ValueError,TypeError):
            return self._json(400,{"error":"Invalid request size"})
        if not 0 < length <= MAX_REQUEST:
            return self._json(413,{"error":"Request too large or empty"})
        try:
            payload=json.loads(self.rfile.read(length))
            out=analyze_request(payload,self.server.catalog,self.server.matcher)
            return self._json(200,out)
        except (AlphaInputError,VisionError,ValueError,TypeError) as exc:
            return self._json(422,{"error":str(exc)[:400]})
        except Exception:
            return self._json(500,{"error":"Analysis failed without a financial conclusion"})

    def do_OPTIONS(self):
        return self._json(403,{"error":"Cross-origin access disabled"})

    def log_message(self,format,*args):
        # Do not log image data or seller text.
        return


def main(argv=None):
    parser=argparse.ArgumentParser(description="BIGSTEN private localhost alpha; NEVER publicly deploy")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--catalog",help="Optional TCGdex catalog JSON; loaded locally")
    parser.add_argument("--reference-index",help="Optional private user-owned pHash/ORB SQLite index")
    args=parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Allowed local port range: 1024–65535")
    catalog=[]
    if args.catalog:
        catalog=json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        if not isinstance(catalog,list):
            parser.error("Catalog must be JSON array")
    matcher=ReferenceMatcher(args.reference_index) if args.reference_index else None
    server=AlphaServer(args.port,catalog,matcher)
    print(f"BIGSTEN local alpha: http://127.0.0.1:{args.port} (PRIVATE, no login — never expose publicly)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping local alpha")
    finally:
        server.server_close()


if __name__=="__main__":
    main()
