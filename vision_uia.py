"""
vision_uia.py - Windows UI Automation & Vision Perception Engine for BERU AI AGENT.
Combines:
  1. Native Windows UI Automation (UIA) tree for accessibility-based element identification (results depend on app support).
  2. OCR Engine (Tesseract / EasyOCR fallback) for raw graphics/text on screen.
  3. Closed-loop visual verification (before/after screenshot diff).
  4. Precise mouse/keyboard input automation via pydirectinput / pyautogui.
  5. Multi-App Context Switching (Feature 36)
  6. Desktop Activity Video/GIF Recorder (Feature 37)
  7. Element Click Verification with Visual Diffing (Feature 38)
  8. Form Auto-Fill by Label Recognition (Feature 39)
  9. Screen Hotspot & Frozen UI Detection (Feature 40)
"""
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import WORKSPACE_DIR

# Enable Windows DPI Awareness so screen coordinates match mouse clicks accurately
if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def capture_screenshot(save_path: Optional[str] = None):
    """Captures a screenshot of the primary screen. Returns (PIL.Image, left, top)."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        if save_path:
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
            img.save(save_path)
        return img, monitor["left"], monitor["top"]


# --------------------------------------------------------------------------- #
# UIA Native Element Discovery (with wait visible bug fix)
# --------------------------------------------------------------------------- #
def get_uia_elements(window_title_keyword: str = "", max_elements: int = 50) -> List[Dict[str, Any]]:
    """
    Extracts interactive UI elements (buttons, inputs, menus) directly from the
    Windows UI Automation tree with 0% OCR error. Enforces win.wait("visible", timeout=2).
    """
    elements = []
    try:
        from pywinauto import Desktop
        d = Desktop(backend="uia")
        windows = d.windows()
        
        target_windows = []
        for w in windows:
            try:
                title = w.window_text()
                if not title:
                    continue
                if not window_title_keyword or window_title_keyword.lower() in title.lower():
                    target_windows.append(w)
            except Exception:
                continue

        count = 1
        for win in target_windows[:3]:
            try:
                try:
                    win.wait("visible", timeout=2)  # ensures window is ready for tree traversal
                except Exception:
                    pass
                descendants = win.descendants()
                for el in descendants:
                    try:
                        c_type = el.element_info.control_type
                        name = el.element_info.name
                        auto_id = el.element_info.automation_id
                        rect = el.rectangle()

                        # Keep interactive or labelled elements
                        if name and c_type in ("Button", "MenuItem", "Edit", "CheckBox", "RadioButton", "TabItem", "Hyperlink", "ListItem"):
                            cx = int((rect.left + rect.right) / 2)
                            cy = int((rect.top + rect.bottom) / 2)
                            elements.append({
                                "id": count,
                                "type": c_type.lower(),
                                "name": name[:50],
                                "auto_id": auto_id[:30] if auto_id else "",
                                "x": cx,
                                "y": cy,
                                "box": (rect.left, rect.top, rect.right, rect.bottom),
                            })
                            count += 1
                            if len(elements) >= max_elements:
                                break
                    except Exception:
                        continue
            except Exception:
                continue

    except Exception:
        pass

    return elements


# --------------------------------------------------------------------------- #
# OCR Fallback Perception
# --------------------------------------------------------------------------- #
def get_ocr_elements(img, max_elements: int = 40) -> List[Dict[str, Any]]:
    """Extracts text elements using Tesseract or EasyOCR as fallback."""
    elements = []
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 11")

        lines = {}
        for i, word in enumerate(data["text"]):
            word = (word or "").strip()
            try:
                conf = float(data["conf"][i])
            except Exception:
                conf = -1
            if not word or conf < 40:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            lines.setdefault(key, []).append((x, y, x + w, y + h, word))

        count = 1
        for words in lines.values():
            x1 = min(w[0] for w in words)
            y1 = min(w[1] for w in words)
            x2 = max(w[2] for w in words)
            y2 = max(w[3] for w in words)
            text_line = " ".join(w[4] for w in words)
            elements.append({
                "id": count,
                "type": "text",
                "name": text_line[:60],
                "auto_id": "",
                "x": int((x1 + x2) / 2),
                "y": int((y1 + y2) / 2),
                "box": (x1, y1, x2, y2),
            })
            count += 1
            if len(elements) >= max_elements:
                break
    except Exception:
        pass

    return elements


# --------------------------------------------------------------------------- #
# High-Level Screen Inspector
# --------------------------------------------------------------------------- #
def inspect_screen(window_keyword: str = "") -> str:
    """
    Returns a unified semantic map of the screen:
    First tries Windows UI Automation (exact button and input names).
    Falls back to OCR if UIA detects no elements.
    """
    uia_els = get_uia_elements(window_keyword)
    if uia_els:
        lines = [f"Found {len(uia_els)} Native UI Elements:"]
        for e in uia_els:
            lines.append(f"#{e['id']} [{e['type']}] '{e['name']}' @({e['x']}, {e['y']})")
        return "\n".join(lines)

    # Fallback to screenshot OCR
    try:
        img, left, top = capture_screenshot()
        ocr_els = get_ocr_elements(img)
        if ocr_els:
            lines = [f"Found {len(ocr_els)} OCR Elements:"]
            for e in ocr_els:
                lines.append(f"#{e['id']} [text] '{e['name']}' @({e['x'] + left}, {e['y'] + top})")
            return "\n".join(lines)
    except Exception as e:
        return f"Perception error: {e}"

    return "No UI elements could be resolved. Make sure target application is open and visible."


# --------------------------------------------------------------------------- #
# Click & Interaction Execution
# --------------------------------------------------------------------------- #
def click_element_by_name(target_name: str, double_click: bool = False) -> str:
    """
    Finds the on-screen button/menu/tab matching `target_name` and clicks it.
    Uses UIA first, then fuzzy OCR matching.
    """
    if not target_name.strip():
        return "Failed: Target name is empty."

    # 1. Try UIA
    uia_els = get_uia_elements()
    for e in uia_els:
        if target_name.lower() in e["name"].lower() or e["name"].lower() in target_name.lower():
            return _execute_click(e["x"], e["y"], double_click, f"UIA element '{e['name']}'")

    # 2. Try OCR
    try:
        img, left, top = capture_screenshot()
        ocr_els = get_ocr_elements(img)
        best, best_score = None, 0.0
        for e in ocr_els:
            score = difflib.SequenceMatcher(None, target_name.lower(), e["name"].lower()).ratio()
            if target_name.lower() in e["name"].lower():
                score = max(score, 0.85)
            if score > best_score:
                best, best_score = e, score

        if best and best_score >= 0.6:
            return _execute_click(best["x"] + left, best["y"] + top, double_click, f"OCR text '{best['name']}' (match {best_score:.2f})")
    except Exception as e:
        return f"Click search failed: {e}"

    # YOLO is used only for an explicitly named generic control class. If the
    # detector sees multiple matching controls, refuse to guess which one.
    aliases = {"text box": "input", "input field": "input", "check box": "checkbox"}
    requested_class = aliases.get(target_name.strip().casefold(), target_name.strip().casefold())
    if requested_class in {"button", "input", "checkbox"}:
        try:
            vision = json.loads(detect_screen_elements_yolo(max_detections=100))
            matches = [d for d in vision.get("detections", [])
                       if str(d.get("label", "")).casefold() == requested_class
                       and float(d.get("confidence", 0)) >= 0.70]
            if len(matches) == 1:
                x1, y1, x2, y2 = matches[0]["screen_box"]
                return _execute_click(round((x1 + x2) / 2), round((y1 + y2) / 2),
                                      double_click, f"unique YOLO {requested_class} detection")
            if len(matches) > 1:
                return f"Failed safely: YOLO detected {len(matches)} matching {requested_class} controls; specify a unique accessible label."
        except (ValueError, KeyError, TypeError):
            pass

    return f"Failed: Could not find any UI element matching '{target_name}'."


def _execute_click(x: int, y: int, double: bool = False, label: str = "") -> str:
    try:
        import pydirectinput
        pydirectinput.FAILSAFE = False
        pydirectinput.moveTo(int(x), int(y))
        time.sleep(0.05)
        if double:
            pydirectinput.doubleClick()
        else:
            pydirectinput.click()
        return f"Clicked {label} at ({x}, {y})."
    except Exception:
        try:
            import pyautogui
            pyautogui.moveTo(int(x), int(y))
            if double:
                pyautogui.doubleClick()
            else:
                pyautogui.click()
            return f"Clicked {label} at ({x}, {y}) via pyautogui."
        except Exception as ex:
            return f"Click execution error: {ex}"


def type_into_field(text: str, submit: bool = False) -> str:
    """Types text using human-like typing simulation without artificial delays."""
    try:
        import pyautogui
        pyautogui.write(text, interval=0.01)
        if submit:
            pyautogui.press("enter")
        return f"Typed '{text}' (submit={submit})."
    except Exception as e:
        return f"Failed to type: {e}"


def press_keyboard_key(key: str) -> str:
    """Presses a keyboard key like 'enter', 'tab', 'esc', 'win'."""
    try:
        import pyautogui
        pyautogui.press(key.lower().strip())
        return f"Pressed key '{key}'."
    except Exception as e:
        return f"Failed to press key: {e}"


# --------------------------------------------------------------------------- #
# Feature 36: Multi-App Context Switching
# --------------------------------------------------------------------------- #
def switch_app_context(window_title_keyword: str) -> str:
    """
    Identifies and brings the specified application window to the foreground,
    allowing seamless context switching between different open desktop applications.
    """
    target = window_title_keyword.strip().lower()
    if not target:
        return "Failed: Window title keyword cannot be empty."

    try:
        from pywinauto import Desktop
        d = Desktop(backend="uia")
        for win in d.windows():
            try:
                title = win.window_text()
                if title and target in title.lower():
                    win.set_focus()
                    time.sleep(0.1)
                    return f"Successfully focused window '{title}'."
            except Exception:
                continue
    except Exception:
        pass

    # Fallback to win32gui
    try:
        import win32gui
        import win32con

        def enum_callback(hwnd, matched_hwnds):
            if win32gui.IsWindowVisible(hwnd):
                text = win32gui.GetWindowText(hwnd)
                if text and target in text.lower():
                    matched_hwnds.append((hwnd, text))

        matched = []
        win32gui.EnumWindows(enum_callback, matched)
        if matched:
            hwnd, title = matched[0]
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return f"Switched foreground focus to '{title}' (HWND: {hwnd})."
    except Exception as e:
        return f"Context switch error: {e}"

    return f"Failed: Could not find any open window matching '{window_title_keyword}'."


def get_active_app_context() -> str:
    """Returns the title and process of the currently focused desktop window."""
    try:
        import win32gui
        import win32process
        import psutil

        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_name = psutil.Process(pid).name() if pid else "unknown"
            return f"Active Window: '{title}' (Process: {proc_name}, PID: {pid})"
    except Exception:
        pass
    return "Active window context could not be determined."


# --------------------------------------------------------------------------- #
# Feature 37: Desktop Activity Video/GIF Recorder
# --------------------------------------------------------------------------- #
def record_desktop_activity(duration_sec: int = 5, output_filename: str = "desktop_recording.gif", fps: int = 3) -> str:
    """
    Records desktop screen activity for N seconds and compiles an animated GIF/clip
    for visual debugging and task verification.
    """
    import mss
    from PIL import Image

    duration = max(1, min(duration_sec, 15))
    total_frames = int(duration * fps)
    interval = 1.0 / fps

    frames: List[Image.Image] = []
    out_path = WORKSPACE_DIR / output_filename
    os.makedirs(WORKSPACE_DIR, exist_ok=True)

    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        for _ in range(total_frames):
            shot = sct.grab(monitor)
            frame_img = Image.frombytes("RGB", shot.size, shot.rgb)
            # Resize frame to 50% for fast processing and smaller file size
            thumb = frame_img.resize((monitor["width"] // 2, monitor["height"] // 2), Image.Resampling.LANCZOS)
            frames.append(thumb)
            time.sleep(interval)

    if frames:
        frames[0].save(
            str(out_path),
            save_all=True,
            append_images=frames[1:],
            duration=int(interval * 1000),
            loop=0,
            optimize=True,
        )
        return f"Desktop activity successfully recorded ({duration}s, {len(frames)} frames) saved to '{out_path}'."
    return "Failed to capture frames for video recording."


# --------------------------------------------------------------------------- #
# Feature 38: Element Click Verification (Screenshot Diff)
# --------------------------------------------------------------------------- #
def click_element_with_verification(target_name: str, expected_change_hint: str = "") -> str:
    """
    Executes a click on an element, captures before/after screen states, computes
    a perceptual difference, and verifies whether the click triggered an actual UI change.
    """
    import numpy as np

    img_before, _, _ = capture_screenshot()
    click_res = click_element_by_name(target_name)
    if "Failed" in click_res:
        return click_res

    time.sleep(0.3)
    img_after, _, _ = capture_screenshot()

    # Compare pixel diffs
    arr_b = np.array(img_before, dtype=np.int16)
    arr_a = np.array(img_after, dtype=np.int16)
    diff = np.abs(arr_b - arr_a)
    diff_pixels = np.count_nonzero(diff > 25)
    total_pixels = arr_b.shape[0] * arr_b.shape[1] * arr_b.shape[2]
    change_ratio = (diff_pixels / total_pixels) * 100

    status = "VERIFIED (UI state altered)" if change_ratio > 0.05 else "NO VISIBLE CHANGE (UI appears unchanged)"
    report = (
        f"{click_res}\n"
        f"🔍 Verification: {status}\n"
        f"• Visual Pixel Delta: {change_ratio:.2f}% of screen pixels updated."
    )
    if expected_change_hint:
        report += f"\n• Expected Hint: '{expected_change_hint}'"
    return report


# --------------------------------------------------------------------------- #
# Feature 39: Form Auto-Fill by Label Recognition
# --------------------------------------------------------------------------- #
def auto_fill_form(field_mappings_json: str) -> str:
    """
    Detects input fields on screen matching given field labels/placeholders,
    navigates to them via UIA, and types the provided values.
    Accepts JSON string: '{"Username": "admin", "Email": "user@example.com"}'
    """
    try:
        mappings = json.loads(field_mappings_json) if isinstance(field_mappings_json, str) else field_mappings_json
    except Exception as e:
        return f"Form Auto-Fill Error: Invalid JSON input: {e}"

    uia_els = get_uia_elements(max_elements=80)
    edits = [e for e in uia_els if e["type"] in ("edit", "combobox")]
    labels = [e for e in uia_els if e["type"] in ("text", "button", "menuitem")]

    results = []
    for field_name, value in mappings.items():
        matched_edit = None
        # 1. Direct name match on edit element
        for ed in edits:
            if field_name.lower() in ed["name"].lower():
                matched_edit = ed
                break

        # 2. Proximity match: find label near an edit box
        if not matched_edit:
            for lbl in labels:
                if field_name.lower() in lbl["name"].lower():
                    # Find closest edit element to the right or below the label
                    lx, ly = lbl["x"], lbl["y"]
                    candidates = [ed for ed in edits if ed["x"] >= lx - 50 and ed["y"] >= ly - 30]
                    if candidates:
                        candidates.sort(key=lambda ed: (ed["x"] - lx)**2 + (ed["y"] - ly)**2)
                        matched_edit = candidates[0]
                        break

        if matched_edit:
            _execute_click(matched_edit["x"], matched_edit["y"], False, f"field '{field_name}'")
            type_into_field(str(value), submit=False)
            results.append(f"✅ Filled '{field_name}' -> '{value}'")
        else:
            results.append(f"❌ Field '{field_name}' not found on active screen.")

    return "Form Auto-Fill Results:\n" + "\n".join(results)


# --------------------------------------------------------------------------- #
# Feature 40: Screen Hotspot & Frozen UI Detection
# --------------------------------------------------------------------------- #
def detect_screen_hotspots(window_title: str = "") -> str:
    """
    Audits UI controls on the screen to identify unresponsive controls,
    dead buttons, or a frozen application window.
    """
    import numpy as np

    uia_els = get_uia_elements(window_title, max_elements=25)
    interactive = [e for e in uia_els if e["type"] in ("button", "menuitem", "tabitem")]

    if not interactive:
        return "Screen Hotspot Detection: No interactive buttons or controls detected on active screen."

    dead_controls = []
    active_controls = []

    # Check top 3 interactive controls for visual hover response
    try:
        import pyautogui
        original_x, original_y = pyautogui.position()
        
        for ctrl in interactive[:3]:
            # Take screenshot before hover
            img_b, _, _ = capture_screenshot()
            pyautogui.moveTo(ctrl["x"], ctrl["y"])
            time.sleep(0.08)
            img_a, _, _ = capture_screenshot()

            arr_b = np.array(img_b, dtype=np.int16)
            arr_a = np.array(img_a, dtype=np.int16)
            diff = np.abs(arr_b - arr_a)
            hover_delta = np.count_nonzero(diff > 20)

            if hover_delta > 5:
                active_controls.append(f"'{ctrl['name']}' (Hover delta: {hover_delta}px)")
            else:
                dead_controls.append(f"'{ctrl['name']}' @({ctrl['x']}, {ctrl['y']})")

        pyautogui.moveTo(original_x, original_y)
    except Exception as e:
        return f"Hotspot detection failed: {e}"

    lines = [
        f"🎯 --- Screen UI Responsiveness & Hotspot Audit ---",
        f"Active Responsive Controls: {', '.join(active_controls) if active_controls else 'None detected'}",
        f"Passive/Static Controls: {', '.join(dead_controls) if dead_controls else 'All tested controls responded'}",
    ]
    return "\n".join(lines)


def detect_screen_elements_yolo(max_detections: int = 50) -> str:
    """Run an explicitly configured local YOLO weights file on a desktop screenshot.

    Ultralytics and weights are optional and never downloaded automatically.
    This returns object labels and coordinates only (no OCR or screenshot upload).
    """
    weights = os.getenv("BERU_YOLO_MODEL", "").strip()
    if not weights:
        return "Local YOLO is not configured. Set BERU_YOLO_MODEL to a reviewed local .pt weights file. No model was downloaded."
    try:
        model_path = Path(weights).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return "Configured YOLO weights path could not be resolved."
    if not model_path.is_file() or model_path.suffix.lower() != ".pt":
        return "Configured YOLO weights must be an existing local .pt file; automatic model downloads are disabled."
    try:
        from ultralytics import YOLO
    except ImportError:
        return "Ultralytics is not installed. Install it separately only if you trust its dependencies and model source."
    try:
        limit = max(1, min(int(max_detections), 100))
        image, left, top = capture_screenshot()
        model = YOLO(str(model_path), task="detect")
        results = model.predict(source=image, verbose=False, max_det=limit, imgsz=1280)
        detections = []
        for result in results[:1]:
            names = result.names
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in list(boxes)[:limit]:
                cls_id = int(box.cls[0].item())
                confidence = float(box.conf[0].item())
                x1, y1, x2, y2 = [round(float(v), 1) for v in box.xyxy[0].tolist()]
                label = names.get(cls_id, cls_id) if hasattr(names, "get") else (names[cls_id] if cls_id < len(names) else cls_id)
                detections.append({"label": str(label),
                                   "confidence": round(confidence, 3),
                                   "box": [x1, y1, x2, y2],
                                   "screen_box": [x1 + left, y1 + top, x2 + left, y2 + top]})
        return json.dumps({"detector": "local YOLO", "weights": model_path.name,
                           "detections": detections}, ensure_ascii=False)
    except Exception as exc:
        return f"Local YOLO detection failed: {type(exc).__name__}: {exc}"


def inspect_screen_hybrid(window_keyword: str = "", max_detections: int = 50) -> str:
    """Combine UI Automation/OCR inspection with optional local YOLO detections."""
    uia = inspect_screen(window_keyword)
    visual = detect_screen_elements_yolo(max_detections)
    return "UI Automation and OCR:\n" + uia[:12000] + "\n\nLocal YOLO detections:\n" + visual[:12000]
