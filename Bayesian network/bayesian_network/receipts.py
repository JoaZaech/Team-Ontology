"""SQLite transactional append-only local audit store. Trusted host filesystem boundary."""
import json
import sqlite3
from kg_rootcause.common import digest

class Conflict(ValueError):
    pass

class ReceiptStore:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), timeout=10)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS source_facts(hash TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS receipts(scope TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS resolutions(receipt_scope TEXT PRIMARY KEY REFERENCES receipts(scope), event_key TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS revocations(scope TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS spends(receipt_scope TEXT PRIMARY KEY REFERENCES receipts(scope), amount INTEGER NOT NULL);
        ''')
        for table in ('receipts','resolutions','revocations','spends','source_facts'):
            for operation in ('UPDATE','DELETE'):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable audit record'); END")
        self.db.commit()

    def lookup(self, scope, fingerprint):
        row = self.db.execute('SELECT fingerprint,body FROM receipts WHERE scope=?',(scope,)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise Conflict('idempotency key reused with different request/configuration')
            return json.loads(row[1])

    def save(self, scope, fingerprint, receipt, source_facts=()):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.lookup(scope, fingerprint)
            if old:
                return old
            required = {p['hash'] for p in (receipt.get('snapshot') or {}).get('provenance', [])}
            for fact in source_facts:
                fact_hash = digest(fact)
                if fact_hash in required:
                    self.db.execute('INSERT OR IGNORE INTO source_facts VALUES(?,?)', (fact_hash, json.dumps(fact, sort_keys=True, allow_nan=False)))
            for fact_hash in required:
                if not self.db.execute('SELECT 1 FROM source_facts WHERE hash=?', (fact_hash,)).fetchone():
                    raise ValueError('source version must be durable before receipt emission')
            authority = receipt['request'].get('authority_id')
            if authority and self.revoked(receipt['request']):
                receipt = dict(receipt, decision='decline', reason='AUTHORITY_REVOKED', analysis=None)
            receipt = dict(receipt, persisted=True)
            receipt['receipt_hash'] = digest(receipt)
            self.db.execute('INSERT INTO receipts VALUES(?,?,?)',(scope,fingerprint,json.dumps(receipt,sort_keys=True,allow_nan=False)))
            if receipt['decision'] == 'approve':
                self.db.execute('INSERT INTO spends VALUES(?,?)',(scope,receipt['request']['amount_cents']))
            return receipt

    def revoked(self, request):
        key = digest([request['tenant'],request['run'],request.get('authority_id')])
        return bool(self.db.execute('SELECT 1 FROM revocations WHERE scope=?',(key,)).fetchone())
