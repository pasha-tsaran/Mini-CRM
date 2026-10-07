"""Постоянное состояние и inbox/replies бота в SQLite, не в JSON-файлах."""
import json
import hashlib
from copy import deepcopy
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class StateStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY CHECK(id=1), next_offset INTEGER NOT NULL);
                INSERT OR IGNORE INTO progress VALUES (1, 0);
                CREATE TABLE IF NOT EXISTS inbox (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS dialogs (user_id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS replies (
                    id INTEGER PRIMARY KEY, update_id INTEGER NOT NULL UNIQUE, chat_id INTEGER NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt REAL NOT NULL DEFAULT 0, lease_until REAL,
                    message_id INTEGER, error_code INTEGER
                );
            ''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def offset(self):
        with self.connect() as connection:
            return connection.execute('SELECT next_offset FROM progress WHERE id=1').fetchone()[0]

    def receive(self, updates):
        # Вся полученная пачка и новый offset записываются одним commit ДО следующего getUpdates.
        with self.connect() as connection:
            for update in updates:
                update = deepcopy(update)
                message = update.get('message', {})
                if message.get('chat', {}).get('type') != 'private':
                    # В группах не сохраняем присланные имя, телефон или текст.
                    update = {'update_id': update['update_id'], 'message': {
                        'chat': message.get('chat', {}), 'from': {'id': message.get('from', {}).get('id')},
                    }}
                elif isinstance(message.get('text'), str):
                    parts = message['text'].split(maxsplit=1)
                    if len(parts) == 2 and parts[0].split('@')[0] == '/start':
                        message['text'] = '/start ' + hashlib.sha256(parts[1].strip().encode()).hexdigest()
                connection.execute('INSERT OR IGNORE INTO inbox(id,payload) VALUES (?,?)',
                                   (update['update_id'], json.dumps(update, ensure_ascii=False)))
            if updates:
                connection.execute('UPDATE progress SET next_offset=max(next_offset, ?) WHERE id=1',
                                   (max(item['update_id'] for item in updates) + 1,))

    def next_update(self):
        with self.connect() as connection:
            row = connection.execute('SELECT payload FROM inbox WHERE done=0 ORDER BY id LIMIT 1').fetchone()
            return json.loads(row[0]) if row else None

    def dialog(self, user_id):
        with self.connect() as connection:
            row = connection.execute('SELECT payload FROM dialogs WHERE user_id=?', (user_id,)).fetchone()
            return json.loads(row[0]) if row else {'step': 'idle'}

    def save_dialog(self, user_id, state):
        with self.connect() as connection:
            connection.execute('INSERT INTO dialogs VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload',
                               (user_id, json.dumps(state, ensure_ascii=False)))

    def complete(self, update_id, user_id=None, state=None, chat_id=None, reply=None):
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if user_id is not None:
                connection.execute('INSERT INTO dialogs VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload',
                                   (user_id, json.dumps(state, ensure_ascii=False)))
            if reply:
                connection.execute('INSERT OR IGNORE INTO replies(update_id,chat_id,payload) VALUES (?,?,?)',
                                   (update_id, chat_id, json.dumps(reply, ensure_ascii=False)))
            # Стираем входной текст (в том числе start-код), сохраняя id для дедупликации.
            connection.execute("UPDATE inbox SET done=1,payload='{}' WHERE id=?", (update_id,))

    def claim_reply(self, now):
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('''SELECT * FROM replies r WHERE
                ((state IN ('pending','retry') AND next_attempt<=?) OR (state='processing' AND lease_until<=?))
                AND NOT EXISTS (SELECT 1 FROM replies older WHERE older.chat_id=r.chat_id AND older.id<r.id
                    AND older.state IN ('pending','retry','processing')) ORDER BY id LIMIT 1''', (now, now)).fetchone()
            if row:
                connection.execute("UPDATE replies SET state='processing', attempts=attempts+1, lease_until=? WHERE id=?", (now + 60, row['id']))
                return dict(row)

    def finish_reply(self, row, now, message_id=None, error=None):
        with self.connect() as connection:
            if error is None:
                connection.execute("UPDATE replies SET state='sent',message_id=?,payload='{}',lease_until=NULL WHERE id=?", (message_id, row['id']))
            elif error.code in (400, 401, 403, 404):
                connection.execute("UPDATE replies SET state='failed',error_code=?,lease_until=NULL WHERE id=?", (error.code, row['id']))
                if error.code == 403:
                    connection.execute("UPDATE replies SET state='failed',error_code=403 WHERE chat_id=? AND state IN ('pending','retry','processing')", (row['chat_id'],))
            else:
                delay = max(error.retry_after, min(3600, 5 * 2 ** min(row['attempts'] + 1, 10)))
                connection.execute("UPDATE replies SET state='retry',error_code=?,next_attempt=?,lease_until=NULL WHERE id=?", (error.code, now + delay, row['id']))
