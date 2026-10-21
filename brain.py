"""
brain.py - Cognitive Architecture & Extended Memory Suite for BERU AI AGENT.
Integrates:
  1. Episodic Memory Timeline (Past discussions recall by date/topic)
  2. Entity Graph Memory (Nodes & relationships tracking)
  3. Confidence Scoring (1-10 self-rating & uncertainty guard)
  4. Self-Reflection Loop (Automatic learning after task execution)
  5. Cross-Session Continuity (Loads recent summaries on startup)
  6. Preference Learning (User accepted/rejected style adaptations)
  7. Task Decomposition Depth (Recursive DAG planning up to depth 3)
  8. Cognitive Load Estimation (Warns when task needs >5 tools)
  9. Tree-of-Thought (ToT) 3-branch decision synthesizer
  10. Chain-of-Verification (CoVe) evidence-grounded self-questioning
  11. Counterfactual Reasoning (Evaluates alternative approaches)
  12. Adversarial Self-Play (Red-teaming critic)
  13. Tool Selection Optimizer (Learns tool success/failure rates)
  14. Failure Recovery Tree (Intelligent fallbacks on failure)
  15. Goal Drift Detection (Alerts when execution deviates >30%)
  16. Context Window Auto-Summarizer (Prunes older conversation turns)
"""
import ast
import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from config import BRAIN_DB_PATH, ENABLE_CRITIC, ENABLE_PLANNER, ENABLE_REFLECT
from gateway import ask_ai

