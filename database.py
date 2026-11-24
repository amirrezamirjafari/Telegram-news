import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
                relevant INTEGER NOT NULL DEFAULT 0,
                normalized_hash TEXT,
                duplicate_of_channel TEXT,
                duplicate_of_message_id INTEGER,
                duplicate_similarity REAL,
                dedup_method TEXT,
                analysis_json TEXT,
                impact_score INTEGER,
                analysis_status TEXT NOT NULL DEFAULT 'pending',
                analysis_error TEXT,
                analysis_attempts INTEGER NOT NULL DEFAULT 0,
                next_retry_at TEXT,
                raw_sent INTEGER NOT NULL DEFAULT 0,
                analyzed_at TEXT,
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
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(posts)")
        }
        migrations = {
            "relevant": "INTEGER NOT NULL DEFAULT 0",
            "normalized_hash": "TEXT",
            "duplicate_of_channel": "TEXT",
            "duplicate_of_message_id": "INTEGER",
            "duplicate_similarity": "REAL",
            "dedup_method": "TEXT",
            "analysis_json": "TEXT",
            "impact_score": "INTEGER",
            "analysis_status": "TEXT NOT NULL DEFAULT 'pending'",
            "analysis_error": "TEXT",
            "analysis_attempts": "INTEGER NOT NULL DEFAULT 0",
            "next_retry_at": "TEXT",
            "analyzed_at": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE posts ADD COLUMN {column} {definition}"
                )
        if "raw_sent" not in columns:
            connection.execute(
                "ALTER TABLE posts ADD COLUMN raw_sent INTEGER NOT NULL DEFAULT 0"
            )
            connection.execute(
                "UPDATE posts SET raw_sent=1 WHERE analysis_status='failed'"
            )
        connection.execute(
            """
            UPDATE posts SET next_retry_at=?
            WHERE analysis_status='failed' AND analysis_attempts=0
              AND next_retry_at IS NULL
            """,
            (utc_now(),),
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_posts_relevant_seen
            ON posts(relevant, seen_at DESC)
            """
        )
        connection.commit()


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


def mark_post_relevant(channel, message_id, relevant, normalized_hash=None):
    with connect() as connection:
        connection.execute(
            """
            UPDATE posts
            SET relevant=?, normalized_hash=?,
                analysis_status=CASE WHEN ?=1 THEN analysis_status ELSE 'filtered' END,
                next_retry_at=CASE WHEN ?=1 THEN next_retry_at ELSE NULL END
            WHERE channel=? AND message_id=?
            """,
            (
                int(relevant),
                normalized_hash,
                int(relevant),
                int(relevant),
                channel,
                message_id,
            ),
        )
        connection.commit()


def mark_post_advertisement(channel, message_id):
    with connect() as connection:
        connection.execute(
            """
            UPDATE posts
            SET relevant=0, analysis_status='advertisement', analysis_json=NULL,
                analysis_error=NULL, impact_score=NULL, next_retry_at=NULL
            WHERE channel=? AND message_id=?
            """,
            (channel, message_id),
        )
        connection.commit()


def mark_analysis_not_required(channel, message_id):
    with connect() as connection:
        connection.execute(
            """
            UPDATE posts
            SET analysis_status='not_required', analysis_json=NULL,
                analysis_error=NULL, impact_score=NULL, next_retry_at=NULL
            WHERE channel=? AND message_id=?
            """,
            (channel, message_id),
        )
        connection.commit()


def mark_raw_sent(channel, message_id):
    with connect() as connection:
        connection.execute(
            "UPDATE posts SET raw_sent=1 WHERE channel=? AND message_id=?",
            (channel, message_id),
        )
        connection.commit()


def post_processing_status(channel, message_id):
    with connect() as connection:
        return connection.execute(
            """
            SELECT relevant, analysis_status, duplicate_of_channel,
                   analysis_attempts, next_retry_at, raw_sent
            FROM posts WHERE channel=? AND message_id=?
            """,
            (channel, message_id),
        ).fetchone()


def begin_analysis_attempt(channel, message_id, max_attempts):
    now = utc_now()
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE posts
            SET analysis_attempts=analysis_attempts+1,
                analysis_status='analyzing', analysis_error=NULL,
                next_retry_at=NULL
            WHERE channel=? AND message_id=? AND analysis_attempts<?
              AND (
                analysis_status='pending'
                OR (
                    analysis_status='failed' AND next_retry_at IS NOT NULL
                    AND next_retry_at<=?
                )
              )
            """,
            (channel, message_id, max_attempts, now),
        )
        if not cursor.rowcount:
            return None
        row = connection.execute(
            """
            SELECT analysis_attempts FROM posts
            WHERE channel=? AND message_id=?
            """,
            (channel, message_id),
        ).fetchone()
        connection.commit()
        return row[0]


