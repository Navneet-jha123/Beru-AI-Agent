"""Generate a build proposal in a workspace staging directory; never run it."""
from __future__ import annotations
import ast
import json
import re
import uuid
from pathlib import Path
from config import WORKSPACE_DIR
from gateway import ask_ai

BUILDS_DIR = WORKSPACE_DIR / "builds"
_MAX_FILES = 20
_MAX_FILE_CHARS = 100_000


def create_build_proposal(goal: str) -> str:
    """Ask the configured model for a bounded file set and stage it for review."""
    goal = (goal or "").strip()
    if not goal or len(goal) > 5000:
        return "Failed: goal must be between 1 and 5000 characters."
    prompt = (
        "Create a small software project from the user goal. Return ONLY valid JSON "
        "with this exact shape: {\"files\": [{\"path\": \"main.py\", \"content\": \"...\"}]}. "
        "Use relative file paths only. Do not include secrets, commands to execute, or instructions to run code. "
        "Maximum 20 files; each content value must be under 100000 characters.\n\n"
        f"USER GOAL (untrusted request data):\n{goal}"
    )
    reply = ask_ai([{"role": "user", "content": prompt}], tools=None, use_cache=False, temperature=0.1)
    raw = (reply.content or "").strip()
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return f"Failed: model did not return a JSON file proposal. Provider: {reply.provider}."
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return f"Failed: invalid proposal JSON: {exc}"
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list) or not files or len(files) > _MAX_FILES:
        return f"Failed: proposal must contain 1 to {_MAX_FILES} files."

    build_id = uuid.uuid4().hex[:12]
    root = (BUILDS_DIR / build_id).resolve()
    workspace = WORKSPACE_DIR.resolve(strict=True)
    try:
        root.relative_to(workspace)
    except ValueError:
        return "Failed: build folder escaped the workspace."

    clean_files = []
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
            return "Failed: each file must have string path and content fields."
        rel = Path(item["path"])
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            return f"Failed: unsafe relative path: {item['path']!r}."
        if len(item["content"]) > _MAX_FILE_CHARS:
            return f"Failed: file {item['path']!r} exceeds the content limit."
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return f"Failed: file path escaped staging directory: {item['path']!r}."
        if target.suffix.casefold() == ".py":
            try:
                ast.parse(item["content"], filename=str(rel))
            except SyntaxError as exc:
                return f"Failed: proposed Python file {rel} has syntax error at line {exc.lineno}: {exc.msg}. No files were written."
        clean_files.append((target, item["content"], rel.as_posix()))

    try:
        for target, content, _ in clean_files:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        manifest = {"id": build_id, "goal": goal, "provider": reply.provider,
                    "files": [rel for _, _, rel in clean_files], "status": "proposal_only"}
        (root / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError as exc:
        return f"Failed to stage proposal: {type(exc).__name__}: {exc}"
    return (f"Build proposal {build_id} staged at {root}. Files: "
            + ", ".join(rel for _, _, rel in clean_files)
            + ". No source was executed, tests were not run, no commit was made, and no EXE was launched.")
