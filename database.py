import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(__file__).with_name("news.db")


@contextmanager
def connect():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    try:
        yield connection
    finally:
        connection.close()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db():
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY,
                channel TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL,
                link TEXT,
                seen_at TEXT NOT NULL,
                UNIQUE(channel, message_id)
            );

            CREATE TABLE IF NOT EXISTS subscribers (
                chat_id INTEGER PRIMARY KEY,
                active INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_posts_channel_date
            ON posts(channel, date DESC);
            """
        )


def save_post(channel, message_id, text, date, link):
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO posts
            (channel, message_id, text, date, link, seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (channel, message_id, text, date, link, utc_now()),
        )
        connection.commit()
        return cursor.rowcount > 0


def latest_posts(channel=None, limit=10):
    query = (
        "SELECT channel, message_id, text, date, link "
        "FROM posts "
        "WHERE 1=1 "
    )
    params = []
    if channel:
        query += "AND lower(channel)=lower(?) "
        params.append(channel)
    query += "ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)
    with connect() as connection:
        return connection.execute(query, params).fetchall()


def add_subscriber(chat_id):
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO subscribers(chat_id, active, added_at)
            VALUES (?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET active=1
            """,
            (chat_id, utc_now()),
        )
        connection.commit()


def remove_subscriber(chat_id):
    with connect() as connection:
        connection.execute(
            "UPDATE subscribers SET active=0 WHERE chat_id=?",
            (chat_id,),
        )
        connection.commit()


def active_subscribers():
    with connect() as connection:
        return [
            row[0]
            for row in connection.execute(
                "SELECT chat_id FROM subscribers WHERE active=1"
            ).fetchall()
        ]
