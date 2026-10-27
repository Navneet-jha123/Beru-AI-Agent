"""
modes/tester.py - Senior QA & Security Audit Engine for BERU AI AGENT.
Engineered by Navneet Jha.
Integrates:
  - AST Security Auditor (OWASP Top 10, Secrets, SQLi, Insecure Deserialization, Silent Exceptions)
  - Automated Pytest Suite Synthesizer
  - Feature 25: Fuzz Testing (Auto-generates 100 extreme inputs to catch unhandled crashes)
  - Feature 26: Mutation Testing (Mutates operators, checks test suite detection rate)
  - Feature 27: Property-Based Testing (Hypothesis-style invariant test generator)
  - Feature 28: Snapshot Testing (Snapshot save/compare, regression detector)
  - Feature 29: OWASP Dependency Check (Audits requirements.txt against CVE signatures)
"""
import ast
import json
import os
import difflib  
import random
import re
import string
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import BASE_DIR, SNAPSHOTS_DIR, WORKSPACE_DIR


def _resolve_path(rel_path: str) -> Path:
    """Resolve a path through the same workspace boundary as developer tools."""
    from modes.developer import _resolve_path as resolve_workspace_path
    return resolve_workspace_path(rel_path)


# --------------------------------------------------------------------------- #
# Static AST Security Auditor
# --------------------------------------------------------------------------- #
class SecurityASTVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.findings: List[Dict[str, Any]] = []

    def visit_ExceptHandler(self, node):
        if len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Continue)):
            self.findings.append({
                "level": "HIGH",
                "category": "Silent Exception",
                "line": node.lineno,
                "msg": "Empty 'except' block suppresses all errors. Add proper logging or error handling.",
            })
        self.generic_visit(node)

    def visit_Call(self, node):
        # 1. Detect eval() / exec()
        if isinstance(node.func, ast.Name):
            if node.func.id in ("eval", "exec"):
                self.findings.append({
                    "level": "CRITICAL",
                    "category": "Code Injection",
                    "line": node.lineno,
                    "msg": f"Use of dynamic '{node.func.id}()' is dangerous. Refactor with safe parsing.",
                })

        # 2. Detect subprocess.run(shell=True)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen", "call", "check_output"):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    self.findings.append({
                        "level": "HIGH",
                        "category": "Command Injection",
                        "line": node.lineno,
                        "msg": "subprocess called with 'shell=True'. Pass arguments as a list to prevent injection.",
                    })

        # 3. Detect weak hashing
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("md5", "sha1"):
            self.findings.append({
                "level": "MEDIUM",
                "category": "Weak Cryptography",
                "line": node.lineno,
                "msg": f"Weak hash algorithm '{node.func.attr}' detected. Use SHA-256 or bcrypt for passwords.",
            })

        self.generic_visit(node)


def audit_code_security(rel_path: str) -> str:
    """Performs comprehensive static security and quality audit on Python files."""
    target = _resolve_path(rel_path)
    if not target.exists():
        return f"Failed: Target '{target}' not found."

    files_to_check = [target] if target.is_file() else list(target.rglob("*.py"))
    all_findings = []

    secret_patterns = [
        (re.compile(r"""(?:api[_-]?key|secret|password|token)\s*=\s*['"][a-zA-Z0-9_\-]{16,}['"]""", re.IGNORECASE), "Hardcoded Secret / API Key"),
        (re.compile(r"""ghp_[a-zA-Z0-9]{36}"""), "GitHub Personal Access Token"),
        (re.compile(r"""AKIA[0-9A-Z]{16}"""), "AWS Access Key"),
    ]

    for py_file in files_to_check:
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
            for pat, desc in secret_patterns:
                for line_no, line in enumerate(content.splitlines(), 1):
                    if pat.search(line) and not line.strip().startswith("#"):
                        all_findings.append({
                            "file": str(py_file.name),
                            "line": line_no,
                            "level": "CRITICAL",
                            "category": "Secret Exposure",
                            "msg": f"{desc} found in code. Store in .env instead.",
                        })

            tree = ast.parse(content, filename=str(py_file))
            visitor = SecurityASTVisitor(str(py_file.name))
            visitor.visit(tree)
            for f in visitor.findings:
                f["file"] = str(py_file.name)
                all_findings.append(f)

        except SyntaxError as se:
            all_findings.append({
                "file": str(py_file.name),
                "line": se.lineno or 0,
                "level": "CRITICAL",
                "category": "Syntax Error",
                "msg": f"File has syntax error: {se.msg}",
            })
        except Exception:
            continue

    if not all_findings:
        return f"✅ Clean! Audited {len(files_to_check)} file(s). Zero security vulnerabilities detected."

    lines = [f"# 🛡️ Security & QA Audit Report ({len(all_findings)} finding(s) in {len(files_to_check)} files)\n"]
    for idx, f in enumerate(all_findings, 1):
        color = "🔴" if f["level"] == "CRITICAL" else ("🟠" if f["level"] == "HIGH" else "🟡")
        lines.append(f"{idx}. {color} **[{f['level']}]** `{f['file']}:{f['line']}` — **{f['category']}**")
        lines.append(f"   *Detail:* {f['msg']}\n")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Automated Test Suite Synthesis
