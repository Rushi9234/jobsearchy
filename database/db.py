"""
db.py — Searchy Database Layer
SQLite3 wrapper for jobs, seen_jobs, notifications, and scrape_logs.
All other modules interact with the DB through this interface only.
"""

import os
import sqlite3
import json
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, Generator, Any

DB_PATH = Path(__file__).resolve().parent.parent / "searchy.db"
logger = logging.getLogger(__name__)


@contextmanager
def get_conn(db_path: Optional[str] = None) -> Generator[Any, None, None]:
    """
    Thread-safe connection context manager.
    If TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set, connects to Turso Cloud (LibSQL)
    so data survives container restarts on Render. Otherwise falls back to local searchy.db.
    """
    turso_url = os.getenv("TURSO_DATABASE_URL")
    turso_token = os.getenv("TURSO_AUTH_TOKEN")

    if turso_url and not db_path:
        try:
            import libsql_experimental as libsql
            conn = libsql.connect(database=turso_url, auth_token=turso_token)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return
        except ImportError:
            logger.debug("[DB] libsql_experimental not installed. Using local SQLite.")
        except Exception as e:
            logger.warning("[DB] Failed to connect to Turso cloud: %s. Falling back to local SQLite.", e)

    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Create all tables and indexes. Safe to call multiple times."""
    with get_conn(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT    NOT NULL,
                source          TEXT    NOT NULL,
                title           TEXT    NOT NULL,
                company         TEXT,
                location        TEXT,
                duration        TEXT,
                stipend         TEXT,
                url             TEXT    NOT NULL,
                tags            TEXT,       -- JSON array of skill tags
                description     TEXT,
                match_score     REAL    DEFAULT 0.0,
                is_notified     INTEGER DEFAULT 0,
                is_saved        INTEGER DEFAULT 0,
                is_applied      INTEGER DEFAULT 0,
                scraped_at      TEXT    NOT NULL,
                created_at      TEXT    DEFAULT (datetime('now')),
                UNIQUE (job_id, source)
            );

            CREATE TABLE IF NOT EXISTS seen_jobs (
                job_id  TEXT NOT NULL,
                source  TEXT NOT NULL,
                seen_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (job_id, source)
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      TEXT NOT NULL,
                source      TEXT NOT NULL,
                channel     TEXT NOT NULL,   -- 'telegram' | 'email'
                status      TEXT NOT NULL,   -- 'sent' | 'failed'
                sent_at     TEXT DEFAULT (datetime('now')),
                error_msg   TEXT
            );

            CREATE TABLE IF NOT EXISTS scrape_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source      TEXT NOT NULL,
                status      TEXT NOT NULL,   -- 'success' | 'error'
                jobs_found  INTEGER DEFAULT 0,
                jobs_new    INTEGER DEFAULT 0,
                message     TEXT,
                logged_at   TEXT DEFAULT (datetime('now'))
            );

            -- Performance indexes
            CREATE INDEX IF NOT EXISTS idx_jobs_score   ON jobs(match_score DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_source  ON jobs(source);
            CREATE INDEX IF NOT EXISTS idx_jobs_notify  ON jobs(is_notified);
            CREATE INDEX IF NOT EXISTS idx_jobs_saved   ON jobs(is_saved);

            -- Application tracker table
            CREATE TABLE IF NOT EXISTS app_tracker (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                company     TEXT    NOT NULL,
                role        TEXT    NOT NULL,
                url         TEXT,
                stage       TEXT    NOT NULL DEFAULT 'Applied',
                note        TEXT,
                applied_at  TEXT    DEFAULT (date('now')),
                updated_at  TEXT    DEFAULT (datetime('now'))
            );
        """)
    logger.info("Database initialized at %s", DB_PATH)


def is_seen(job_id: str, source: str, db_path: Optional[str] = None) -> bool:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_jobs WHERE job_id=? AND source=?", (job_id, source)
        ).fetchone()
        return row is not None


def mark_seen(job_id: str, source: str, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_jobs (job_id, source) VALUES (?,?)",
            (job_id, source),
        )