def retryable_posts(max_attempts, limit=100):
    now = utc_now()
    with connect() as connection:
        return connection.execute(
            """
            SELECT channel, message_id, text, date, link
            FROM posts
            WHERE analysis_status='failed' AND next_retry_at IS NOT NULL
              AND next_retry_at<=? AND analysis_attempts<?
            ORDER BY next_retry_at, id
            LIMIT ?
            """,
            (now, max_attempts, limit),
        ).fetchall()


def recover_interrupted_analyses(max_attempts):
    now = utc_now()
    with connect() as connection:
        connection.execute(
            """
            UPDATE posts
            SET analysis_status='failed',
                analysis_error='Analysis interrupted before completion',
                next_retry_at=CASE WHEN analysis_attempts<?
                    THEN ? ELSE NULL END
            WHERE analysis_status='analyzing'
            """,
            (max_attempts, now),
        )
        connection.commit()


def find_duplicate(normalized_text, normalized_hash, exclude_channel,
                   exclude_message_id, days=7, threshold=0.88):
    if not normalized_text:
        return None

    from difflib import SequenceMatcher

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    with connect() as connection:
        exact = connection.execute(
            """
            SELECT channel, message_id
            FROM posts
            WHERE relevant=1 AND duplicate_of_channel IS NULL
              AND normalized_hash=?
              AND NOT (channel=? AND message_id=?)
              AND seen_at>=?
            ORDER BY seen_at DESC LIMIT 1
            """,
            (normalized_hash, exclude_channel, exclude_message_id, cutoff),
        ).fetchone()
        if exact:
            return exact[0], exact[1], 1.0, "exact"

        candidates = connection.execute(
            """
            SELECT channel, message_id, text, normalized_hash
            FROM posts
            WHERE relevant=1 AND duplicate_of_channel IS NULL
              AND text!=''
              AND NOT (channel=? AND message_id=?)
              AND seen_at>=?
            ORDER BY seen_at DESC LIMIT 1000
            """,
            (exclude_channel, exclude_message_id, cutoff),
        ).fetchall()

    best = None
    for channel, message_id, text, candidate_hash in candidates:
        candidate_text = normalize_for_comparison(text)
        if not candidate_text:
            continue
        if candidate_hash == normalized_hash:
            similarity = 1.0
        elif min(len(normalized_text), len(candidate_text)) < 50:
            continue
        else:
            similarity = SequenceMatcher(
                None, normalized_text, candidate_text
            ).ratio()
        if similarity >= threshold and (best is None or similarity > best[2]):
            best = (channel, message_id, similarity, "near")
    return best


def normalize_for_comparison(text):
    import re
    import unicodedata

    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[@#][\w_]+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def mark_duplicate(channel, message_id, original_channel, original_message_id,
                   similarity, method):
    with connect() as connection:
        connection.execute(
            """
            UPDATE posts
            SET duplicate_of_channel=?, duplicate_of_message_id=?,
                duplicate_similarity=?, dedup_method=?,
                analysis_status='duplicate', next_retry_at=NULL
            WHERE channel=? AND message_id=?
            """,
            (
                original_channel,
                original_message_id,
                similarity,
                method,
                channel,
                message_id,
            ),
        )
        connection.commit()


def save_analysis(channel, message_id, analysis):
    import json

    with connect() as connection:
        connection.execute(
            """
            UPDATE posts
            SET analysis_json=?, impact_score=?, analysis_status='complete',
                analysis_error=NULL, next_retry_at=NULL, analyzed_at=?
            WHERE channel=? AND message_id=?
            """,
            (
                json.dumps(analysis, ensure_ascii=False),
                analysis.get("impact_score"),
                utc_now(),
                channel,
                message_id,
            ),
        )
        connection.commit()


def save_analysis_error(channel, message_id, error, retry_after_seconds=None):
    next_retry_at = None
    if retry_after_seconds is not None:
        retry_at = datetime.now(timezone.utc) + timedelta(
            seconds=max(0, retry_after_seconds)
        )
        next_retry_at = retry_at.isoformat(timespec="seconds")
    with connect() as connection:
        connection.execute(
            """
            UPDATE posts
            SET analysis_status='failed', analysis_error=?, next_retry_at=?
            WHERE channel=? AND message_id=?
            """,
            (error, next_retry_at, channel, message_id),
        )
        connection.commit()


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


def latest_news(channel=None, limit=10):
    query = (
        "SELECT channel, message_id, text, date, link, analysis_json, "
        "analysis_status, analysis_error FROM posts "
        "WHERE relevant=1 AND duplicate_of_channel IS NULL "
        "AND analysis_status!='advertisement' "
    )
    params = []
    if channel:
        query += "AND lower(channel)=lower(?) "
        params.append(channel)
    query += (
        "ORDER BY CASE WHEN impact_score IS NULL THEN 1 ELSE 0 END, "
        "impact_score DESC, date DESC, id DESC LIMIT ?"
    )
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
