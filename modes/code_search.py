"""Local SQLite FTS5 search for source files inside BERU's workspace."""
from __future__ import annotations

import ast
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from config import WORKSPACE_DIR
from modes.developer import _resolve_path, is_safe_dev_path

DB_PATH = WORKSPACE_DIR / "beru_code_search.db"
_ALLOWED_SUFFIXES = {".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".sql", ".sh", ".ps1"}
_EXCLUDED_PARTS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build", "secrets", "credentials"}
_MAX_FILE_BYTES = 1_000_000
_MAX_INDEX_FILES = 5000


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH), timeout=15)


@contextmanager
def _db():
    """Commit/rollback and close a SQLite connection for every operation."""
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _init_db() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(path UNINDEXED, content, tokenize='unicode61')")


_init_db()


def _iter_files(root: Path) -> Iterable[Path]:
    count = 0
    for path in root.rglob("*"):
        if count >= _MAX_INDEX_FILES:
            break
        if not path.is_file() or path.suffix.casefold() not in _ALLOWED_SUFFIXES:
            continue
        try:
            relative = path.relative_to(root)
            if any(part.casefold() in _EXCLUDED_PARTS or part.casefold().startswith(".env") for part in relative.parts):
                continue
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            if not is_safe_dev_path(str(path)):
                continue
        except (OSError, ValueError):
            continue
        count += 1
        yield path


def index_codebase(path: str = ".") -> str:
    """Rebuild the local search index for a workspace folder; skips secret-like paths."""
    try:
        root = _resolve_path(path)
        if not root.is_dir() or not is_safe_dev_path(str(root)):
            return "Failed: index root must be a directory inside BERU's workspace."
        root_anchor = WORKSPACE_DIR.resolve(strict=True)
        rows = []
        for file in _iter_files(root):
            try:
                content = file.read_text(encoding="utf-8", errors="replace")
                rel = file.relative_to(root_anchor).as_posix()
                rows.append((rel, content))
            except (OSError, ValueError):
                continue
        with _db() as conn:
            conn.execute("DELETE FROM code_fts")
            conn.executemany("INSERT INTO code_fts(path, content) VALUES (?, ?)", rows)
        return f"Indexed {len(rows)} files locally. Content is stored in workspace/beru_code_search.db."
    except (OSError, ValueError, sqlite3.Error) as exc:
        return f"Code index failed: {type(exc).__name__}: {exc}"


def search_code(query: str, limit: int = 10) -> str:
    """Search indexed code with AND semantics; query is tokenized before FTS5."""
    import re
    terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,80}", query or "")[:12]
    if not terms:
        return "Enter at least one search term (two or more characters)."
    limit = max(1, min(int(limit), 20))
    expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT path, snippet(code_fts, 1, '[', ']', ' … ', 12), bm25(code_fts) "
                "FROM code_fts WHERE code_fts MATCH ? ORDER BY bm25(code_fts) LIMIT ?",
                (expression, limit),
            ).fetchall()
        if not rows:
            return "No matches. Run index_codebase first or use different terms."
        return "\n".join(f"{row[0]}\n  {row[1]}" for row in rows)
    except sqlite3.OperationalError as exc:
        return f"Search failed. Run index_codebase first. ({exc})"
    except sqlite3.Error as exc:
        return f"Search database error: {exc}"


def find_symbol(name: str, path: str = ".") -> str:
    """Find Python classes/functions and assignments by exact symbol name."""
    name = (name or "").strip()
    if not name or len(name) > 120:
        return "Provide a symbol name up to 120 characters."
    try:
        root = _resolve_path(path)
        if not root.is_dir() or not is_safe_dev_path(str(root)):
            return "Failed: search root must be inside BERU's workspace."
        root_anchor = WORKSPACE_DIR.resolve(strict=True)
        results = []
        for file in _iter_files(root):
            if file.suffix.casefold() != ".py":
                continue
            try:
                source = file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=str(file))
            except (OSError, SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                found = None
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                    found = node.name
                elif isinstance(node, (ast.Name, ast.arg)) and node.id == name:
                    found = node.id
                if found:
                    try:
                        rel = file.relative_to(root_anchor).as_posix()
                    except ValueError:
                        continue
                    results.append(f"{rel}:{getattr(node, 'lineno', 1)} — {found}")
                    if len(results) >= 50:
                        break
            if len(results) >= 50:
                break
        return "\n".join(results) if results else f"No Python symbol named '{name}' found."
    except (OSError, ValueError) as exc:
        return f"Symbol search failed: {exc}"
