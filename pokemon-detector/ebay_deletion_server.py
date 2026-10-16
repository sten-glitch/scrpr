"""Dedicated eBay callback. Expose ONLY this service behind an HTTPS proxy.

Run beside the private workspace on the same durable volume; never expose the
localhost workbench. Signature validation precedes durable ACK (no raw inbox).
"""
import argparse
import base64
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

from ebay_deletion import DeletionLedger

ROUTE = '/api/ebay/marketplace-account-deletion'


class InvalidSignature(ValueError):
    pass


class KeyUnavailable(RuntimeError):
    pass


class PublicKeys:
    def __init__(self, environment):
        from ebay_discovery import EbayClient
        self.client = EbayClient(environment)
        self.cache = {}
        self.lock = threading.Lock()

    def __call__(self, kid):
        with self.lock:
            cached = self.cache.get(kid)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            try:
                # This long-lived receiver must not inherit Browse's per-scan OAuth budget.
                self.client.oauth_requests_used = 0
                value = self.client._transport(self.client.base + '/commerce/notification/v1/public_key/' + kid,
                    headers={'Authorization': 'Bearer ' + self.client._access_token()})
                if not isinstance(value, dict) or not isinstance(value.get('key'), str):
                    raise ValueError()
                if len(self.cache) >= 100:
                    self.cache.clear()
                self.cache[kid] = (time.monotonic() + 3600, value)
                return value
            except Exception:
                self.client._token = None
                raise KeyUnavailable('Official eBay public key unavailable') from None


def verify_signature(raw, header, keys):
    from cryptography.exceptions import InvalidSignature as CryptoInvalid
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        if not isinstance(header, str) or len(header) > 8192:
            raise ValueError()
        envelope = json.loads(base64.b64decode(header, validate=True))
        kid = envelope['kid']
        if not isinstance(kid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', kid):
            raise ValueError()
        if str(envelope.get('alg', '')).lower() != 'ecdsa' or envelope.get('digest') not in {'SHA1', 'SHA256'}:
            raise ValueError()
        signature = base64.b64decode(envelope['signature'], validate=True)
    except (ValueError, TypeError, KeyError):
        raise InvalidSignature('Invalid eBay signature envelope') from None
    material = keys(kid)
    try:
        if material.get('algorithm', '').upper() != 'ECDSA' or material.get('digest') != envelope['digest']:
            raise ValueError()
        pem = material['key']
        # The API may deliver PEM without newlines, as in eBay's SDK fixture.
        encoded = pem.replace('-----BEGIN PUBLIC KEY-----', '').replace('-----END PUBLIC KEY-----', '')
        pem = '-----BEGIN PUBLIC KEY-----\n' + ''.join(encoded.split()) + '\n-----END PUBLIC KEY-----\n'
        key = serialization.load_pem_public_key(pem.encode())
        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise ValueError()
        digest = hashes.SHA1() if envelope['digest'] == 'SHA1' else hashes.SHA256()
        key.verify(signature, raw, ec.ECDSA(digest))
    except (ValueError, KeyError, TypeError, CryptoInvalid):
        raise InvalidSignature('eBay signature verification failed') from None


def challenge(code, token, endpoint):
    if not isinstance(code, str) or not 1 <= len(code) <= 1024:
        raise ValueError('Invalid challenge')
    return {'challengeResponse': hashlib.sha256((code + token + endpoint).encode()).hexdigest()}


def validate_config(token, endpoint):
    parsed = urlsplit(endpoint)
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,80}', token):
        raise ValueError('Verification token must contain 32..80 permitted characters')
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path != ROUTE or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Configure the exact public HTTPS callback URL')


def receive(raw, header, ledger, keys, environment):
    verify_signature(raw, header, keys)
    try:
        payload = json.loads(raw)
        # Any schemaVersion: rejecting a future version would stop deletions and mark the endpoint down.
        if payload['metadata']['topic'] != 'MARKETPLACE_ACCOUNT_DELETION' or not isinstance(payload['metadata'].get('schemaVersion'), str):
            raise ValueError()
        notification = payload['notification']
        ledger.enqueue(notification['notificationId'], notification['data'], environment)
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid account deletion notification') from None


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/healthz':
            status = self.server.ledger.status()
            return self.reply(200 if status['ready'] else 503, status)
        if parsed.path != ROUTE:
            return self.reply(404, {'error': 'Not found'})
        try:
            params = parse_qs(parsed.query, strict_parsing=True)
            if set(params) != {'challenge_code'} or len(params['challenge_code']) != 1:
                raise ValueError()
            return self.reply(200, challenge(params['challenge_code'][0], self.server.token, self.server.endpoint))
        except (ValueError, KeyError):
            return self.reply(400, {'error': 'Invalid challenge'})

    def do_POST(self):
        if self.path != ROUTE:
            return self.reply(404, {'error': 'Not found'})
        try:
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                raise ValueError()
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536:
                return self.reply(413, {'error': 'Invalid body size'})
            if self.headers.get_content_type() != 'application/json':
                return self.reply(415, {'error': 'JSON required'})
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError()
            receive(raw, self.headers.get('X-EBAY-SIGNATURE'), self.server.ledger,
                    self.server.keys, self.server.environment)
        except InvalidSignature:
            return self.reply(412, {'error': 'Signature rejected'})
        except (ValueError, TypeError):
            return self.reply(400, {'error': 'Invalid notification'})
        except Exception:
            return self.reply(503, {'error': 'Retry notification later'})
        return self.reply(202, {'accepted': True})


def worker(ledger, stop):
    while not stop.is_set():
        try:
            if ledger.process_one():
                continue
            ledger.purge_expired()  # enforce retention even while the scanner is idle
        except Exception:
            # No payloads, URLs, account IDs or secrets in operational logs.
            print('eBay deletion cleanup failed; retry pending', flush=True)
        stop.wait(2)


def main():
    from local_config import load_ebay_config
    load_ebay_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--environment', choices=['production', 'sandbox'], default='production')
    parser.add_argument('--replay', action='store_true', help='Reapply retained tombstones after a controlled restore, before serving data')
    args = parser.parse_args()
    ledger = DeletionLedger(args.db)
    if args.replay:
        with closing(ledger.connect()) as db, db:
            db.execute("UPDATE ebay_deletion_events SET status='pending',error=NULL")
            db.execute('UPDATE ebay_deletion_state SET epoch=epoch+1')
        while ledger.process_one():
            pass
        return
    token, endpoint = os.environ.get('EBAY_DELETION_VERIFICATION_TOKEN', ''), os.environ.get('EBAY_DELETION_ENDPOINT', '')
    validate_config(token, endpoint)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.ledger, server.token, server.endpoint = ledger, token, endpoint
    server.keys, server.environment = PublicKeys(args.environment), args.environment
    stop = threading.Event()
    thread = threading.Thread(target=worker, args=(ledger, stop), daemon=True)
    thread.start()
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()
        thread.join(timeout=30)


if __name__ == '__main__':
    main()