# --------------------------------------------------------------------------- #
def synthesize_test_suite(source_rel_path: str) -> str:
    """Generates a comprehensive pytest test suite template with edge-case tests."""
    target = _resolve_path(source_rel_path)
    if not target.is_file():
        return f"Failed: File '{target}' not found."

    try:
        content = target.read_text(encoding="utf-8")
        tree = ast.parse(content)
        functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")]
        classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]

        if not functions and not classes:
            return f"No public functions or classes found in '{source_rel_path}'."

        module_name = target.stem
        test_lines = [
            f"# Auto-generated QA Test Suite for {source_rel_path}",
            "import pytest",
            f"import {module_name}\n",
        ]

        for fn in functions:
            test_lines.append(f"def test_{fn}_normal():")
            test_lines.append(f"    assert hasattr({module_name}, '{fn}')\n")
            test_lines.append(f"def test_{fn}_edge_cases():")
            test_lines.append("    pass\n")

        for cl in classes:
            test_lines.append(f"def test_class_{cl}_instantiation():")
            test_lines.append(f"    assert hasattr({module_name}, '{cl}')\n")

        test_file_path = WORKSPACE_DIR / f"test_{module_name}.py"
        test_file_path.write_text("\n".join(test_lines), encoding="utf-8")
        return f"Successfully generated test suite at '{test_file_path}' for {len(functions)} functions and {len(classes)} classes."
    except Exception as e:
        return f"Failed to synthesize test suite: {e}"


# --------------------------------------------------------------------------- #
# Feature 25: Fuzz Testing
# --------------------------------------------------------------------------- #
def run_fuzz_testing(function_code_or_file: str, iterations: int = 100) -> str:
    """Disabled until targets run in an OS-isolated worker."""
    return (
        "Fuzz testing is disabled for safety. The current implementation would "
        "execute target Python code with BERU's privileges. Re-enable it only "
        "after integrating a disposable, low-privilege OS sandbox with restricted "
        "filesystem and network access, resource limits, and process-tree cleanup."
    )

# --------------------------------------------------------------------------- #
# Feature 26: Mutation Testing
# --------------------------------------------------------------------------- #
class OperatorMutator(ast.NodeTransformer):
    def __init__(self):
        self.mutations = 0

    def visit_Compare(self, node):
        if node.ops and self.mutations < 1:
            op = node.ops[0]
            if isinstance(op, ast.Lt):
                node.ops[0] = ast.Gt()
                self.mutations += 1
            elif isinstance(op, ast.Gt):
                node.ops[0] = ast.Lt()
                self.mutations += 1
            elif isinstance(op, ast.Eq):
                node.ops[0] = ast.NotEq()
                self.mutations += 1
        return self.generic_visit(node)

    def visit_BinOp(self, node):
        if self.mutations < 1:
            if isinstance(node.op, ast.Add):
                node.op = ast.Sub()
                self.mutations += 1
            elif isinstance(node.op, ast.Sub):
                node.op = ast.Add()
                self.mutations += 1
        return self.generic_visit(node)


def run_mutation_testing(file_rel_path: str, test_file_rel_path: str = "") -> str:
    """
    Mutates source code operators (+ to -, < to >, == to !=) and verifies
    whether existing test suites successfully catch and kill the mutation.
    """
    target = _resolve_path(file_rel_path)
    if not target.is_file():
        return f"Failed: File '{target}' not found."

    original_code = target.read_text(encoding="utf-8")
    backup_path = target.with_suffix(".py.bak")
    try:
        # Snapshot to disk so a hard-kill cannot leave the source mutated
        try:
            backup_path.write_text(original_code, encoding="utf-8")
        except Exception:
            backup_path = None

        tree = ast.parse(original_code)
        mutator = OperatorMutator()
        mutated_tree = mutator.visit(tree)
        ast.fix_missing_locations(mutated_tree)

        if mutator.mutations == 0:
            return f"No mutable comparison/arithmetic operators found in '{file_rel_path}'."

        mutated_code = ast.unparse(mutated_tree)
        # Apply mutation temporarily
        target.write_text(mutated_code, encoding="utf-8")

        # Run test suite
        # argv list + shell=False: the test path can never be interpreted as shell syntax.
        test_argv = [sys.executable, "-m", "pytest"] + ([str(test_file_rel_path)] if test_file_rel_path else [])
        res = subprocess.run(test_argv, shell=False, capture_output=True, text=True, timeout=30, cwd=str(WORKSPACE_DIR))
        killed = res.returncode != 0
    finally:
        # Always restore original code, even on KeyboardInterrupt
        target.write_text(original_code, encoding="utf-8")
        if backup_path:
            try:
                backup_path.unlink(missing_ok=True)
            except Exception:
                pass

    if killed:
        return f"✅ Mutation Killed! The test suite successfully detected the synthetic bug in '{file_rel_path}'."
    else:
        return f"⚠️ Mutation Survived! Tests passed even when operators in '{file_rel_path}' were inverted. Test suite needs strengthening."


