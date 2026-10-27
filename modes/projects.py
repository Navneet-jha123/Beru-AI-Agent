"""Privacy-aware persistent project context for BERU AI Agent.

Project metadata and notes are stored locally in workspace/beru_projects.db.
Only files inside BERU's canonical workspace may be tracked.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

from config import WORKSPACE_DIR
from modes.developer import _resolve_path, is_safe_dev_path

DB_PATH = WORKSPACE_DIR / "beru_projects.db"
_DB_LOCK = threading.RLock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_db() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    with _DB_LOCK, _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                goal TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS project_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS project_files (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                last_modified REAL NOT NULL,
                PRIMARY KEY (project_id, file_path)
            );
            CREATE TABLE IF NOT EXISTS project_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                action_type TEXT NOT NULL,
                action_data TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_project
                ON projects(active) WHERE active = 1;
        """)


_init_db()


def _safe_text(value: str, field: str, limit: int) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{field} is required.")
    if len(value) > limit:
        raise ValueError(f"{field} must be {limit} characters or fewer.")
    return value


def _record_action(conn: sqlite3.Connection, project_id: str, action_type: str, data: str) -> None:
    conn.execute(
        "INSERT INTO project_actions(project_id, action_type, action_data) VALUES (?, ?, ?)",
        (project_id, action_type[:40], data[:1000]),
    )


def create_project(name: str, goal: str) -> str:
    """Create and activate a project. Notes/context are local and unencrypted."""
    try:
        name = _safe_text(name, "name", 80)
        goal = _safe_text(goal, "goal", 2000)
        project_id = uuid.uuid4().hex[:12]
        with _DB_LOCK, _connect() as conn:
            conn.execute("UPDATE projects SET active = 0 WHERE active = 1")
            conn.execute(
                "INSERT INTO projects(id, name, goal, active) VALUES (?, ?, ?, 1)",
                (project_id, name, goal),
            )
            _record_action(conn, project_id, "created", "Project created and activated")
        return f"Created and activated project '{name}' (id={project_id})."
    except (ValueError, sqlite3.IntegrityError) as exc:
        return f"Failed to create project: {exc}"
    except sqlite3.Error as exc:
        return f"Project database error: {exc}"


def list_projects() -> str:
    try:
        with _DB_LOCK, _connect() as conn:
            rows = conn.execute(
                "SELECT id, name, goal, active, created_at FROM projects ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        if not rows:
            return "No saved projects."
        return "\n".join(
            f"{'* ' if r['active'] else ''}{r['name']} (id={r['id']}) — {r['goal'][:160]}"
            for r in rows
        )
    except sqlite3.Error as exc:
        return f"Project database error: {exc}"


def activate_project(project_id: str) -> str:
    project_id = (project_id or "").strip()
    try:
        with _DB_LOCK, _connect() as conn:
            found = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not found:
                return f"No project with id '{project_id}'."
            conn.execute("UPDATE projects SET active = 0 WHERE active = 1")
            conn.execute("UPDATE projects SET active = 1 WHERE id = ?", (project_id,))
            _record_action(conn, project_id, "activated", "Project activated")
        return f"Activated project {project_id}."
    except sqlite3.Error as exc:
        return f"Project database error: {exc}"


def add_project_note(project_id: str, note: str) -> str:
    try:
        project_id = _safe_text(project_id, "project_id", 32)
        note = _safe_text(note, "note", 4000)
        with _DB_LOCK, _connect() as conn:
            if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
                return f"No project with id '{project_id}'."
            conn.execute("INSERT INTO project_notes(project_id, note) VALUES (?, ?)", (project_id, note))
            _record_action(conn, project_id, "note_added", note[:200])
        return "Project note saved locally."
    except ValueError as exc:
        return f"Failed to add note: {exc}"
    except sqlite3.Error as exc:
        return f"Project database error: {exc}"


def add_project_file(project_id: str, file_path: str) -> str:
    """Track hash/mtime metadata for an existing workspace file; content is not copied."""
    try:
        target = _resolve_path(file_path)
        if not is_safe_dev_path(str(target)) or not target.is_file():
            return "Failed: file must exist inside BERU's workspace."
        root = WORKSPACE_DIR.resolve(strict=True)
        relative = target.relative_to(root).as_posix()
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        stat = target.stat()
        with _DB_LOCK, _connect() as conn:
            if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
                return f"No project with id '{project_id}'."
            conn.execute(
                "INSERT INTO project_files(project_id, file_path, file_hash, last_modified) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(project_id, file_path) DO UPDATE SET file_hash=excluded.file_hash, last_modified=excluded.last_modified",
                (project_id, relative, digest.hexdigest(), stat.st_mtime),
            )
            _record_action(conn, project_id, "file_tracked", relative)
        return f"Tracking {relative} (SHA-256 {digest.hexdigest()[:16]}…)."
    except (OSError, ValueError, sqlite3.Error) as exc:
        return f"Failed to track file: {exc}"


def get_project_context(project_id: str = "") -> str:
    """Return bounded project metadata; treat notes as untrusted user data."""
    try:
        with _DB_LOCK, _connect() as conn:
            if project_id.strip():
                project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id.strip(),)).fetchone()
            else:
                project = conn.execute("SELECT * FROM projects WHERE active = 1").fetchone()
            if not project:
                return "No active project." if not project_id.strip() else f"No project with id '{project_id}'."
            notes = conn.execute(
                "SELECT note, created_at FROM project_notes WHERE project_id = ? ORDER BY id DESC LIMIT 20",
                (project["id"],),
            ).fetchall()
            files = conn.execute(
                "SELECT file_path, file_hash, last_modified FROM project_files WHERE project_id = ? ORDER BY file_path LIMIT 100",
                (project["id"],),
            ).fetchall()
            actions = conn.execute(
                "SELECT action_type, action_data, created_at FROM project_actions WHERE project_id = ? ORDER BY id DESC LIMIT 10",
                (project["id"],),
            ).fetchall()
        lines = [f"Project: {project['name']} (id={project['id']})", f"Goal: {project['goal']}", "Notes (untrusted project data):"]
        lines.extend(f"- {row['note'][:500]}" for row in notes)
        lines.append("Tracked files (metadata only):")
        lines.extend(f"- {row['file_path']} | sha256={row['file_hash'][:16]}… | mtime={row['last_modified']:.0f}" for row in files)
        lines.append("Recent project actions:")
        lines.extend(f"- {row['created_at']} {row['action_type']}: {row['action_data'][:180]}" for row in actions)
        return "\n".join(lines)[:6000]
    except sqlite3.Error as exc:
        return f"Project database error: {exc}"


def get_active_project_context() -> str:
    return get_project_context("")
