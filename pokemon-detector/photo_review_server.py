"""BIGSTEN Photo Review Lab — localhost-only manual ground truth annotator.

Run in pokemon-detector:
python photo_review_server.py --photos private/evaluation-photos \
    --out private/reference-holdout.json --catalog vision_catalog.json

No external access, no uploads, no AI API, no screenshots/CDN/analytics.
Human confirmation is required before any record becomes benchmark ground
truth. This annotator cannot prove correctness of a reviewer's assertion.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, parse_qs, urlsplit

from dataset_review import PhotoReviewError, PhotoReviewStore

STATIC = Path(__file__).resolve().parent/"photo_review"


class ReviewServer(ThreadingHTTPServer):
    allow_reuse_address=True
    daemon_threads=True

    def __init__(self, store: PhotoReviewStore, port=8766):
        self.store=store
        super().__init__(("127.0.0.1",port),ReviewHandler)


class ReviewHandler(BaseHTTPRequestHandler):
    server_version="BIGSTENPhotoReview/0.1"

    def log_message(self, format, *args):
        # Avoid logging customer image names, annotation content and paths.
        pass

    def _allowed(self, modifying=False):
        port=self.server.server_address[1]
        hosts={"127.0.0.1:"+str(port),"localhost:"+str(port)}
        if self.headers.get("Host","").lower() not in hosts:
            return False
        origin=self.headers.get("Origin")
        if modifying and origin is None:
            return False
        if origin:
            parsed=urlsplit(origin)
            if parsed.scheme!="http" or parsed.netloc.lower() not in hosts:
                return False
        return True

    def _send(self, code: int, data: bytes, mime="application/json; charset=utf-8", *, filename=None):
        self.send_response(code)
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Cross-Origin-Resource-Policy","same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; img-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'")
        self.send_header("Content-Type",mime)
        if filename:
            self.send_header("Content-Disposition",'attachment; filename="'+filename+'"')
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, payload):
        self._send(status,json.dumps(payload,ensure_ascii=False,allow_nan=False).encode())

    def do_GET(self):
        if not self._allowed():
            return self._json(403,{"error":"localhost access only"})
        url=urlsplit(self.path)
        route=url.path
        if route in {"/","/index.html","/app.js"}:
            path=STATIC/("app.js" if route=="/app.js" else "index.html")
            mime="application/javascript; charset=utf-8" if route=="/app.js" else "text/html; charset=utf-8"
            try:
                return self._send(200,path.read_bytes(),mime)
            except OSError:
                return self._json(500,{"error":"Local annotator UI missing"})
        if route=="/api/summary":
            return self._json(200,self.server.store.summary())
        if route=="/api/export":
            return self._send(200,(json.dumps(self.server.store.export(),ensure_ascii=False,indent=2)+"\n").encode(),
                              "application/json; charset=utf-8",filename="bigsten-reference-holdout.json")
        if route=="/api/catalog":
            q=parse_qs(url.query).get("q",[""])[0]
            if not isinstance(q,str) or len(q)>120:
                return self._json(400,{"error":"Search query too long"})
            q=q.strip().casefold()
            if len(q)<2:
                return self._json(200,{"candidates":[]})
            found=[]
            for c in self.server.store.catalog:
                if not isinstance(c,dict) or c.get("kind")=="sealed":
                    continue
                key=c.get("identity_key")
                if not isinstance(key,str):
                    continue
                name=c.get("name") or ""
                number=c.get("number") or ""
                if q in key.casefold() or q in str(name).casefold() or q in str(number).casefold():
                    found.append({k:c.get(k) for k in ("identity_key","name","set","number","finish","language")})
                    if len(found)>=25:
                        break
            return self._json(200,{"candidates":found})
        if route.startswith("/api/photo/"):
            try:
                # The store rejects absolute paths, separators, symlinks and
                # any file not in its explicit initial approved allowlist.
                name=unquote(route[len("/api/photo/"):],errors="strict")
                data,mime=self.server.store.image(name)
                return self._send(200,data,mime)
            except (PhotoReviewError,UnicodeError):
                return self._json(404,{"error":"Photo not found"})
        return self._json(404,{"error":"Not found"})

    def do_POST(self):
        if not self._allowed(modifying=True):
            return self._json(403,{"error":"Origin must be same localhost"})
        if urlsplit(self.path).path!="/api/label":
            return self._json(404,{"error":"Not found"})
        if self.headers.get("Content-Type","").split(";")[0].strip().lower()!="application/json":
            return self._json(415,{"error":"Only application/json"})
        try:
            size=int(self.headers.get("Content-Length","0"))
        except ValueError:
            return self._json(400,{"error":"Invalid content size"})
        if not 0<size<=12_000:
            return self._json(413,{"error":"Label request too large"})
        try:
            body=json.loads(self.rfile.read(size))
            record=self.server.store.save(body)
            return self._json(200,{"saved":record,"progress":self.server.store.summary()})
        except (PhotoReviewError,ValueError,TypeError,UnicodeError,json.JSONDecodeError) as exc:
            return self._json(422,{"error":str(exc)[:280]})
        except OSError:
            return self._json(500,{"error":"Private dataset write failed"})

    def do_OPTIONS(self):
        return self._json(403,{"error":"Cross-origin requests disabled"})


def main(argv=None):
    parser=argparse.ArgumentParser(description="BIGSTEN single-user localhost holdout labeling lab")
    parser.add_argument("--photos",default="private/evaluation-photos",
                        help="Local authorized photos (JPG, PNG, WebP), read-only")
    parser.add_argument("--out",default="private/reference-holdout.json",
                        help="Local private JSON manifest; never commit to public GitHub")
    parser.add_argument("--catalog",help="Optional local TCGdex exact variant catalog JSON")
    parser.add_argument("--port",type=int,default=8766)
    args=parser.parse_args(argv)
    if not 1024<=args.port<=65535:
        parser.error("Select port 1024..65535")
    catalog=[]
    if args.catalog:
        catalog=json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    store=PhotoReviewStore(args.photos,args.out,catalog=catalog)
    server=ReviewServer(store,args.port)
    print(f"BIGSTEN PRIVATE photo labeler: http://127.0.0.1:{args.port}")
    print(f"{len(store.photo_names)} photos; labels are saved ONLY to {store.dataset_path}")
    print("Never publicly deploy or proxy this unauthenticated local annotator.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=="__main__":
    main()