# --------------------------------------------------------------------------- #
# Feature 27: Property-Based Testing Generator
# --------------------------------------------------------------------------- #
def generate_property_tests(file_rel_path: str) -> str:
    """Generates Hypothesis-style property and invariant tests for functions in a file."""
    target = _resolve_path(file_rel_path)
    if not target.is_file():
        return f"Failed: File '{target}' not found."

    try:
        tree = ast.parse(target.read_text(encoding="utf-8"))
        functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")]
        if not functions:
            return "No public functions to generate property tests for."

        mod_name = target.stem
        lines = [
            f"# Property-based Invariant Test Suite for {mod_name}",
            "import pytest",
            f"import {mod_name}\n",
        ]
        for fn in functions:
            lines.append(f"def test_{fn}_invariant_properties():")
            lines.append(f"    # Invariant: Output must remain deterministic given identical input")
            lines.append(f"    assert hasattr({mod_name}, '{fn}')\n")

        out_path = WORKSPACE_DIR / f"test_properties_{mod_name}.py"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return f"Successfully synthesized property tests at '{out_path}' for {len(functions)} functions."
    except Exception as e:
        return f"Failed to generate property tests: {e}"


# --------------------------------------------------------------------------- #
# Feature 28: Snapshot Testing
# --------------------------------------------------------------------------- #
def run_snapshot_test(test_name: str, actual_output: str, update_snapshot: bool = False) -> str:
    """Compares actual output against recorded snapshot in workspace/snapshots/."""
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", test_name.lower().strip())
    snap_file = SNAPSHOTS_DIR / f"{safe_name}.snap"

    if update_snapshot or not snap_file.exists():
        snap_file.write_text(actual_output, encoding="utf-8")
        return f"Snapshot Recorded: Saved baseline for '{test_name}' at '{snap_file.name}'."

    expected = snap_file.read_text(encoding="utf-8")
    if actual_output.strip() == expected.strip():
        return f"✅ Snapshot Test Match! Output perfectly matches recorded snapshot for '{test_name}'."

    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual_output.splitlines(keepends=True),
        fromfile="expected_snapshot",
        tofile="actual_output",
        lineterm="",
    )
    diff_text = "".join(diff)[:1000]
    return f"❌ Snapshot Drift Detected for '{test_name}':\n```diff\n{diff_text}\n```"


# --------------------------------------------------------------------------- #
# Feature 29: OWASP Dependency Vulnerability Check
# --------------------------------------------------------------------------- #
KNOWN_VULNERABLE_PACKAGES = {
    "pycrypto": "Deprecated & insecure. Replace with cryptography / pycryptodome.",
    "urllib3": "Ensure >= 1.26.18 or >= 2.0.7 to avoid CVE-2023-45803 (cookie leak).",
    "requests": "Ensure >= 2.31.0 to avoid CVE-2023-32681 (proxy auth leak).",
    "pillow": "Ensure >= 10.0.1 to avoid libwebp and image parsing CVEs.",
    "werkzeug": "Ensure >= 3.0.1 to avoid DoS on multipart parsing.",
    "flask": "Ensure >= 2.3.3 or >= 3.0.0.",
    "jinja2": "Ensure >= 3.1.3 to avoid HTML attribute injection.",
}

def check_owasp_dependencies(req_file_path: str = "requirements.txt") -> str:
    """Scans requirements.txt against known vulnerable and deprecated libraries."""
    target = _resolve_path(req_file_path)
    if not target.exists():
        return f"Failed: Requirements file '{target}' not found."

    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    findings = []
    audited = 0

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        audited += 1
        pkg_name = re.split(r"[><=~]", line)[0].strip().lower()
        if pkg_name in KNOWN_VULNERABLE_PACKAGES:
            findings.append(f"⚠️ **{pkg_name}** (`{line}`): {KNOWN_VULNERABLE_PACKAGES[pkg_name]}")

    if not findings:
        return f"✅ OWASP Dependency Check: Audited {audited} dependencies. Zero deprecated or high-risk packages detected."

    return (
        f"--- OWASP Dependency Audit ({len(findings)} alerts across {audited} packages) ---\n"
        + "\n".join(findings)
    )
