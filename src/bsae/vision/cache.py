"""Per-frame transaction checkpoints. Cache is independent of selected player."""
import json
import sqlite3


class Cache:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS frames (key TEXT, t REAL, payload TEXT, PRIMARY KEY(key,t))')
        self.db.execute('CREATE TABLE IF NOT EXISTS complete (key TEXT PRIMARY KEY)')

    def rows(self, key):
        for t, payload in self.db.execute('SELECT t,payload FROM frames WHERE key=? ORDER BY t', (key,)):
            yield t, json.loads(payload)

    def put(self, key, t, payload):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO frames VALUES(?,?,?)', (key, t, json.dumps(payload, allow_nan=False)))

    def complete(self, key):
        return self.db.execute('SELECT 1 FROM complete WHERE key=?', (key,)).fetchone() is not None

    def finish(self, key):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO complete VALUES(?)', (key,))

    def close(self):
        self.db.close()
