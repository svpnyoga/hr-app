import sqlite3
import os
from flask import g
import config


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(config.DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db_conn = g.pop("db", None)
    if db_conn is not None:
        db_conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def init_db():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(os.path.join(config.BASE_DIR, "schema.sql"), "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def query(sql, args=(), one=False):
    conn = get_db()
    cur = conn.execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, args=()):
    conn = get_db()
    cur = conn.execute(sql, args)
    conn.commit()
    lastrowid = cur.lastrowid
    cur.close()
    return lastrowid


def executemany(sql, seq_of_args):
    conn = get_db()
    conn.executemany(sql, seq_of_args)
    conn.commit()


def next_sequence(code, prefix=None, pad=4):
    """Atomically generate the next formatted document number for a sequence code."""
    conn = get_db()
    row = conn.execute("SELECT * FROM sequences WHERE code=?", (code,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO sequences (code, prefix, next_val, pad) VALUES (?,?,?,?)",
            (code, prefix or code, 1, pad),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM sequences WHERE code=?", (code,)).fetchone()
    number = row["next_val"]
    formatted = f"{row['prefix']}-{str(number).zfill(row['pad'])}"
    conn.execute("UPDATE sequences SET next_val = next_val + 1 WHERE code=?", (code,))
    conn.commit()
    return formatted