def insert_job(job: dict, db_path: Optional[str] = None) -> bool:
    """
    Insert a job dict. Returns True if inserted (new), False if duplicate.
    Expected keys: job_id, source, title, company, location, duration,
                   stipend, url, tags(list), description, match_score, scraped_at
    """
    tags_json = json.dumps(job.get("tags", []))
    scraped_at = job.get("scraped_at", datetime.now().isoformat())
    try:
        with get_conn(db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO jobs
                    (job_id, source, title, company, location, duration,
                     stipend, url, tags, description, match_score, scraped_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                job["job_id"], job["source"], job["title"],
                job.get("company"), job.get("location"), job.get("duration"),
                job.get("stipend"), job["url"], tags_json,
                job.get("description"), job.get("match_score", 0.0), scraped_at,
            ))
            return conn.execute(
                "SELECT changes()"
            ).fetchone()[0] > 0
    except sqlite3.IntegrityError:
        return False


def get_unnotified_jobs(
    min_score: float = 0.0,
    limit: int = 50,
    db_path: Optional[str] = None,
) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM jobs
            WHERE is_notified = 0 AND match_score >= ?
            ORDER BY match_score DESC, scraped_at DESC
            LIMIT ?
        """, (min_score, limit)).fetchall()
        return [dict(r) for r in rows]


def get_top_jobs(
    limit: int = 20,
    min_score: float = 0.0,
    source: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    query = "SELECT * FROM jobs WHERE match_score >= ?"
    params: list = [min_score]
    if source:
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY match_score DESC, scraped_at DESC LIMIT ?"
    params.append(limit)
    with get_conn(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_all_jobs(
    limit: int = 200,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY scraped_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def get_saved_jobs(db_path: Optional[str] = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE is_saved=1 ORDER BY match_score DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_notified(job_ids: list, db_path: Optional[str] = None) -> None:
    if not job_ids:
        return
    with get_conn(db_path) as conn:
        conn.executemany(
            "UPDATE jobs SET is_notified=1 WHERE id=? OR job_id=?",
            [(jid, str(jid)) for jid in job_ids],
        )


def toggle_saved(job_id: int, saved: bool, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET is_saved=? WHERE id=?",
            (1 if saved else 0, job_id),
        )


def log_notification(
    job_id: str, source: str, channel: str, status: str,
    error_msg: Optional[str] = None, db_path: Optional[str] = None,
) -> None:
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO notifications (job_id, source, channel, status, error_msg)
            VALUES (?,?,?,?,?)
        """, (job_id, source, channel, status, error_msg))


def log_scrape(
    source: str, status: str, jobs_found: int = 0,
    jobs_new: int = 0, message: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO scrape_logs (source, status, jobs_found, jobs_new, message)
            VALUES (?,?,?,?,?)
        """, (source, status, jobs_found, jobs_new, message))


def get_stats(db_path: Optional[str] = None) -> dict:
    with get_conn(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        new_today = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE DATE(scraped_at)=DATE('now')"
        ).fetchone()[0]
        top_score = conn.execute(
            "SELECT MAX(match_score) FROM jobs"
        ).fetchone()[0] or 0
        avg_score = conn.execute(
            "SELECT AVG(match_score) FROM jobs WHERE match_score > 0"
        ).fetchone()[0] or 0
        notified = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_notified=1"
        ).fetchone()[0]
        saved = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_saved=1"
        ).fetchone()[0]
        return {
            "total_jobs":      total,
            "new_today":       new_today,
            "top_score":       round(top_score, 1),
            "top_match_score": round(top_score, 1),  # kept for backward compat
            "avg_score":       round(avg_score, 1),
            "notified":        notified,
            "saved":           saved,
            "saved_jobs":      saved,  # kept for backward compat
        }


# ── Application Tracker CRUD ──────────────────────────────────────────────────
def get_tracker_entries(db_path: Optional[str] = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM app_tracker ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def add_tracker_entry(company: str, role: str, url: str = "",
                      stage: str = "Applied", note: str = "",
                      db_path: Optional[str] = None) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO app_tracker (company, role, url, stage, note) VALUES (?,?,?,?,?)",
            (company, role, url, stage, note)
        )
        return cur.lastrowid


def update_tracker_stage(entry_id: int, stage: str, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE app_tracker SET stage=?, updated_at=datetime('now') WHERE id=?",
            (stage, entry_id)
        )


def delete_tracker_entry(entry_id: int, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM app_tracker WHERE id=?", (entry_id,))


def update_match_scores(scores: dict[int, float], db_path: Optional[str] = None) -> None:
    """Batch update match scores: {job_db_id: score}"""
    with get_conn(db_path) as conn:
        conn.executemany(
            "UPDATE jobs SET match_score=? WHERE id=?",
            [(score, jid) for jid, score in scores.items()],
        )


if __name__ == "__main__":
    init_db()
    stats = get_stats()
    print("DB Stats:", json.dumps(stats, indent=2))
