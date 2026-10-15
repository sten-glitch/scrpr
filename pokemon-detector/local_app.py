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
import shutil
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from workspace import WorkspaceStore, WorkspaceError
from workspace_api import workspace_get, workspace_post
from similar_listings import search_similar, review_supply
from vision_cost_router import VisionCostRouter

from listing_truth import evaluate_listing_truth
from local_cv import combine_local_observations, LocalCVError
from reference_matcher import ReferenceMatcher, ReferenceMatchError
from photo_inputs import MAX_TOTAL_BYTES
from vision import analyze_listing, VisionError

STATIC_DIR = Path(__file__).resolve().parent / "local_app"
MAX_REQUEST = 11 * 1024 * 1024
MAX_UPLOADS = 4


def runtime_capabilities(card_detector=None):
    """Report the engine the web app actually uses, not installed ML packages."""
    try:
        from local_cv import _modules
        _modules()
        cv=True
    except LocalCVError:
        cv=False
    return {"photo_detection_available":cv,
            "ocr_available":cv and __import__("certificate_reader").tesseract_executable() is not None,
            "photo_detector":("rfdetr_nano" if card_detector is not None else "opencv") if cv else "unavailable",
            "rfdetr_enabled":card_detector is not None}

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
                    matcher: ReferenceMatcher | None = None, *, card_detector=None) -> dict:
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
    status = "manual_observations" if observation is not None else (
        "rfdetr_offline" if card_detector is not None else "opencv_offline")
    notes = []
    if observation is None:
        try:
            observation = combine_local_observations([raw for _,raw in images], run_ocr=True, detector=card_detector)
            engine="RF-DETR Nano" if card_detector is not None else "OpenCV"
            notes.append(f"{engine} and Tesseract, where available, are only provisional object/OCR candidates")
        except LocalCVError as exc:
            if card_detector is not None:
                raise AlphaInputError("RF-DETR photo analysis could not complete; no result was saved") from exc
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
            if (not result["visual_reference_matches"] and len(images) == 1
                    and kind in {"single", "graded"}):
                whole = matcher.match_entire_photo(images[0][1])
                result["visual_reference_matches"] = [{
                    "observation_index": None, "image_index": 0, "scope": "whole_photo",
                    "note": "No verified card contour; compared the entire uploaded photograph",
                    **whole,
                }]
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
    if card_detector is not None and status=="rfdetr_offline":
        result["image_analysis"]["checkpoint_sha256"]=card_detector.checkpoint_sha256
        result["image_analysis"]["confidence_threshold"]=card_detector.threshold
    # No private image content or original local paths in returned JSON.
    return result


class AlphaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, port: int, catalog: list[dict], matcher: ReferenceMatcher | None = None,
                 workspace_path="private/bigsten_workspace.sqlite", *, card_detector=None):
        self.catalog = catalog
        self.matcher = matcher
        self.card_detector = card_detector
        self.workspace = WorkspaceStore(workspace_path)
        self.vision_router = VisionCostRouter(self.workspace.path)
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
        uri = urlsplit(self.path)
        if uri.path in ("/workspace", "/workspace.html"):
            path=STATIC_DIR/"workspace.html"
            ctype="text/html; charset=utf-8"
        elif uri.path in ("/analyze", "/index.html"):
            path=STATIC_DIR/"index.html"
            ctype="text/html; charset=utf-8"
        elif uri.path=="/workspace.js":
            path=STATIC_DIR/"workspace.js"
            ctype="application/javascript; charset=utf-8"
        elif uri.path=="/app.js":
            path=STATIC_DIR/"app.js"
            ctype="application/javascript; charset=utf-8"
        elif uri.path in ("/", "/graded", "/graded.html"):
            path=STATIC_DIR/"graded.html"
            ctype="text/html; charset=utf-8"
        elif uri.path=="/graded.js":
            path=STATIC_DIR/"graded.js"
            ctype="application/javascript; charset=utf-8"
        elif uri.path=="/api/graded/snapshot":
            try:
                saved=self.server.workspace.get_supply_snapshot(parse_qs(uri.query).get("id",[""])[0])
                return self._json(200 if saved else 404,saved or {"error":"Snapshot not found"})
            except WorkspaceError as exc:
                return self._json(422,{"error":str(exc)})
        elif uri.path=="/api/health":
            return self._json(200,{"status":"local_alpha","public_deployment_allowed":False,
                                   "capabilities":runtime_capabilities(self.server.card_detector),
                                   "catalog_items":len(self.server.catalog),
                                   "reference_index_loaded":self.server.matcher is not None,
                                   "reference_photos":self.server.matcher.reference_count if self.server.matcher else 0})
        elif uri.path.startswith("/api/workspace/"):
            try:
                code, payload=workspace_get(self.server.workspace,uri.path,parse_qs(uri.query))
                return self._json(code,payload)
            except (WorkspaceError,ValueError) as exc:
                return self._json(422,{"error":str(exc)[:400]})
        else:
            return self._json(404,{"error":"Not found"})
        try:
            contents=path.read_bytes()
        except OSError:
            return self._json(500,{"error":"Local UI file missing"})
        self._send(200,contents,ctype)

    def do_POST(self):
        if not self._valid_origin():
            # Consume only a small, declared body before closing. On Windows,
            # closing with unread incoming bytes can reset TCP and hide the 403.
            # Never parse this data; bound both size and time for hostile peers.
            try:
                rejected_length=int(self.headers.get("Content-Length","0"))
                if 0 < rejected_length <= 65536:
                    self.connection.settimeout(.5)
                    self.rfile.read(rejected_length)
            except (ValueError, OSError):
                pass
            return self._json(403,{"error":"Only localhost access is permitted"})
        endpoint=urlsplit(self.path).path
        if endpoint not in {"/api/analyze", "/api/graded/search", "/api/graded/certificate", "/api/graded/supply"} and not endpoint.startswith("/api/workspace/"):
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
            if endpoint.startswith("/api/graded/"):
                if not isinstance(payload,dict):
                    raise AlphaInputError("Expected JSON object")
                if endpoint=="/api/graded/search":
                    out=search_similar(payload.get("query", ""), self.server.catalog,
                        live=payload.get("live",False), environment=payload.get("environment","sandbox"),
                        markets=payload.get("markets"))
                elif endpoint=="/api/graded/certificate":
                    images=_decode_uploads(payload.get("images",[]))
                    if len(images)!=1:
                        raise AlphaInputError("Upload one upright slab photo")
                    routed=self.server.vision_router.analyze_listing_image(images[0][1],
                        {"grader_hint":payload.get("grader_hint")},
                        policy={"pipeline":"certificate-v2:"+str(__import__("certificate_reader").tesseract_executable())+":"+__import__("os").environ.get("BIGSTEN_OCR_LANG", "eng")})
                    out={**routed.pop("result"), "routing":routed}
                else:
                    out=review_supply(payload.get("listings"))
                snapshot=self.server.workspace.save_supply_snapshot(out)
                return self._json(200,{**out,"snapshot_id":snapshot})
            def configured_analysis(body,catalog,matcher):
                return analyze_request(body,catalog,matcher,card_detector=self.server.card_detector)
            if endpoint=="/api/analyze":
                out=configured_analysis(payload,self.server.catalog,self.server.matcher)
                return self._json(200,out)
            code,body=workspace_post(self.server.workspace,endpoint,payload,
                                     analyze_listing=configured_analysis,
                                     catalog=self.server.catalog,matcher=self.server.matcher)
            return self._json(code,body)
        except (AlphaInputError,VisionError,WorkspaceError,ValueError,TypeError) as exc:
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
    parser.add_argument("--open-browser",action="store_true",help="Open the local workbench on startup")
    parser.add_argument("--catalog",help="Optional TCGdex catalog JSON; loaded locally")
    parser.add_argument("--reference-index",help="Optional private user-owned pHash/ORB SQLite index")
    parser.add_argument("--rfdetr-checkpoint",help="Optional trusted local card-fine-tuned Nano checkpoint")
    parser.add_argument("--rfdetr-confidence",type=float,default=.5)
    parser.add_argument("--workspace-db",default="private/bigsten_workspace.sqlite",
                        help="Local-only persistent SQLite workspace (inside gitignored private folder)")
    args=parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Allowed local port range: 1024–65535")
    if args.open_browser:
        # A repeated double-click opens the running workbench instead of starting
        # another process on its port. Explicit custom configurations still fail
        # normally if their requested port is occupied.
        if (not args.catalog and not args.reference_index and not args.rfdetr_checkpoint
                and args.workspace_db=="private/bigsten_workspace.sqlite"):
            import urllib.request
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health",timeout=1) as response:
                    existing=json.load(response)
                if existing.get("status")=="local_alpha":
                    webbrowser.open(f"http://127.0.0.1:{args.port}")
                    return
            except (OSError,ValueError):
                pass
    catalog=[]
    default_catalog=Path(__file__).resolve().parent / "private/catalog-en-ja.json"
    if not args.catalog and default_catalog.is_file():
        args.catalog=str(default_catalog)
    if args.catalog:
        catalog=json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        if not isinstance(catalog,list):
            parser.error("Catalog must be JSON array")
    matcher=ReferenceMatcher(args.reference_index) if args.reference_index else None
    card_detector=None
    if args.rfdetr_checkpoint:
        from rfdetr_card_detector import RFDETRCardDetector
        card_detector=RFDETRCardDetector(args.rfdetr_checkpoint,threshold=args.rfdetr_confidence)
    server=AlphaServer(args.port,catalog,matcher,workspace_path=args.workspace_db,card_detector=card_detector)
    if args.open_browser:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    print(f"BIGSTEN Workbench: http://127.0.0.1:{args.port} — local database at {server.workspace.path}")
    print(f"Photo lab: http://127.0.0.1:{args.port}/analyze (PRIVATE, never expose publicly)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping local alpha")
    finally:
        server.server_close()


if __name__=="__main__":
    main()
