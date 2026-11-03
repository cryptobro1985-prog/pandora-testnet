"""One SQLite transaction contains portfolio, decisions and the journal cursor."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w') as f:
        f.write(encode(value)+'\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


class Store:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root/'paper.sqlite')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, seq INTEGER UNIQUE, payload TEXT NOT NULL)')

    def load(self):
        row = self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def commit(self, state, events):
        with self.db:
            for event in events:
                self.db.execute('INSERT INTO events VALUES(?,?,?)', (event['event_id'], event['seq'], encode(event)))
            self.db.execute('INSERT INTO state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (encode(state),))

    def recent_events(self, limit=80):
        return [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM events ORDER BY seq DESC LIMIT ?', (limit,))]

    def export(self, state):
        # Checkpoint includes complete journal; SQLite remains the live source.
        payload = {'schema_version': 1, 'saved_at': time.time(), 'state': state,
                   'events': [json.loads(r[0]) for r in self.db.execute('SELECT payload FROM events ORDER BY seq')]}
        envelope = {'payload': payload, 'sha256': hashlib.sha256(encode(payload).encode()).hexdigest()}
        atomic_json(self.root/'checkpoint.json', envelope)
        with (self.root/'journal.jsonl').open('w') as f:
            for event in payload['events']:
                f.write(encode(event)+'\n')
        return payload['saved_at']

    def restore(self, path):
        if self.load() is not None:
            raise ValueError('Refusing to overwrite existing state with a checkpoint')
        envelope = json.loads(Path(path).read_text())
        payload = envelope['payload']
        if hashlib.sha256(encode(payload).encode()).hexdigest() != envelope['sha256']:
            raise ValueError('Checkpoint checksum mismatch')
        state = payload['state']; events = payload['events']
        if payload['schema_version'] != 1 or state.get('schema_version') != 1:
            raise ValueError('Unsupported checkpoint schema')
        if state['seq'] != len(events) or any(e['seq'] != i+1 or e['session_id'] != state['session_id']
                                             for i, e in enumerate(events)):
            raise ValueError('Checkpoint journal cursor/session mismatch')
        # Reject non-finite numbers, duplicated IDs and broken accounting in Engine validation.
        encode(payload)
        self.commit(state, events)
        return state
