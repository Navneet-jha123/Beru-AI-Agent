"""
cleanup.py — Interactive cleaner for BERU's generated files.

Runs from the project root. Asks before each deletion so nothing is removed
without your explicit confirmation. Never touches source code (.py files
outside workspace/), .env, or anything in workspace/quarantine/ without
explicit confirmation.
"""
from __future__ import annotations

import shutil
from pathlib import Path


BASE = Path(__file__).resolve().parent
WS = BASE / "workspace"


CATEGORIES = [
    {
        "name": "Build proposals",
        "path": WS / "builds",
        "what": "Staged LLM-generated project files. Never executed. Safe to delete.",
        "danger": False,
    },
    {
        "name": "Self-heal proposals",
        "path": WS / "heal_proposals",
        "what": "Staged repair diffs. Original files unchanged. Safe to delete.",
        "danger": False,
    },
    {
        "name": "Session traces",
        "path": WS / "traces",
        "what": "Metadata-only logs (mode, tool names, durations). Safe to delete.",
        "danger": False,
    },
    {
        "name": "Code search index",
        "path": WS / "beru_code_search.db",
        "what": "SQLite FTS5 index. Rebuilds via index_codebase in seconds.",
        "danger": False,
    },
    {
        "name": "Brain database",
        "path": WS / "beru_ai_agent_brain.db",
        "what": "Memory, lessons, episodic history, tool success stats. Resets on next run.",
        "danger": False,
    },
    {
        "name": "Paper trading ledger",
        "path": WS / "paper_trading.db",
        "what": "Simulated trades. Resets to $100,000 starting cash.",
        "danger": False,
    },
    {
        "name": "Project context database",
        "path": WS / "beru_projects.db",
        "what": "Saved projects, notes, tracked files. FORGETS every project.",
        "danger": True,
    },
    {
        "name": "Forged tools",
        "path": WS / "forged_tools",
        "what": "LLM-created tools you approved. DELETES every tool you forged. Cannot undo.",
        "danger": True,
    },
    {
        "name": "Quarantined files",
        "path": WS / "quarantine",
        "what": "Suspicious files you quarantined. PERMANENTLY DELETES them. Review first.",
        "danger": True,
    },
    {
        "name": "Snapshot tests",
        "path": WS / "snapshots",
        "what": "Recorded test baselines. Safe to delete; snapshot tests re-record on next run.",
        "danger": False,
    },
    {
        "name": "Benchmark runs",
        "path": WS / "benchmarks",
        "what": "Historical benchmark results. Safe to delete.",
        "danger": False,
    },
    {
        "name": "Scheduled tasks",
        "path": WS / "schedules.json",
        "what": "Persistent cron schedules. Deleting stops all scheduled tasks.",
        "danger": True,
    },
    {
        "name": "Trigger rules",
        "path": WS / "rules.json",
        "what": "If-X-then-Y automation rules. Deleting removes them.",
        "danger": True,
    },
]


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return 0


def _count_files(path: Path) -> int:
    if path.is_file():
        return 1
    if path.is_dir():
        return sum(1 for p in path.rglob("*") if p.is_file())
    return 0


def _confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def main():
    print("\n=== BERU cleanup ===")
    print(f"Project root: {BASE}")
    print(f"Workspace:    {WS}\n")

    if not WS.exists():
        print("No workspace/ folder. Nothing to clean.")
        return

    total_freed = 0
    total_files = 0

    for cat in CATEGORIES:
        path: Path = cat["path"]
        if not path.exists():
            continue

        size = _size(path)
        files = _count_files(path)
        mb = size / (1024 * 1024)

        prefix = "⚠️ " if cat["danger"] else "  "
        print(f"\n{prefix}[{cat['name']}]")
        print(f"   Path: {path}")
        print(f"   Size: {mb:.2f} MB across {files} file(s)")
        print(f"   Note: {cat['what']}")

        if cat["danger"]:
            if not _confirm(f"   Delete {cat['name']}? This cannot be undone."):
                print("   → Skipped.")
                continue
        else:
            if not _confirm("   Delete?"):
                print("   → Skipped.")
                continue

        try:
            if path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
            total_freed += size
            total_files += files
            print(f"   → Deleted.")
        except Exception as exc:
            print(f"   → FAILED: {type(exc).__name__}: {exc}")

    print(f"\n=== Summary ===")
    print(f"Freed: {total_freed / (1024 * 1024):.2f} MB across {total_files} file(s)")

    if total_freed > 0:
        print("\nRun `python main.py` to restart BERU. It will regenerate any")
        print("deleted databases/indexes fresh on first use.")


if __name__ == "__main__":
    main()