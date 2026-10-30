"""Local, transcript-free answer feedback and explicit style preferences."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from config import WORKSPACE_DIR

DB_PATH = Path(WORKSPACE_DIR) / "beru_feedback.db"
_LOCK = threading.RLock()

FEEDBACK_RATINGS = {"helpful", "not_helpful"}
FEEDBACK_REASONS = {
    "none", "accuracy", "incomplete", "format", "tool_selection", "slow", "other"
}
RESPONSE_STYLES = {
    "concise": "Prefer concise answers.",
    "detailed": "Give detailed explanations when useful.",
    "bullets": "Use bullet points when they make an answer easier to scan.",
    "plain_language": "Explain technical terms in plain language.",
}


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH), timeout=10)


def _initialize() -> None:
    Path(WORKSPACE_DIR).mkdir(parents=True, exist_ok=True)
    with _LOCK, closing(_connect()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS answer_feedback (
                conversation_id TEXT NOT NULL,
                message_index INTEGER NOT NULL CHECK(message_index >= 0),
                mode TEXT NOT NULL,
                rating TEXT NOT NULL CHECK(rating IN ('helpful', 'not_helpful')),
                reason TEXT NOT NULL,
                answer_sha256 TEXT NOT NULL,
                answer_characters INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (conversation_id, message_index)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS response_preferences (
                preference_key TEXT PRIMARY KEY CHECK(preference_key = 'response_style'),
                preference_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


_initialize()


def record_answer_feedback(
    conversation_id: str,
    message_index: int,
    mode: str,
    rating: str,
    reason: str,
    answer: str,
) -> None:
    """Save a rating and response hash; the prompt and answer text are not retained."""
    conversation_id = (conversation_id or "").strip()
    if not conversation_id or len(conversation_id) > 80:
        raise ValueError("Invalid conversation identifier.")
    if isinstance(message_index, bool) or not isinstance(message_index, int) or message_index < 0:
        raise ValueError("Invalid message index.")
    rating = (rating or "").strip().casefold()
    reason = (reason or "none").strip().casefold()
    if rating not in FEEDBACK_RATINGS or reason not in FEEDBACK_REASONS:
        raise ValueError("Choose a supported feedback rating and reason.")
    mode = (mode or "General").strip()[:64]
    answer = str(answer or "")
    answer_hash = hashlib.sha256(answer.encode("utf-8", errors="replace")).hexdigest()
    with _LOCK, closing(_connect()) as conn:
        conn.execute("""
            INSERT INTO answer_feedback
                (conversation_id, message_index, mode, rating, reason, answer_sha256, answer_characters)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id, message_index) DO UPDATE SET
                mode=excluded.mode, rating=excluded.rating, reason=excluded.reason,
                answer_sha256=excluded.answer_sha256, answer_characters=excluded.answer_characters,
                created_at=CURRENT_TIMESTAMP
        """, (conversation_id, message_index, mode, rating, reason, answer_hash, len(answer)))
        conn.commit()


def has_answer_feedback(conversation_id: str, message_index: int) -> bool:
    with _LOCK, closing(_connect()) as conn:
        row = conn.execute(
            "SELECT 1 FROM answer_feedback WHERE conversation_id=? AND message_index=?",
            (conversation_id, message_index),
        ).fetchone()
    return row is not None


def get_feedback_summary() -> dict[str, object]:
    """Return aggregate quality signals without exposing any conversation text."""
    with _LOCK, closing(_connect()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM answer_feedback").fetchone()[0]
        ratings = dict(conn.execute(
            "SELECT rating, COUNT(*) FROM answer_feedback GROUP BY rating"
        ).fetchall())
        reasons = dict(conn.execute(
            "SELECT reason, COUNT(*) FROM answer_feedback GROUP BY reason"
        ).fetchall())
    return {
        "total": int(total),
        "helpful": int(ratings.get("helpful", 0)),
        "not_helpful": int(ratings.get("not_helpful", 0)),
        "reasons": {str(key): int(value) for key, value in reasons.items()},
    }


def set_response_style_preference(style: str | None) -> None:
    """Persist one of the fixed, user-selected styles or clear the preference."""
    with _LOCK, closing(_connect()) as conn:
        if style is None:
            conn.execute("DELETE FROM response_preferences WHERE preference_key='response_style'")
        elif style in RESPONSE_STYLES:
            conn.execute("""
                INSERT INTO response_preferences(preference_key, preference_value)
                VALUES ('response_style', ?)
                ON CONFLICT(preference_key) DO UPDATE SET
                    preference_value=excluded.preference_value, updated_at=CURRENT_TIMESTAMP
            """, (style,))
        else:
            raise ValueError("Choose one of the supported response styles.")
        conn.commit()


def get_response_style_preference() -> str:
    """Return only a known, fixed style instruction; arbitrary text is never injected."""
    with _LOCK, closing(_connect()) as conn:
        row = conn.execute(
            "SELECT preference_value FROM response_preferences WHERE preference_key='response_style'"
        ).fetchone()
    value = row[0] if row else ""
    return RESPONSE_STYLES.get(value, "")
