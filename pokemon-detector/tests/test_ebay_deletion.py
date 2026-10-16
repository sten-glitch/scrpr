"""Deletion acceptance tests use generated signatures and disposable data only."""
import base64
from contextlib import closing
import hashlib
import http.client
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ebay_deletion import DeletionLedger, DeletionBlocked
from ebay_deletion_server import (Handler, InvalidSignature, KeyUnavailable, ROUTE,
                                  challenge, receive, validate_config, verify_signature)
from http.server import ThreadingHTTPServer
from workspace import WorkspaceStore

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    CRYPTO = True
except ImportError:
    CRYPTO = False


def listing(item='a', user='alice', environment='production'):
    return {'title': 'Synthetic PSA card ' + item, 'asking_eur': 10,
            'source': 'ebay', 'external_id': item, 'environment': environment,
            'seller_identity': {'username': user, 'userId': 'id-' + user, 'eiasToken': 'eias-' + user}}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'workspace.sqlite'
        self.store = WorkspaceStore(self.path)
        self.ledger = self.store.deletions

    def query(self, sql, values=()):
        with closing(self.ledger.connect()) as db:
            return db.execute(sql, values).fetchall()

    def test_selective_deletion_children_and_other_account(self):
        a = self.store.create_listing(listing())
        b = self.store.create_listing(listing('b', 'bob'))
        self.ledger.enqueue('event', {'userId': 'id-alice'}, 'production')
        self.assertFalse(self.ledger.status()['ready'])
        self.assertTrue(self.ledger.process_one())
        self.assertEqual(self.query('SELECT id FROM listings'), [(b['id'],)])
        self.assertEqual(self.query('SELECT listing_id FROM events'), [(b['id'],)])
        self.assertTrue(self.ledger.status()['ready'])
        self.assertNotIn(b'alice', self.path.read_bytes())

    def test_duplicate_event_restart_and_no_raw_inbox(self):
        self.ledger.enqueue('event', {'username': 'alice'}, 'production')
        again = DeletionLedger(self.path)
        again.enqueue('event', {'username': 'alice'}, 'production')
        self.assertEqual(len(self.query('SELECT id FROM ebay_deletion_events')), 1)
        self.assertTrue(again.process_one())
        again.enqueue('event', {'username': 'alice'}, 'production')
        self.assertFalse(again.process_one())
        self.assertNotIn(b'alice', self.path.read_bytes())

    def test_aliases_block_before_worker_and_after_completion(self):
        self.store.create_listing(listing())
        self.ledger.enqueue('event', {'userId': 'id-alice'}, 'production')
        data = listing('new')
        data['seller_identity'] = {'username': 'alice'}
        for _ in range(2):
            with self.assertRaises(DeletionBlocked):
                self.store.create_listing(data)
            self.ledger.process_one()

    def test_eias_and_username_replaced_with_userid(self):
        self.store.create_listing(listing())
        self.ledger.enqueue('event', {'username': 'id-alice'}, 'production')
        self.ledger.process_one()
        self.assertEqual(self.query('SELECT id FROM listings'), [])
        with self.assertRaises(DeletionBlocked):
            self.store.create_listing(listing('new'))
        self.store.create_listing(listing('b', 'bob'))
        self.ledger.enqueue('event2', {'eiasToken': 'eias-bob'}, 'production')
        self.ledger.process_one()
        self.assertEqual(self.query('SELECT id FROM listings'), [])

    def test_environment_isolation(self):
        self.store.create_listing(listing(environment='sandbox'))
        self.ledger.enqueue('event', {'username': 'alice'}, 'production')
        self.ledger.process_one()
        self.assertEqual(len(self.query('SELECT id FROM listings')), 1)

    def test_mixed_snapshot_invalidated_other_snapshot_retained(self):
        a, b = listing(), listing('b', 'bob')
        b['observations'] = [{'marketplace': 'EBAY_GB', 'title': 'synthetic', 'price': {'value': '10'}}]
        mixed = self.store.save_supply_snapshot({'environment': 'production', 'listings': [a, b], 'groups': [{'certificate': 'synthetic'}]})
        kept = self.store.save_supply_snapshot({'environment': 'production', 'listings': [b]})
        self.ledger.enqueue('event', {'username': 'alice'}, 'production')
        self.ledger.process_one()
        self.assertIsNone(self.store.get_supply_snapshot(mixed))
        self.assertIsNotNone(self.store.get_supply_snapshot(kept))

    def test_legacy_unmapped_rows_and_unknown_import(self):
        data = listing()
        del data['seller_identity']
        self.store.create_listing(data)
        snapshot = self.store.save_supply_snapshot({'legacy_ocr': 'synthetic'})
        self.ledger.enqueue('event', {'userId': 'unmapped-id'}, 'production')
        self.ledger.process_one()
        self.assertEqual(self.query('SELECT id FROM listings'), [])
        self.assertIsNone(self.store.get_supply_snapshot(snapshot))
        with self.assertRaises(DeletionBlocked):
            self.store.create_listing(data)

    def test_username_only_cannot_evade_userid_deletion(self):
        data = listing()
        data['seller_identity'] = {'username': 'old-name'}
        self.store.create_listing(data)
        self.ledger.enqueue('event', {'userId': 'unmapped-id'}, 'production')
        self.ledger.process_one()
        self.assertEqual(self.query('SELECT id FROM listings'), [])

    def test_cache_selectivity_and_inflight_analysis(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow optional')
        import io
        from vision_cost_router import VisionCostRouter
        stream = io.BytesIO()
        Image.new('RGB', (20, 20)).save(stream, 'PNG')
        router = VisionCostRouter(self.path)
        analyzer = lambda *_: {'resolved': True, 'certificate': 'synthetic'}
        for data in [listing(), listing('b', 'bob')]:
            router.analyze_listing_image(stream.getvalue(), data, local_analyzer=analyzer)
        self.ledger.enqueue('event', {'userId': 'id-alice'}, 'production')
        self.ledger.process_one()
        self.assertEqual(len(self.query('SELECT cache_key FROM vision_cache')), 1)
        response = router.analyze_listing_image(stream.getvalue(), listing('b', 'bob'), local_analyzer=analyzer)
        self.assertTrue(response['cache_hit'])
        def racing_analyzer(*_):
            self.ledger.enqueue('event2', {'userId': 'id-charlie'}, 'production')
            self.ledger.process_one()
            return {'resolved': True}
        with self.assertRaises(DeletionBlocked):
            router.analyze_listing_image(stream.getvalue(), listing('c', 'charlie'), local_analyzer=racing_analyzer)
        self.assertEqual(len(self.query('SELECT cache_key FROM vision_cache')), 1)

    def test_inflight_snapshot_cannot_reappear(self):
        epoch = self.ledger.epoch()
        self.ledger.enqueue('event', {'username': 'alice'}, 'production')
        self.ledger.process_one()
        with self.assertRaises(DeletionBlocked):
            self.store.save_supply_snapshot({'environment': 'production', 'listings': [listing()]}, epoch=epoch)

    def test_managed_export_removed_and_path_confined(self):
        out = self.ledger.export('scan.json', {'offers': [listing()]}, scope='production', epoch=self.ledger.epoch())
        with self.assertRaises(ValueError):
            self.ledger.export('../outside.json', {}, scope='production', epoch=self.ledger.epoch())
        self.ledger.enqueue('event', {'username': 'alice'}, 'production')
        self.ledger.process_one()
        self.assertFalse(out.exists())

    def test_scanner_export_endpoint_and_deleted_snapshot(self):
        from local_app import AlphaServer
        snapshot = self.store.save_supply_snapshot({'environment': 'production', 'listings': [listing()]})
        server = AlphaServer(0, [], workspace_path=self.path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection(*server.server_address)
        self.addCleanup(conn.close)
        def export():
            conn.request('POST', '/api/graded/export', json.dumps({'snapshot_id': snapshot}), {'Content-Type': 'application/json'})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        status, body = export()
        self.assertEqual(status, 200)
        target = Path(body['saved_to'])
        self.assertTrue(target.exists())
        self.ledger.enqueue('event', {'userId': 'id-alice'}, 'production')
        self.ledger.process_one()
        self.assertFalse(target.exists())
        self.assertEqual(export()[0], 404)

    def test_failed_cleanup_retries_without_false_success(self):
        self.store.create_listing(listing())
        self.ledger.enqueue('event', {'username': 'alice'}, 'production')
        with patch.object(self.ledger, '_remove', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                self.ledger.process_one()
        self.assertEqual(self.ledger.status()['failures'], 1)
        self.assertEqual(len(self.query('SELECT id FROM listings')), 1)
        self.ledger.process_one()
        self.assertTrue(self.ledger.status()['ready'])

    def test_restore_requires_original_key(self):
        self.path.with_suffix('.sqlite.deletion-key').unlink()
        with self.assertRaises(DeletionBlocked):
            DeletionLedger(self.path)

    def test_replay_removes_restored_data(self):
        data = listing()
        self.store.create_listing(data)
        self.ledger.enqueue('event', {'username': 'alice'}, 'production')
        self.ledger.process_one()
        # Emulate restoring an old data row while retaining the deletion ledger.
        with closing(self.ledger.connect()) as db, db:
            db.execute("INSERT INTO listings(id,title,description,kind,source,source_url,external_id,asking_eur,status,created_at,updated_at,note) VALUES('old','restored','','single','ebay','','a',1,'INBOX','','','')")
            db.execute("UPDATE ebay_deletion_events SET status='pending'")
        self.ledger.process_one()
        self.assertEqual(self.query('SELECT id FROM listings'), [])


@unittest.skipUnless(CRYPTO, 'Install requirements-deletion.txt for signature tests')
class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = DeletionLedger(Path(self.temp.name) / 'db.sqlite')
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.material = {'key': self.private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(), 'algorithm': 'ECDSA', 'digest': 'SHA1'}
        self.payload = {'metadata': {'topic': 'MARKETPLACE_ACCOUNT_DELETION', 'schemaVersion': '1.0'}, 'notification': {'notificationId': 'event', 'data': {'username': 'alice'}}}
        self.raw = json.dumps(self.payload, separators=(',', ':')).encode()

    def signature(self, raw=None):
        sig = self.private.sign(raw or self.raw, ec.ECDSA(hashes.SHA1()))
        return base64.b64encode(json.dumps({'kid': 'test-key', 'alg': 'ecdsa', 'digest': 'SHA1', 'signature': base64.b64encode(sig).decode()}).encode()).decode()

    def test_challenge_exact_url(self):
        url = 'https://example.com' + ROUTE
        token = 'a' * 32
        validate_config(token, url)
        self.assertEqual(challenge('123', token, url)['challengeResponse'], hashlib.sha256(('123' + token + url).encode()).hexdigest())
        for bad in ['short', '!' * 32]:
            with self.assertRaises(ValueError):
                validate_config(bad, url)
        with self.assertRaises(ValueError):
            validate_config(token, url + '?bad=1')

    def test_signature_valid_and_tampered(self):
        sig = self.signature()
        verify_signature(self.raw, sig, lambda kid: self.material)
        with self.assertRaises(InvalidSignature):
            verify_signature(self.raw + b' ', sig, lambda kid: self.material)
        with self.assertRaises(InvalidSignature):
            verify_signature(self.raw, 'bad', lambda kid: self.material)

    def test_key_outage_and_rotation(self):
        def unavailable(kid):
            raise KeyUnavailable()
        with self.assertRaises(KeyUnavailable):
            receive(self.raw, self.signature(), self.ledger, unavailable, 'production')
        self.assertEqual(self.ledger.status()['pending'], 0)
        sig = self.signature()
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.material['key'] = self.private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        with self.assertRaises(InvalidSignature):
            verify_signature(self.raw, sig, lambda kid: self.material)
        verify_signature(self.raw, self.signature(), lambda kid: self.material)

    def test_http_ack_only_after_commit_and_invalid_signature(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.ledger, server.keys = self.ledger, lambda kid: self.material
        server.environment, server.token = 'production', 'a' * 32
        server.endpoint = 'https://example.com' + ROUTE
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        conn = http.client.HTTPConnection(*server.server_address)
        self.addCleanup(conn.close)
        conn.request('GET', ROUTE + '?challenge_code=123')
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        for signature, expected in [('invalid', 412), (self.signature(), 202)]:
            conn.request('POST', ROUTE, self.raw, {'Content-Type': 'application/json', 'X-EBAY-SIGNATURE': signature})
            response = conn.getresponse()
            self.assertEqual(response.status, expected)
            response.read()
        self.assertEqual(DeletionLedger(self.ledger.path).status()['pending'], 1)
        with patch.object(self.ledger, 'enqueue', side_effect=sqlite3.OperationalError()):
            conn.request('POST', ROUTE, self.raw, {'Content-Type': 'application/json', 'X-EBAY-SIGNATURE': self.signature()})
            response = conn.getresponse()
            self.assertEqual(response.status, 503)
            response.read()


if __name__ == '__main__':
    unittest.main()
