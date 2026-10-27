"""
browser_agent.py - Autonomous Playwright Web Agent for BERU AI AGENT.
Runs on a dedicated worker thread to prevent thread-affine event loop collisions.

Features:
  - Stealth Mode (Bypasses bot detection, navigator.webdriver cloaking) [Feature 41]
  - Session Persistence (Save/restore cookies & storage across sessions) [Feature 42]
  - Multi-Tab Orchestrator (Concurrent parallel browsing & comparison) [Feature 43]
  - Structured Data Extraction (JSON-LD, OpenGraph, Microdata) [Feature 44]
  - Screenshot Diff for Page Changes (Visual change detection) [Feature 45]
  - Fast instant search via DDG Lite + Bing fallback
  - DOM content extraction & interactive controls
"""
import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

from config import SNAPSHOTS_DIR, WORKSPACE_DIR


# JavaScript stealth script injected before any webpage loads
STEALTH_INIT_SCRIPT = """
(() => {
    // 1. Cloak navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. Mock chrome runtime
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };

    // 3. Mock plugins array
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
        ]
    });

    // 4. Mock navigator languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en']
    });

    // 5. Mock permissions query
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
})();
"""


class BrowserWorker:
    def __init__(self):
        self._jobs = queue.Queue()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def _worker_loop(self):
        playwright = None
        browser = None
        context = None
        page = None
        session_file = WORKSPACE_DIR / "browser_session.json"

        def _init_browser():
            nonlocal playwright, browser, context, page
            if playwright is None:
                from playwright.sync_api import sync_playwright
                playwright = sync_playwright().start()
                browser = playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars",
                    ],
                )
                
                # Check for existing session storage state
                storage_kwargs = {}
                if session_file.exists():
                    try:
                        storage_kwargs["storage_state"] = str(session_file)
                    except Exception:
                        pass

                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    **storage_kwargs,
                )
                
                # Feature 41: Inject stealth cloaking script on every new page
                context.add_init_script(STEALTH_INIT_SCRIPT)
                page = context.new_page()

        while True:
            job = self._jobs.get()
            if job is None:
                break
            action, kwargs, res_queue = job
            try:
                _init_browser()

                # Action: Open URL
                if action == "open":
                    url = kwargs["url"]
                    if not url.startswith(("http://", "https://")):
                        url = "https://" + url
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(0.5)
                    res_queue.put(("ok", f"Opened {url}. Title: '{page.title()}'"))

                # Action: Search
                elif action == "search":
                    query = kwargs["query"]
                    search_url = f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"
                    page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(0.3)

                    results = []
                    rows = page.query_selector_all("table tr")
                    current_title = None
                    for row in rows[:20]:
                        try:
                            link = row.query_selector("a.result-link")
                            snippet = row.query_selector("td.result-snippet")
                            if link:
                                current_title = link.inner_text().strip()
                            if snippet and current_title:
                                s = snippet.inner_text().strip()
                                results.append(f"• **{current_title}**\n  {s}")
                                current_title = None
                        except Exception:
                            continue

                    # Fallback to Bing if DDG Lite returned nothing
                    if not results:
                        page.goto(f"https://www.bing.com/search?q={quote_plus(query)}", wait_until="domcontentloaded", timeout=20000)
                        time.sleep(0.5)
                        for el in page.query_selector_all("li.b_algo")[:5]:
                            try:
                                t = el.query_selector("h2")
                                s = el.query_selector(".b_caption p")
                                title = t.inner_text().strip() if t else ""
                                snip = s.inner_text().strip() if s else ""
                                if title:
                                    results.append(f"• **{title}**\n  {snip}")
                            except Exception:
                                continue

                    summary = "\n\n".join(results) if results else "No direct results found."
                    res_queue.put(("ok", f"--- Search Results for '{query}' ---\n{summary}"))

                # Action: Read page text
                elif action == "read":
                    max_chars = kwargs.get("max_chars", 3500)
                    text = page.evaluate("""() => {
                        const bad = document.querySelectorAll('script, style, noscript, nav, footer, iframe');
                        bad.forEach(b => b.remove());
                        return document.body ? document.body.innerText : '';
                    }""")
                    clean = re.sub(r"\n{3,}", "\n\n", text.strip())[:max_chars]
                    res_queue.put(("ok", f"--- {page.title()} ({page.url}) ---\n{clean}"))

                # Action: Click
                elif action == "click":
                    selector = kwargs.get("selector")
                    text = kwargs.get("text")
                    if selector:
                        page.click(selector, timeout=8000)
                        res_queue.put(("ok", f"Clicked selector '{selector}'."))
                    elif text:
                        page.click(f"text='{text}'", timeout=8000)
                        res_queue.put(("ok", f"Clicked text '{text}'."))
                    else:
                        res_queue.put(("err", "Must provide selector or text to click."))

                # Action: Type
                elif action == "type":
                    selector = kwargs.get("selector", "input[type='text'], textarea, input[name='q']")
                    text = kwargs["text"]
                    submit = kwargs.get("submit", False)
                    page.fill(selector, text, timeout=8000)
                    if submit:
                        page.press(selector, "Enter")
                        time.sleep(0.5)
                    res_queue.put(("ok", f"Typed '{text}' into '{selector}'."))

                # Action: Screenshot
                elif action == "screenshot":
                    path = kwargs.get("path", "browser_screenshot.png")
                    page.screenshot(path=path)
                    res_queue.put(("ok", f"Saved screenshot to '{path}'."))

                # Feature 42: Save Session State
                elif action == "save_session":
                    target_file = kwargs.get("filepath") or str(session_file)
                    context.storage_state(path=target_file)
                    res_queue.put(("ok", f"Browser cookies and session state successfully persisted to '{target_file}'."))

                # Feature 42: Load Session State
                elif action == "load_session":
                    target_file = kwargs.get("filepath") or str(session_file)
                    if os.path.exists(target_file):
                        context.close()
                        context = browser.new_context(
                            storage_state=target_file,
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                            viewport={"width": 1280, "height": 800},
                        )
                        context.add_init_script(STEALTH_INIT_SCRIPT)
                        page = context.new_page()
                        res_queue.put(("ok", f"Browser session restored from '{target_file}'."))
                    else:
                        res_queue.put(("err", f"Session file '{target_file}' not found."))

                # Feature 43: Multi-Tab Orchestration
                elif action == "multi_tab":
                    urls = kwargs.get("urls", [])
                    max_tabs = kwargs.get("max_tabs", 5)
                    tab_results = []
                    
                    for u in urls[:max_tabs]:
                        if not u.startswith(("http://", "https://")):
                            u = "https://" + u
                        p = None
                        try:
                            p = context.new_page()
                            p.goto(u, wait_until="domcontentloaded", timeout=15000)
                            title = p.title()
                            extracted_price = p.evaluate("""() => {
                                const priceEl = document.querySelector('[class*="price"], [id*="price"], .a-price-whole');
                                return priceEl ? priceEl.innerText.trim() : null;
                            }""")
                            info = f"Title: '{title}'"
                            if extracted_price:
                                info += f" | Price/Metric: {extracted_price}"
                            tab_results.append(f"• **{u}** -> {info}")
                        except Exception as e:
                            tab_results.append(f"• **{u}** -> Load failed: {e}")
                        finally:
                            if p is not None:
                                try:
                                    p.close()
                                except Exception:
                                    pass

                    report = f"🌐 --- Multi-Tab Orchestrator ({len(urls)} target URLs) ---\n" + "\n".join(tab_results)
                    res_queue.put(("ok", report))

                # Feature 44: Structured Data Extraction
                elif action == "extract_structured_data":
                    url = kwargs.get("url")
                    if url:
                        if not url.startswith(("http://", "https://")):
                            url = "https://" + url
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)

                    extracted = page.evaluate("""() => {
                        const result = { json_ld: [], opengraph: {}, meta: {} };

                        // 1. JSON-LD scripts
                        document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                            try {
                                result.json_ld.push(JSON.parse(s.innerText));
                            } catch (e) {}
                        });

                        // 2. OpenGraph tags
                        document.querySelectorAll('meta[property^="og:"]').forEach(m => {
                            const prop = m.getAttribute('property');
                            const cont = m.getAttribute('content');
                            if (prop && cont) result.opengraph[prop] = cont;
                        });

                        // 3. Twitter and standard meta
                        document.querySelectorAll('meta[name^="description"], meta[name^="twitter:"]').forEach(m => {
                            const n = m.getAttribute('name');
                            const c = m.getAttribute('content');
                            if (n && c) result.meta[n] = c;
                        });

                        return result;
                    }""")

                    summary_lines = [f"📊 --- Structured Data for {page.title()} ({page.url}) ---"]
                    if extracted.get("opengraph"):
                        summary_lines.append("[OpenGraph Metadata]:")
                        for k, v in extracted["opengraph"].items():
                            summary_lines.append(f"  • {k}: {v}")

                    if extracted.get("json_ld"):
                        summary_lines.append(f"[JSON-LD Schemas ({len(extracted['json_ld'])} found)]:")
                        for idx, schema in enumerate(extracted["json_ld"][:3], 1):
                            schema_type = schema.get("@type", "Entity") if isinstance(schema, dict) else "Entity"
                            summary_lines.append(f"  • Schema #{idx} [@type: {schema_type}]: {json.dumps(schema)[:150]}...")

                    if not extracted.get("opengraph") and not extracted.get("json_ld"):
                        summary_lines.append("No JSON-LD or OpenGraph structured metadata found on this page.")

                    res_queue.put(("ok", "\n".join(summary_lines)))

                # Feature 45: Page Snapshot Diffing
                elif action == "diff_snapshots":
                    url = kwargs["url"]
                    snapshot_id = kwargs.get("snapshot_id", "default")
                    if not url.startswith(("http://", "https://")):
                        url = "https://" + url

                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(0.5)

                    baseline_path = SNAPSHOTS_DIR / f"page_{snapshot_id}_baseline.png"
                    current_path = SNAPSHOTS_DIR / f"page_{snapshot_id}_current.png"
                    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

                    if not baseline_path.exists():
                        page.screenshot(path=str(baseline_path))
                        res_queue.put(("ok", f"Initial baseline snapshot captured and saved for '{url}' (ID: {snapshot_id})."))
                    else:
                        page.screenshot(path=str(current_path))
                        # Compare
                        import numpy as np
                        from PIL import Image

                        img1 = Image.open(str(baseline_path)).convert("RGB")
                        img2 = Image.open(str(current_path)).convert("RGB")

                        if img1.size != img2.size:
                            img2 = img2.resize(img1.size)

                        arr1 = np.array(img1, dtype=np.int16)
                        arr2 = np.array(img2, dtype=np.int16)
                        diff = np.abs(arr1 - arr2)
                        delta_px = np.count_nonzero(diff > 30)
                        total_px = arr1.shape[0] * arr1.shape[1] * arr1.shape[2]
                        diff_pct = (delta_px / total_px) * 100

                        # Overwrite baseline with new current
                        page.screenshot(path=str(baseline_path))

                        if diff_pct < 0.1:
                            status = "NO CHANGE DETECTED (Page is static)"
                        else:
                            status = f"PAGE MODIFIED ({diff_pct:.2f}% visual delta)"

                        res_queue.put(("ok", f"📸 Page Snapshot Diff [{snapshot_id}]: {status}\nTarget: {url}\nDelta: {delta_px} pixels changed."))

                # Action: Close
                elif action == "close":
                    if browser:
                        browser.close()
                    if playwright:
                        playwright.stop()
                    playwright = browser = context = page = None
                    res_queue.put(("ok", "Browser session closed."))

                else:
                    res_queue.put(("err", f"Unknown browser action '{action}'."))

            except Exception as e:
                res_queue.put(("err", f"Browser error: {e}"))

    def execute(self, action: str, timeout: float = 60.0, **kwargs) -> str:
        q = queue.Queue()
        self._jobs.put((action, kwargs, q))
        try:
            status, result = q.get(timeout=timeout)
            return result
        except queue.Empty:
            return f"Failed: Browser operation '{action}' timed out after {timeout}s."


