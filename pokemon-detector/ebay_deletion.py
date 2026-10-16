"""Private, transactional eBay deletion ledger shared by receiver and writers.

Only keyed identifiers enter the inbox. Mixed derived artifacts are invalidated
as a whole: they must be regenerated, never served with stale counts/evidence.
The adjacent key and deletion ledger must survive every data restore.
"""
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time


class DeletionBlocked(ValueError):
    pass


def retention_hours():
    """API License 8.1(c)/3.1(b): listing data older than 6h may not be displayed; keep no longer by default."""
    hours = float(os.environ.get('BIGSTEN_EBAY_RETENTION_HOURS', '6'))
    if not 0 < hours <= 24 * 30:
        raise ValueError('BIGSTEN_EBAY_RETENTION_HOURS must be >0 and <=720')
    return hours


def seller_identity(item):
    seller = item.get('seller') or {}
    if isinstance(seller, str):
        seller = {'username': seller}
    return {k: seller[k] for k in ('username', 'userId', 'eiasToken')
            if isinstance(seller.get(k), str) and seller[k]}


class DeletionLedger:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        key_path = self.path.with_suffix(self.path.suffix + '.deletion-key')
        if not key_path.exists():
            # Never silently rotate the key on an existing ledger.
            if self.path.exists():
                with closing(sqlite3.connect(self.path)) as db:
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name='ebay_deletion_events'").fetchone():
                        raise DeletionBlocked('Deletion key missing; restore the original key before opening this workspace')
            try:
                with key_path.open('xb') as stream:
                    stream.write(secrets.token_bytes(32))
                os.chmod(key_path, 0o600)
            except FileExistsError:
                pass
        self.key = key_path.read_bytes()
        if len(self.key) != 32:
            raise DeletionBlocked('Invalid deletion key')
        with closing(self.connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS ebay_artifacts (
                    kind TEXT, id TEXT, scope TEXT, aliases TEXT, items TEXT,
                    unknown INTEGER, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS ebay_items (
                    scope TEXT, item TEXT, aliases TEXT, complete INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope,item));
                CREATE TABLE IF NOT EXISTS ebay_tombstones (
                    scope TEXT, alias TEXT, PRIMARY KEY(scope,alias));
                CREATE TABLE IF NOT EXISTS ebay_deletion_events (
                    id TEXT PRIMARY KEY, scope TEXT NOT NULL, aliases TEXT NOT NULL,
                    status TEXT NOT NULL, received REAL NOT NULL, completed REAL,
                    attempts INTEGER NOT NULL DEFAULT 0, error TEXT, removed INTEGER);
                CREATE TABLE IF NOT EXISTS ebay_deletion_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), epoch INTEGER NOT NULL);
                INSERT OR IGNORE INTO ebay_deletion_state VALUES(1,0);
            ''')
            if 'complete' not in {r[1] for r in db.execute('PRAGMA table_info(ebay_items)')}:
                db.execute('ALTER TABLE ebay_items ADD COLUMN complete INTEGER NOT NULL DEFAULT 0')
                db.commit()
            if 'created' not in {r[1] for r in db.execute('PRAGMA table_info(ebay_artifacts)')}:
                # Pre-existing artifacts start their retention clock at upgrade time.
                db.execute('ALTER TABLE ebay_artifacts ADD COLUMN created REAL')
                db.execute('UPDATE ebay_artifacts SET created=?', (time.time(),))
                db.commit()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA secure_delete=ON')
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def digest(self, kind, value):
        return hmac.new(self.key, (kind + '\0' + value).encode(), hashlib.sha256).hexdigest()

    def aliases(self, identity):
        if not isinstance(identity, dict):
            return set()
        # username can contain the immutable userId in current eBay payloads.
        return {self.digest('eias' if k == 'eiasToken' else 'account', v)
                for k, v in identity.items() if k in {'username', 'userId', 'eiasToken'}
                and isinstance(v, str) and 0 < len(v) <= 4096}

    def epoch(self, db=None):
        if db is not None:
            return db.execute('SELECT epoch FROM ebay_deletion_state').fetchone()[0]
        with closing(self.connect()) as db:
            return self.epoch(db)

    def register(self, db, kind, identifier, payload, *, scope=None, epoch=None):
        """Call inside BEGIN IMMEDIATE, in the same transaction as the write.

        Strips raw seller identifiers from ``payload`` in place: serialize it only after this call.
        """
        if epoch is not None and epoch != self.epoch(db):
            raise DeletionBlocked('Account deletion occurred during processing; retry with fresh inputs')
        scope = scope or (payload.get('environment') if isinstance(payload, dict) else None) or '*'
        if scope not in {'sandbox', 'production', '*'}:
            raise DeletionBlocked('Invalid eBay environment')
        aliases, items, unknown = set(), set(), False
        is_ebay = 'ebay' in json.dumps(payload, ensure_ascii=False).lower()

        def walk(obj):
            nonlocal unknown, is_ebay
            if isinstance(obj, list):
                for entry in obj:
                    walk(entry)
            elif isinstance(obj, dict):
                item = obj.get('item_id') or obj.get('itemId') or obj.get('external_id')
                ebay = str(obj.get('source', '')).lower().startswith('ebay') or (bool(item) and str(obj.get('marketplace', '')).lower().startswith('ebay')) or obj.get('seller_identity') is not None
                if ebay:
                    is_ebay = True
                    identity = obj.get('seller_identity') or seller_identity(obj)
                    found = self.aliases(identity)
                    complete = isinstance(identity, dict) and bool(identity.get('userId'))
                    if item:
                        hashed = self.digest('item', str(item))
                        items.add(hashed)
                        known = db.execute("SELECT aliases,complete FROM ebay_items WHERE (scope=? OR ?='*') AND item=?", (scope, scope, hashed)).fetchall()
                        for old_aliases, old_complete in known:
                            found.update(json.loads(old_aliases))
                            complete = complete or bool(old_complete)
                        if found:
                            db.execute('INSERT OR REPLACE INTO ebay_items VALUES(?,?,?,?)', (scope, hashed, json.dumps(sorted(found)), int(complete)))
                    aliases.update(found)
                    unknown = unknown or not found or not complete
                    # API License 8.2.1(c): raw eBay user IDs never reach storage; keyed aliases above keep deletion working.
                    obj.pop('seller_identity', None)
                    if isinstance(obj.get('seller'), (str, dict)):
                        obj.pop('seller')
                for value in obj.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
        walk(payload)
        if not is_ebay:
            return
        unknown = unknown or not aliases
        tombstones = {r[0] for r in db.execute("SELECT alias FROM ebay_tombstones WHERE scope=? OR ?='*'", (scope, scope))}
        if aliases & tombstones or (unknown and tombstones):
            raise DeletionBlocked('eBay data suppressed or ownership unresolved after an account deletion')
        db.execute('INSERT OR REPLACE INTO ebay_artifacts(kind,id,scope,aliases,items,unknown,created) VALUES(?,?,?,?,?,?,?)',
                   (kind, identifier, scope, json.dumps(sorted(aliases)), json.dumps(sorted(items)), int(unknown), time.time()))

    def enforce(self):
        """Before any read/write: finish acknowledged deletions, then expire old data (fail closed on error)."""
        if self.status()['pending']:
            while self.process_one():
                pass
        self.purge_expired()

    def purge_expired(self, now=None):
        """Remove every registered eBay artifact older than the retention window. Returns count removed."""
        cutoff = (now or time.time()) - retention_hours() * 3600
        with closing(self.connect()) as db:
            if not db.execute('SELECT 1 FROM ebay_artifacts WHERE created<? LIMIT 1', (cutoff,)).fetchone():
                return 0  # common path: no write lock on reads
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            expired = db.execute('SELECT kind,id FROM ebay_artifacts WHERE created<?', (cutoff,)).fetchall()
            for kind, identifier in expired:
                self._remove(db, kind, identifier)
        return len(expired)

    def enqueue(self, event_id, identity, scope):
        aliases = self.aliases(identity)
        if not aliases or scope not in {'production', 'sandbox'} or not isinstance(event_id, str) or not 1 <= len(event_id) <= 256:
            raise ValueError('Invalid account deletion event')
        event_id = self.digest('event:' + scope, event_id)
        packed = json.dumps(sorted(aliases))
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT aliases FROM ebay_deletion_events WHERE id=?', (event_id,)).fetchone()
            if old:
                if old[0] != packed:
                    raise ValueError('Conflicting notification identifier')
                return event_id
            # Close known alias chains before ACK, so username-only writes are
            # suppressed even if this event arrived with immutable userId only.
            known = [set(json.loads(r[0])) for r in db.execute("SELECT aliases FROM ebay_items WHERE scope=? OR scope='*'", (scope,))]
            changed = True
            while changed:
                before = len(aliases)
                for group in known:
                    if aliases & group:
                        aliases.update(group)
                changed = len(aliases) != before
            db.execute('INSERT INTO ebay_deletion_events(id,scope,aliases,status,received) VALUES(?,?,?,?,?)',
                       (event_id, scope, packed, 'pending', time.time()))
            db.executemany('INSERT OR IGNORE INTO ebay_tombstones VALUES(?,?)', [(scope, a) for a in aliases])
            db.execute('UPDATE ebay_deletion_state SET epoch=epoch+1')
        return event_id

    def process_one(self):
        """Retry-safe worker; errors remain pending and readiness becomes unhealthy."""
        event_id = None
        try:
            with closing(self.connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute("SELECT id,scope,aliases FROM ebay_deletion_events WHERE status='pending' ORDER BY received LIMIT 1").fetchone()
                if not row:
                    return False
                event_id, scope, raw = row
                aliases = set(json.loads(raw))
                aliases.update(r[0] for r in db.execute('SELECT alias FROM ebay_tombstones WHERE scope=?', (scope,)))
                affected_items = {r[0] for r in db.execute("SELECT item,aliases FROM ebay_items WHERE scope=? OR scope='*'", (scope,)) if aliases & set(json.loads(r[1]))}
                artifacts = db.execute("SELECT kind,id,aliases,items,unknown FROM ebay_artifacts WHERE scope=? OR scope='*'", (scope,)).fetchall()
                removed = 0
                for kind, identifier, owners, items, unknown in artifacts:
                    if unknown or aliases & set(json.loads(owners)) or affected_items & set(json.loads(items)):
                        self._remove(db, kind, identifier)
                        removed += 1
                # Pre-migration rows have no reliable ownership; invalidate conservatively.
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'listings' in tables:
                    for (identifier,) in db.execute("SELECT id FROM listings WHERE (source='ebay' OR lower(source_url) LIKE '%ebay.%') AND id NOT IN (SELECT id FROM ebay_artifacts WHERE kind='listing')").fetchall():
                        self._remove(db, 'listing', identifier)
                        removed += 1
                for table, kind, column in [('supply_snapshots','snapshot','id'), ('vision_cache','cache','cache_key')]:
                    if table in tables:
                        # Old OCR snapshots can have no source at all; absence is not proof of independence.
                        for (identifier,) in db.execute(f"SELECT {column} FROM {table} WHERE {column} NOT IN (SELECT id FROM ebay_artifacts WHERE kind=? OR kind=?)", (kind, 'independent_' + kind)).fetchall():
                            self._remove(db, kind, identifier)
                            removed += 1
                if 'vision_budget' in tables:
                    # Keep cost totals; erase unindexed listing references, including old reservations.
                    db.execute("UPDATE vision_budget SET listing_id='' WHERE listing_id<>''")
                for item in affected_items:
                    db.execute("DELETE FROM ebay_items WHERE item=? AND (scope=? OR scope='*')", (item, scope))
                db.execute("UPDATE ebay_deletion_events SET attempts=attempts+1,error=NULL,removed=? WHERE id=?", (removed, event_id))
            # ACK was durable, but completion also requires SQLite maintenance.
            # This does not erase external backups or SSD/volume snapshots.
            with closing(self.connect()) as db:
                if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                    raise DeletionBlocked('SQLite checkpoint busy')
                db.execute('VACUUM')
                if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                    raise DeletionBlocked('SQLite checkpoint busy')
            with closing(self.connect()) as db, db:
                db.execute("UPDATE ebay_deletion_events SET status='complete',completed=?,error=NULL WHERE id=?", (time.time(), event_id))
            return True
        except Exception:
            if event_id:
                with closing(self.connect()) as db, db:
                    db.execute("UPDATE ebay_deletion_events SET attempts=attempts+1,error='storage_cleanup_failed' WHERE id=?", (event_id,))
            raise

    def _remove(self, db, kind, identifier):
        if kind == 'listing':
            for table in ('events', 'scenarios', 'trades'):
                db.execute(f'DELETE FROM {table} WHERE listing_id=?', (identifier,))
            db.execute('DELETE FROM listings WHERE id=?', (identifier,))
        elif kind in {'snapshot', 'cache'}:
            table, column = ('supply_snapshots', 'id') if kind == 'snapshot' else ('vision_cache', 'cache_key')
            db.execute(f'DELETE FROM {table} WHERE {column}=?', (identifier,))
        elif kind == 'export':
            root = self.path.parent / 'managed_ebay_exports'
            target = (root / identifier).resolve()
            if target.parent != root.resolve() or target.is_symlink():
                raise DeletionBlocked('Unsafe managed export path')
            target.unlink(missing_ok=True)
        else:
            raise DeletionBlocked('Unknown deletion artifact adapter')
        db.execute('DELETE FROM ebay_artifacts WHERE kind=? AND id=?', (kind, identifier))

    def export(self, name, payload, *, scope, epoch):
        if Path(name).name != name or not name.endswith('.json'):
            raise ValueError('Export must be a JSON filename, without directories')
        root = self.path.parent / 'managed_ebay_exports'
        root.mkdir(exist_ok=True)
        target = root / name
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self.register(db, 'export', name, payload, scope=scope, epoch=epoch)
            # Commit registry first: a crash can leave an absent file, never an unregistered file.
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self.register(db, 'export', name, payload, scope=scope, epoch=epoch)
            if target.is_symlink():
                raise DeletionBlocked('Unsafe export target')
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return target

    def status(self):
        with closing(self.connect()) as db:
            pending, failures = db.execute("SELECT COUNT(*),COALESCE(SUM(error IS NOT NULL),0) FROM ebay_deletion_events WHERE status='pending'").fetchone()
            return {'pending': pending, 'failures': failures, 'ready': pending == 0}