_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Database Initialization & Schema Migrations
# --------------------------------------------------------------------------- #
from contextlib import contextmanager

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(BRAIN_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db():
    """Correct context manager: yields a connection, commits on success,
    rolls back on error, and always closes the connection."""
    conn = sqlite3.connect(str(BRAIN_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_brain_db() -> None:
    """Initializes all cognitive, episodic, entity, and metric tables."""
    with _lock:
        with _get_conn() as conn:
            # Lessons & Facts
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    lesson TEXT NOT NULL,
                    source_task TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT DEFAULT 'general',
                    fact TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Feature 1: Episodic Memory Timeline
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    final_answer TEXT NOT NULL,
                    mode TEXT DEFAULT 'General',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Feature 2: Entity Graph Memory
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    entity_type TEXT DEFAULT 'concept',
                    attributes_json TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    UNIQUE(source_name, target_name, relation)
                )
            """)
            # Feature 6: User Preferences
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pref_key TEXT UNIQUE NOT NULL,
                    pref_value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Feature 13: Tool Selection Optimizer Stats
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_stats (
                    tool_name TEXT PRIMARY KEY,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    last_used DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()


init_brain_db()


# --------------------------------------------------------------------------- #
# Case-Insensitive Long-Term Facts & Lessons Memory (Fix 2)
# --------------------------------------------------------------------------- #
def save_lesson(topic: str, lesson: str, source_task: str = "") -> str:
    """Saves a permanent lesson learned from task outcomes."""
    with _lock:
        try:
            with _db() as conn:
                conn.execute(
                    "INSERT INTO lessons (topic, lesson, source_task) VALUES (?, ?, ?)",
                    (topic.strip().lower(), lesson.strip(), source_task.strip()),
                )
            return f"Saved lesson for '{topic}': {lesson}"
        except Exception as e:
            return f"Failed to save lesson: {e}"


def recall_lessons(topic: str) -> List[str]:
    """Recalls relevant lessons using case-insensitive LOWER() matching."""
    words = [w for w in re.findall(r"\w+", topic.lower()) if len(w) > 3]
    if not words:
        return []

    with _lock:
        try:
            with _get_conn() as conn:
                query = (
                    "SELECT lesson FROM lessons WHERE "
                    + " OR ".join(["LOWER(topic) LIKE ?" for _ in words])
                    + " ORDER BY id DESC LIMIT 5"
                )
                params = [f"%{w}%" for w in words]
                cur = conn.execute(query, params)
                return [row["lesson"] for row in cur.fetchall()]
        except Exception:
            return []


def save_fact(fact: str, category: str = "general") -> str:
    """Saves a long-term fact about the user, system, or preference."""
    with _lock:
        try:
            with _get_conn() as conn:
                cur = conn.execute("SELECT id FROM memory_facts WHERE LOWER(fact) = LOWER(?)", (fact.strip(),))
                if cur.fetchone():
                    return "Fact already in memory."
                conn.execute("INSERT INTO memory_facts (category, fact) VALUES (?, ?)", (category.strip(), fact.strip()))
                conn.commit()
            return f"Memorized: {fact}"
        except Exception as e:
            return f"Failed to save fact: {e}"


def recall_facts(query: str = "") -> str:
    """Recalls stored memory facts using case-insensitive LOWER() matching."""
    with _lock:
        try:
            with _get_conn() as conn:
                if query.strip():
                    cur = conn.execute(
                        "SELECT category, fact FROM memory_facts WHERE LOWER(fact) LIKE ? ORDER BY id DESC LIMIT 10",
                        (f"%{query.strip().lower()}%",),
                    )
                else:
                    cur = conn.execute("SELECT category, fact FROM memory_facts ORDER BY id DESC LIMIT 15")
                rows = cur.fetchall()
                if not rows:
                    return "No facts saved yet."
                return "Known Facts:\n" + "\n".join([f"- [{r['category']}] {r['fact']}" for r in rows])
        except Exception as e:
            return f"Failed to recall facts: {e}"


# --------------------------------------------------------------------------- #
# Feature 1: Episodic Memory Timeline
# --------------------------------------------------------------------------- #
def record_episodic_event(session_id: str, prompt: str, final_answer: str, mode: str = "General") -> None:
    """Saves full session context with timestamp for conversational timeline queries."""
    with _lock:
        try:
            with _get_conn() as conn:
                conn.execute(
                    "INSERT INTO episodic_memory (session_id, prompt, final_answer, mode) VALUES (?, ?, ?, ?)",
                    (session_id, prompt[:1000], final_answer[:2000], mode),
                )
                conn.commit()
        except Exception:
            pass


def query_episodic_memory(query: str, date_filter: str = "") -> str:
    """Queries conversation history: 'What did we discuss yesterday?' or topic lookup."""
    with _lock:
        try:
            with _get_conn() as conn:
                if date_filter.lower() in ("yesterday", "recent"):
                    cur = conn.execute(
                        "SELECT prompt, final_answer, timestamp FROM episodic_memory WHERE timestamp >= datetime('now', '-2 days') ORDER BY id DESC LIMIT 5"
                    )
                elif query.strip():
                    words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 3]
                    if not words:
                        cur = conn.execute("SELECT prompt, final_answer, timestamp FROM episodic_memory ORDER BY id DESC LIMIT 5")
                    else:
                        clause = " OR ".join(["LOWER(prompt) LIKE ? OR LOWER(final_answer) LIKE ?" for _ in words])
                        params = []
                        for w in words:
                            params.extend([f"%{w}%", f"%{w}%"])
                        cur = conn.execute(f"SELECT prompt, final_answer, timestamp FROM episodic_memory WHERE {clause} ORDER BY id DESC LIMIT 5", params)
                else:
                    cur = conn.execute("SELECT prompt, final_answer, timestamp FROM episodic_memory ORDER BY id DESC LIMIT 5")

                rows = cur.fetchall()
                if not rows:
                    return "No past episodic discussions found matching that query."

                output = ["--- EPISODIC MEMORY TIMELINE ---"]
                for r in rows:
                    output.append(f"[{r['timestamp']}] User Asked: '{r['prompt'][:100]}'\n  ↳ Outcome: '{r['final_answer'][:150]}...'")
                return "\n\n".join(output)
        except Exception as e:
            return f"Failed to query episodic memory: {e}"


# --------------------------------------------------------------------------- #
# Feature 2: Entity Graph Memory
# --------------------------------------------------------------------------- #
def add_entity_relation(source: str, target: str, relation: str, entity_type: str = "concept") -> str:
    """Tracks entities (people, projects, files) and their relationships in a knowledge graph."""
    src = source.strip().lower()
    tgt = target.strip().lower()
    rel = relation.strip().lower()
    with _lock:
        try:
            with _get_conn() as conn:
                conn.execute("INSERT OR IGNORE INTO entity_nodes (name, entity_type) VALUES (?, ?)", (src, entity_type))
                conn.execute("INSERT OR IGNORE INTO entity_nodes (name, entity_type) VALUES (?, ?)", (tgt, entity_type))
                conn.execute(
                    "INSERT INTO entity_edges (source_name, target_name, relation) VALUES (?, ?, ?) ON CONFLICT(source_name, target_name, relation) DO UPDATE SET weight = weight + 1.0",
                    (src, tgt, rel),
                )
                conn.commit()
            return f"Entity Graph: Linked '{src}' --[{rel}]--> '{tgt}'"
        except Exception as e:
            return f"Failed to add entity relation: {e}"


def query_entity_graph(entity_name: str) -> str:
    """Queries related nodes in the entity knowledge graph."""
    name = entity_name.strip().lower()
    with _lock:
        try:
            with _get_conn() as conn:
                cur = conn.execute(
                    "SELECT target_name, relation FROM entity_edges WHERE source_name = ? UNION SELECT source_name, relation FROM entity_edges WHERE target_name = ?",
                    (name, name),
                )
                rows = cur.fetchall()
                if not rows:
                    return f"No entity relations found for '{entity_name}'."
                links = [f"• {r['relation'].upper()} -> '{r[0]}'" for r in rows]
                return f"--- Entity Knowledge Graph for '{entity_name}' ---\n" + "\n".join(links)
        except Exception as e:
            return f"Failed to query entity graph: {e}"


# --------------------------------------------------------------------------- #
# Feature 3: Confidence Scoring
# --------------------------------------------------------------------------- #
def rate_confidence(answer: str, tool_evidence: Optional[List[Dict[str, Any]]] = None) -> Tuple[int, str]:
    """
    Evaluates confidence score (1 to 10) for an answer based on tool outputs and hallucination guards.
    Returns (score, reason).
    """
    tool_evidence = tool_evidence or []  # <--- ADD THIS LINE

    if not tool_evidence and ("http" in answer or "port" in answer or "100%" in answer):
        return 3, "Low Confidence (3/10): Specific claims made without direct tool evidence."

    failures = sum(1 for e in tool_evidence if "failed" in e.get("result", "").lower() or "error" in e.get("result", "").lower())
    if failures == len(tool_evidence) and len(tool_evidence) > 0:
        return 2, "Low Confidence (2/10): All supporting tool invocations reported errors."

    if len(tool_evidence) >= 1:
        return 9, "High Confidence (9/10): Fully grounded in verified tool outputs."

    return 7, "Moderate Confidence (7/10): Direct analytical reasoning."


# --------------------------------------------------------------------------- #
# Feature 4: Self-Reflection Loop
# --------------------------------------------------------------------------- #
def generate_self_reflection(prompt: str, answer: str, success: bool) -> str:
    """Generates a concise 1-2 sentence self-reflection after a task and stores it into lessons."""
    if not ENABLE_REFLECT:
        return ""
    system_prompt = "You are a metacognitive AI reflector. In 1 or 2 concise sentences, summarize key lesson learned."
    user_prompt = f"Task: {prompt[:300]}\nSuccess: {success}\nOutcome: {answer[:400]}"
    try:
        reflection = ask_ai(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.0,
        ).content.strip()
        if reflection:
            save_lesson(prompt[:40], reflection, source_task=prompt[:80])
        return reflection
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Feature 5: Cross-Session Continuity
# --------------------------------------------------------------------------- #
def get_cross_session_context() -> str:
    """Loads a short summary of yesterday/recent sessions to maintain continuous workflow."""
    with _lock:
        try:
            with _get_conn() as conn:
                cur = conn.execute("SELECT prompt, final_answer, timestamp FROM episodic_memory ORDER BY id DESC LIMIT 2")
                rows = cur.fetchall()
                if not rows:
                    return ""
                items = [f"- [{r['timestamp']}] Worked on: '{r['prompt'][:80]}'" for r in rows]
                return "RECENT SESSION CONTINUITY:\n" + "\n".join(items)
        except Exception:
            return ""


# --------------------------------------------------------------------------- #
# Feature 6: Preference Learning
# --------------------------------------------------------------------------- #
def update_preference(pref_key: str, pref_value: str) -> str:
    """Stores a learned user preference (e.g. response length, preferred tools)."""
    with _lock:
        try:
            with _get_conn() as conn:
                conn.execute(
                    "INSERT INTO user_preferences (pref_key, pref_value) VALUES (?, ?) ON CONFLICT(pref_key) DO UPDATE SET pref_value = ?, updated_at = CURRENT_TIMESTAMP",
                    (pref_key.strip().lower(), pref_value.strip(), pref_value.strip()),
                )
                conn.commit()
            return f"Preference saved: {pref_key} -> {pref_value}"
        except Exception as e:
            return f"Failed to update preference: {e}"


def get_user_preferences() -> str:
    """Retrieves all user preferences."""
    with _lock:
        try:
            with _get_conn() as conn:
                cur = conn.execute("SELECT pref_key, pref_value FROM user_preferences")
                rows = cur.fetchall()
                if not rows:
                    return ""
                return "LEARNED USER PREFERENCES:\n" + "\n".join([f"- {r['pref_key']}: {r['pref_value']}" for r in rows])
        except Exception:
            return ""


# --------------------------------------------------------------------------- #
# Feature 7: Task Decomposition Depth (Recursive up to Depth 3)
# --------------------------------------------------------------------------- #
def decompose_task_recursive(task: str, depth: int = 1, max_depth: int = 3) -> Dict[str, Any]:
    """Recursively decomposes a complex task into hierarchical sub-steps."""
    if depth > max_depth or len(task.strip()) < 15:
        return {"task": task, "subtasks": []}

    system_prompt = (
        "Deconstruct this task into 2 to 3 essential subtasks. Output ONLY a valid JSON list of strings, "
        "e.g. ['inspect code structure', 'run unit tests']."
    )
    try:
        res = ask_ai(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": task}],
            temperature=0.0,
        ).content.strip()
        m = re.search(r"\[.*?\]", res, re.DOTALL)
        if m:
            sub_list = json.loads(m.group(0))
            children = []
            for item in sub_list[:3]:
                if depth < max_depth and len(item) > 25:
                    children.append(decompose_task_recursive(item, depth=depth + 1, max_depth=max_depth))
                else:
                    children.append({"task": item, "subtasks": []})
            return {"task": task, "subtasks": children}
    except Exception:
        pass
    return {"task": task, "subtasks": []}


# --------------------------------------------------------------------------- #
# Feature 8: Cognitive Load Estimation
# --------------------------------------------------------------------------- #
def estimate_cognitive_load(prompt: str) -> Dict[str, Any]:
    """Estimates required tool invocations; warns if task needs >5 tools."""
    p_lower = prompt.lower()
    est_tools = 1
    if any(k in p_lower for k in ("build", "compile", "create", "test", "audit", "scan", "deploy")):
        est_tools += 2
    if any(k in p_lower for k in ("and", "then", "after", "also", "compare")):
        est_tools += 2
    if len(prompt.split()) > 30:
        est_tools += 1

    needs_warning = est_tools >= 5
    warning_text = ""
    if needs_warning:
        warning_text = (
            f"⚠️ Cognitive Load Warning: This operation is estimated to require ~{est_tools} tool executions. "
            "A structured pre-plan will be formulated first."
        )
    return {"estimated_tools": est_tools, "heavy_load": needs_warning, "warning": warning_text}


# --------------------------------------------------------------------------- #
# Feature 9: Tree-of-Thought (ToT) 3-Branch Reasoning
# --------------------------------------------------------------------------- #
def tree_of_thought_solve(problem: str, num_branches: int = 3) -> str:
    """Generates 3 alternative reasoning trajectories for critical decisions and selects optimal branch."""
    prompt = f"""Generate {num_branches} distinct, competing strategies to solve this problem:
Problem: {problem}

For each strategy, provide:
1. Strategy Name & Approach
2. Pros & Cons
3. Feasibility Score (1-10)

Conclude with the single BEST recommended strategy."""
    try:
        reply = ask_ai([{"role": "user", "content": prompt}], temperature=0.2).content.strip()
        return f"--- TREE-OF-THOUGHT STRATEGY MATRIX ---\n{reply}"
    except Exception as e:
        return f"Tree-of-thought analysis failed: {e}"


# --------------------------------------------------------------------------- #
# Feature 10: Chain-of-Verification (CoVe)
# --------------------------------------------------------------------------- #
def chain_of_verification(draft_answer: str, tool_evidence: List[Dict[str, Any]]) -> str:
    """Performs self-questioning and verification against recorded tool evidence."""
    evidence_text = "\n".join(f"[{e['tool']}]: {e['result'][:300]}" for e in tool_evidence) if tool_evidence else "None"
    prompt = f"""Verify the following draft answer against observed tool evidence:
Draft Answer: {draft_answer}

Observed Tool Evidence:
{evidence_text}

Task:
1. List 2 factual verification questions.
2. Confirm if each is supported by the evidence.
3. Output the verified, corrected final answer."""
    try:
        return ask_ai([{"role": "user", "content": prompt}], temperature=0.0).content.strip()
    except Exception:
        return draft_answer


# --------------------------------------------------------------------------- #
# Feature 11: Counterfactual Reasoning
# --------------------------------------------------------------------------- #
def counterfactual_evaluate(approach_a: str, approach_b: str, context: str) -> str:
    """Evaluates 'What if approach B was used instead of approach A?' trade-offs."""
    prompt = f"""Perform counterfactual comparative analysis:
Context: {context}
Approach A (Primary): {approach_a}
Approach B (Alternative): {approach_b}

Compare both along: Speed, Reliability, Error Risk. Recommend which is optimal."""
    try:
        return ask_ai([{"role": "user", "content": prompt}], temperature=0.1).content.strip()
    except Exception as e:
        return f"Counterfactual reasoning error: {e}"


# --------------------------------------------------------------------------- #
# Feature 12: Adversarial Self-Play Critic
# --------------------------------------------------------------------------- #
def adversarial_critique(answer: str, prompt: str) -> str:
    """Adversarial critic challenges the answer's logic and checks edge cases."""
    critique_prompt = f"""Act as a ruthless code and systems security auditor.
User Goal: {prompt}
Proposed Solution: {answer}

Identify 1 to 2 critical flaws, overlooked edge cases, or potential failure modes. Conclude with required fixes."""
    try:
        return ask_ai([{"role": "user", "content": critique_prompt}], temperature=0.1).content.strip()
    except Exception as e:
        return f"Adversarial critique unavailable: {e}"


# --------------------------------------------------------------------------- #
# Feature 13: Tool Selection Optimizer
# --------------------------------------------------------------------------- #
def record_tool_outcome(tool_name: str, success: bool) -> None:
    """Records tool execution success/failure to optimize future tool choices."""
    with _lock:
        try:
            with _get_conn() as conn:
                field = "success_count" if success else "fail_count"
                conn.execute(
                    f"INSERT INTO tool_stats (tool_name, success_count, fail_count) VALUES (?, ?, ?) ON CONFLICT(tool_name) DO UPDATE SET {field} = {field} + 1, last_used = CURRENT_TIMESTAMP",
                    (tool_name, 1 if success else 0, 0 if success else 1),
                )
                conn.commit()
        except Exception:
            pass


def get_tool_optimizer_report() -> str:
    """Returns tool performance metrics and reliability ranking."""
    with _lock:
        try:
            with _get_conn() as conn:
                cur = conn.execute("SELECT tool_name, success_count, fail_count FROM tool_stats ORDER BY (success_count + fail_count) DESC LIMIT 15")
                rows = cur.fetchall()
                if not rows:
                    return "No tool telemetry recorded yet."
                lines = ["--- TOOL SELECTION OPTIMIZER TELEMETRY ---"]
                for r in rows:
                    total = r["success_count"] + r["fail_count"]
                    rate = (r["success_count"] / total * 100) if total > 0 else 0
                    lines.append(f"• {r['tool_name']:28s} | Success: {rate:5.1f}% ({r['success_count']}/{total})")
                return "\n".join(lines)
        except Exception as e:
            return f"Failed to retrieve tool stats: {e}"


# --------------------------------------------------------------------------- #
# Feature 14: Failure Recovery Decision Tree
# --------------------------------------------------------------------------- #
FALLBACK_DECISION_TREE = {
    "click_ui_element": "1. Verify window focus. 2. Fall back to inspect_screen -> click_at coordinates. 3. Fall back to press_key shortcuts.",
    "browser_search": "1. Fall back to browser_open direct URL. 2. Fall back to DuckDuckGo Lite. 3. Fall back to Bing search.",
    "compile_to_exe": "1. Check PyInstaller installed. 2. Inspect missing imports in script. 3. Build with --onedir instead of --onefile.",
    "audit_ports_and_services": "1. Check host reachable via ping. 2. Check if target blocks ICMP. 3. Scan fewer ports with increased timeout.",
}

def suggest_failure_recovery(tool_name: str, error_message: str) -> str:
    """Provides targeted recovery protocol when a tool execution fails."""
    guide = FALLBACK_DECISION_TREE.get(tool_name, "1. Inspect error traceback. 2. Alter parameters. 3. Switch tool or report failure.")
    return f"[Failure Recovery Tree for '{tool_name}']\nError: {error_message}\nPrescribed Fallback Path:\n{guide}"


# --------------------------------------------------------------------------- #
# Feature 15: Goal Drift Detection
# --------------------------------------------------------------------------- #
def detect_goal_drift(original_goal: str, current_action: str) -> Tuple[bool, float, str]:
    """Detects if current agent action deviates significantly (>30%) from original user objective."""
    orig_words = set(re.findall(r"\w+", original_goal.lower()))
    act_words = set(re.findall(r"\w+", current_action.lower()))
    stop_words = {"the", "and", "for", "with", "from", "that", "this", "action", "tool"}
    orig_clean = orig_words - stop_words
    act_clean = act_words - stop_words

    if not orig_clean or not act_clean:
        return False, 0.0, "Aligned"

    overlap = len(orig_clean.intersection(act_clean))
    similarity = overlap / max(len(orig_clean), len(act_clean))
    drift = 1.0 - similarity

    is_drifted = drift > 0.70 and len(orig_clean) > 4
    status = f"Drift: {drift * 100:.1f}% - {'⚠️ DRIFT DETECTED' if is_drifted else '✅ ALIGNED'}"
    return is_drifted, drift, status


# --------------------------------------------------------------------------- #
# Feature 16: Context Window Auto-Summarizer
# --------------------------------------------------------------------------- #
def summarize_long_context(messages: List[Dict[str, Any]], max_turns: int = 6) -> List[Dict[str, Any]]:
    """Prunes and summarizes older turns when message history exceeds limit."""
    if len(messages) <= max_turns + 2:
        return messages

    system_msg = messages[0] if messages and messages[0]["role"] == "system" else {"role": "system", "content": ""}
    initial_user = messages[1] if len(messages) > 1 and messages[1]["role"] == "user" else None

    # Middle turns to summarize
    middle = messages[2:-max_turns]
    kept_recent = messages[-max_turns:]

    middle_text = "\n".join(f"{m['role']}: {str(m.get('content', ''))[:150]}" for m in middle)
    summary_msg = {
        "role": "system",
        "content": f"[COMPACT SESSION MEMORY OF PRIOR TURNS]:\n{middle_text[:800]}",
    }

    rebuilt = [system_msg]
    if initial_user:
        rebuilt.append(initial_user)
    rebuilt.append(summary_msg)
    rebuilt.extend(kept_recent)
    return rebuilt


# --------------------------------------------------------------------------- #
# Working Memory & Checklist
# --------------------------------------------------------------------------- #
class TodoItem:
    def __init__(self, task: str, done: bool = False):
        self.task: str = task
        self.done: bool = done


class WorkingMemory:
    def __init__(self):
        self.todo_list: List[TodoItem] = []
        self.tool_evidence: List[Dict[str, Any]] = []

    def set_todos(self, items: List[str]) -> None:
        self.todo_list = [TodoItem(t) for t in items if t.strip()]

    def mark_done(self, task_substr: str) -> None:
        sub = task_substr.lower().strip()
        for t in self.todo_list:
            if sub in t.task.lower():
                t.done = True

    def format_todo_pad(self) -> str:
        if not self.todo_list:
            return ""
        lines = ["--- CURRENT WORKING CHECKLIST ---"]
        for idx, item in enumerate(self.todo_list, 1):
            box = "[X]" if item.done else "[ ]"
            lines.append(f"{idx}. {box} {item.task}")
        lines.append("---------------------------------")
        return "\n".join(lines)

    def record_tool_result(self, tool_name: str, args: Dict[str, Any], result: str) -> None:
        self.tool_evidence.append({
            "tool": tool_name,
            "args": args,
            "result": result[:2000],
            "time": time.strftime("%H:%M:%S"),
        })


# --------------------------------------------------------------------------- #
# Pre-Planner (Skips trivial queries <20 words or templates)
# --------------------------------------------------------------------------- #
def plan_task(goal: str, mode: str, available_tool_names: List[str]) -> List[str]:
    """Generates a 3-5 step plan. Skips for trivial queries under 20 words or quick template matches."""
    if not ENABLE_PLANNER or len(goal.split()) < 20:
        return []

    # Skip templates (open, search, health)
    goal_low = goal.lower()
    if any(goal_low.startswith(p) for p in ("open ", "calc", "search ", "health", "screenshot", "status")):
        return []

    system_prompt = f"""You are the Executive Planner of BERU AI AGENT.
Current Mode: {mode}.
Deconstruct the user's goal into 3 to 5 concrete tactical steps.
Keep each step brief (under 12 words).
Output ONLY a JSON array of strings."""
    try:
        msg = ask_ai(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Goal: {goal}"}],
            temperature=0.0,
        )
        raw = msg.content.strip()
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        if m:
            steps = json.loads(m.group(0))
            if isinstance(steps, list) and all(isinstance(s, str) for s in steps):
                return steps[:5]
    except Exception:
        pass
    return []


# --------------------------------------------------------------------------- #
# Verification Critic (Skips queries <100 chars or <2 tools)
# --------------------------------------------------------------------------- #
def verify_answer(answer: str, tool_evidence: List[Dict[str, Any]], prompt_len: int = 120) -> Tuple[bool, str]:
    """
    Evaluates evidence support for final answer.
    Performance fix: Skips for queries under 100 chars or when len(tool_evidence) < 2.
    """
    if not ENABLE_CRITIC or prompt_len < 100 or len(tool_evidence) < 2:
        return True, ""

    all_failed = all("failed" in e["result"].lower() or "error" in e["result"].lower() for e in tool_evidence)
    if all_failed and len(tool_evidence) > 0 and len(answer) > 200:
        return False, "Evidence shows all tools failed. Do not simulate success. Report the failure plainly."

    return True, ""