_worker = None
_wlock = threading.Lock()

def _get_worker() -> BrowserWorker:
    global _worker
    with _wlock:
        if _worker is None:
            _worker = BrowserWorker()
        return _worker


def browser_open(url: str) -> str:
    """Navigates to a webpage in the browser."""
    return _get_worker().execute("open", url=url)


def browser_search(query: str) -> str:
    """Fast, anti-bot resilient web search returning instant top snippets."""
    return _get_worker().execute("search", query=query)


def browser_read(max_chars: int = 3500) -> str:
    """Extracts clean text content from the current open webpage."""
    return _get_worker().execute("read", max_chars=max_chars)


def browser_click(selector: str = "", text: str = "") -> str:
    """Clicks an element on the current webpage by CSS selector or visible text."""
    return _get_worker().execute("click", selector=selector, text=text)


def browser_type(text: str, selector: str = "input", submit: bool = False) -> str:
    """Types text into an input element and optionally submits."""
    return _get_worker().execute("type", selector=selector, text=text, submit=submit)


def browser_close() -> str:
    """Closes the browser session."""
    return _get_worker().execute("close")


def save_browser_session(filepath: Optional[str] = None) -> str:
    """Feature 42: Persists browser cookies, storage, and authentication state."""
    return _get_worker().execute("save_session", filepath=filepath)


def load_browser_session(filepath: Optional[str] = None) -> str:
    """Feature 42: Restores browser cookies and authentication state from disk."""
    return _get_worker().execute("load_session", filepath=filepath)


def orchestrate_multi_tabs(urls: List[str], max_tabs: int = 5) -> str:
    """Feature 43: Concurrently opens multiple tabs to compare prices, specs, or headlines."""
    return _get_worker().execute("multi_tab", urls=urls, max_tabs=max_tabs)


def extract_structured_data(url: Optional[str] = None) -> str:
    """Feature 44: Extracts JSON-LD schemas and OpenGraph metadata from current or target URL."""
    return _get_worker().execute("extract_structured_data", url=url)


def diff_page_snapshots(url: str, snapshot_id: str = "default") -> str:
    """Feature 45: Compares visual page states over time and detects changes."""
    return _get_worker().execute("diff_snapshots", url=url, snapshot_id=snapshot_id)
