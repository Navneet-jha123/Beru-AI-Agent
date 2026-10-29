"""Local-only, non-diagnostic clinical calculators and lab-text extraction.

Design (AgentMD-style tool use):
    1. ``suggest_calculators(note)``  -> retrieve candidate calculators for a clinical note
    2. LLM extracts the required parameters from the note (see ``tool_specs()``)
    3. ``run_calculator(name, **params)`` -> deterministic, validated, local computation
    4. LLM interprets the returned string in context

Nothing here diagnoses. Every output carries a disclaimer. Invalid or ambiguous input
returns an error string -- it is never silently scored as zero.
"""
from __future__ import annotations

import functools
import inspect
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 40
MAX_TEXT_CHARS = 500_000
MAX_NOTE_CHARS = 20_000
DISCLAIMER = ("For information only; this is not medical advice or a diagnosis. "
              "Review results with a licensed clinician.")

# If set (e.g. (Path("~/medical_uploads").expanduser().resolve(),)), file tools refuse
# anything outside these folders. Strongly recommended when an LLM chooses the path.
ALLOWED_ROOTS: Optional[Tuple[Path, ...]] = None


class InputError(ValueError):
    """Raised for invalid calculator input; converted to a user-facing message."""


# --------------------------------------------------------------------------------------
# Input validation helpers
# --------------------------------------------------------------------------------------
def _number(value: Any, name: str, lo: float, hi: float, *, integer: bool = False):
    if isinstance(value, bool):
        raise InputError(f"{name} must be a number, not a boolean.")
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        raise InputError(f"{name} must be a number.") from None
    if not math.isfinite(x):
        raise InputError(f"{name} must be finite.")
    if not lo <= x <= hi:
        raise InputError(f"{name} must be between {lo:g} and {hi:g} (check units).")
    if integer:
        if x != int(x):
            raise InputError(f"{name} must be a whole number.")
        return int(x)
    return x


_TRUE = {"true", "yes", "y", "1", "present", "positive"}
_FALSE = {"false", "no", "n", "0", "absent", "negative"}


def _flag(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().casefold()
        if v in _TRUE:
            return True
        if v in _FALSE:
            return False
    raise InputError(f"{name} must be true/false (yes/no).")


def _choice(value: Any, name: str, options: Dict[str, int]) -> int:
    if not isinstance(value, str) or value.strip().casefold() not in options:
        allowed = ", ".join(sorted(options))
        raise InputError(f"{name} must be one of: {allowed}.")
    return options[value.strip().casefold()]


# --------------------------------------------------------------------------------------
# Calculator registry (retrieval + execution)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Calculator:
    name: str
    description: str
    keywords: Tuple[str, ...]
    params: Dict[str, str]
    func: Callable[..., str]
    signature: inspect.Signature


_REGISTRY: Dict[str, Calculator] = {}


def _register(description: str, keywords: Iterable[str], params: Dict[str, str]):
    def deco(fn: Callable[..., str]):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except InputError as exc:
                return f"Input error: {exc} {DISCLAIMER}"
        _REGISTRY[fn.__name__] = Calculator(
            fn.__name__, description, tuple(k.casefold() for k in keywords),
            params, wrapper, inspect.signature(fn))
        return wrapper
    return deco


def list_calculators() -> str:
    rows = [f"- {c.name}: {c.description}" for c in _REGISTRY.values()]
    return "Available calculators:\n" + "\n".join(rows)


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def suggest_calculators(clinical_text: str, top_k: int = 3) -> str:
    """Lexical retrieval of candidate calculators for a note.

    A deliberately simple local stand-in for embedding retrieval; replace the scoring
    here with a local embedding model when you add one.
    """
    if not isinstance(clinical_text, str) or not clinical_text.strip():
        return f"Provide clinical text to match against. {DISCLAIMER}"
    text = clinical_text[:MAX_NOTE_CHARS].casefold()
    toks = _tokens(text)
    scored = []
    for calc in _REGISTRY.values():
        # whole-word/phrase match so "af" does not fire inside "after"
        score = sum(3 for kw in calc.keywords if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text))
        score += len(toks & _tokens(calc.description)) * 0.25
        if score >= 1:
            scored.append((score, calc))
    scored.sort(key=lambda s: -s[0])
    if not scored:
        return "No calculator matched. " + list_calculators()
    try:
        k = max(1, min(int(top_k), 10))
    except (TypeError, ValueError):
        k = 3
    lines = ["Candidate calculators (verify applicability before use):"]
    for _, calc in scored[:k]:
        lines.append(f"- {calc.name}: {calc.description} | parameters: {', '.join(calc.params)}")
    return "\n".join(lines)


def tool_specs() -> List[Dict[str, Any]]:
    """JSON-schema tool specs for LLM function calling (one per calculator)."""
    type_map = {"int": "integer", "float": "number", "bool": "boolean", "str": "string"}
    specs = []
    for calc in _REGISTRY.values():
        props, required = {}, []
        for pname, p in calc.signature.parameters.items():
            ann = p.annotation if isinstance(p.annotation, str) else getattr(p.annotation, "__name__", "str")
            props[pname] = {"type": type_map.get(ann, "string"), "description": calc.params.get(pname, "")}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        specs.append({"name": calc.name, "description": calc.description,
                      "parameters": {"type": "object", "properties": props, "required": required}})
    return specs


def run_calculator(name: str, **params: Any) -> str:
    """Execute a registered calculator by name with validated parameters."""
    key = str(name).strip()
    calc = _REGISTRY.get(key) or _REGISTRY.get("calculate_" + key.removeprefix("calculate_"))
    if calc is None:
        return f"Unknown calculator '{key}'. {list_calculators()}"
    accepted = calc.signature.parameters
    unknown = sorted(set(params) - set(accepted))
    if unknown:
        return (f"Unknown parameter(s) for {calc.name}: {', '.join(unknown)}. "
                f"Expected: {', '.join(accepted)}. {DISCLAIMER}")
    missing = [n for n, p in accepted.items() if p.default is inspect.Parameter.empty and n not in params]
    if missing:
        return (f"Missing required parameter(s) for {calc.name}: {', '.join(missing)}. "
                f"Do not guess; ask for them. {DISCLAIMER}")
    return calc.func(**params)


# --------------------------------------------------------------------------------------
# File safety
# --------------------------------------------------------------------------------------
def _safe_file(file_path: str, expected_suffix: str, magic: Optional[bytes] = None) -> Tuple[Optional[Path], Optional[str]]:
    try:
        path = Path(file_path).expanduser().resolve(strict=True)
        if ALLOWED_ROOTS is not None and not any(path.is_relative_to(r) for r in ALLOWED_ROOTS):
            return None, "The file is outside the allowed folders."
        if not path.is_file():
            return None, "The supplied path is not a regular file."
        if path.suffix.casefold() != expected_suffix:
            return None, f"Expected a {expected_suffix} file."
        size = path.stat().st_size
        if size <= 0 or size > MAX_PDF_BYTES:
            return None, f"File must be between 1 byte and {MAX_PDF_BYTES // (1024 * 1024)} MB."
        if magic is not None:
            with path.open("rb") as fh:
                if not fh.read(len(magic)).startswith(magic):
                    return None, f"File content is not a valid {expected_suffix} file."
        return path, None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None, "The file could not be accessed. Check the path and permissions."


# --------------------------------------------------------------------------------------
# Lab extraction
# --------------------------------------------------------------------------------------
_ANALYTES: Dict[str, Tuple[str, ...]] = {
    "HbA1c": ("hemoglobin a1c", "haemoglobin a1c", "glycated hemoglobin", "glycosylated hemoglobin", "hba1c", "a1c"),
    "Hemoglobin": ("hemoglobin", "haemoglobin", "hgb", "hb"),
    "Glucose": ("fasting glucose", "glucose", "blood sugar"),
    "Total cholesterol": ("total cholesterol", "cholesterol, total", "cholesterol"),
    "LDL cholesterol": ("ldl cholesterol", "ldl-c", "ldl"),
    "HDL cholesterol": ("hdl cholesterol", "hdl-c", "hdl"),
    "Triglycerides": ("triglycerides", "triglyceride"),
    "Creatinine": ("creatinine",),
    "TSH": ("thyroid stimulating hormone", "tsh"),
    "ALT": ("alanine aminotransferase", "sgpt", "alt"),
    "AST": ("aspartate aminotransferase", "sgot", "ast"),
    "Sodium": ("sodium",),
    "Potassium": ("potassium",),
    "Platelets": ("platelet count", "platelets"),
    "WBC": ("white blood cell count", "total leucocyte count", "total leukocyte count", "wbc", "tlc"),
}
_NUM = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_VALUE_RE = re.compile(rf"(?<![\w.])({_NUM})")
_LABELLED_RANGE_RE = re.compile(
    rf"(?:reference\s*(?:range|interval)?|ref\.?\s*(?:range|interval)?|normal\s*range)\s*[:=]?\s*({_NUM})\s*(?:-|–|—|to)\s*({_NUM})", re.I)
_BARE_RANGE_RE = re.compile(rf"(?<![\w.])({_NUM})\s*(?:-|–|—|to)\s*({_NUM})(?![\w.]*\d)")
_UPPER_RE = re.compile(rf"(?:<|≤)\s*=?\s*({_NUM})")
_LOWER_RE = re.compile(rf"(?:>|≥)\s*=?\s*({_NUM})")
_UNIT_RE = re.compile(
    r"(?<![\w/])(mg/dL|mmol/L|g/dL|g/L|mIU/L|uIU/mL|µIU/mL|μIU/mL|mmol/mol|ng/mL|pg/mL|U/L|IU/L|mEq/L|"
    r"x?10\^?[39]/[µμu]?L|cells/[µμu]L|/[µμu]L|%)(?!\w)", re.I)
_FLAG_RE = re.compile(r"(?<![\w])(H|L|HIGH|LOW)(?![\w])")


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def _extract_lines(text: str) -> List[str]:
    lines: List[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line[:500])
    return lines


def _best_analyte(line: str) -> Optional[Tuple[str, int]]:
    """Longest alias wins, so 'Hemoglobin A1c' is HbA1c, not Hemoglobin."""
    low = line.casefold()
    best: Optional[Tuple[int, int, str, int]] = None  # (alias_len, -start, label, end)
    for label, aliases in _ANALYTES.items():
        for alias in aliases:
            for m in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", low):
                cand = (len(alias), -m.start(), label, m.end())
                if best is None or cand[:2] > best[:2]:
                    best = cand
    return (best[2], best[3]) if best else None


def _assess(number: float, after: str) -> Tuple[str, str]:
    """Return (interval_text, status) from a printed reference on the same line."""
    m = _LABELLED_RANGE_RE.search(after) or _BARE_RANGE_RE.search(after)
    if m:
        lo, hi = _to_float(m.group(1)), _to_float(m.group(2))
        if lo <= hi:
            status = "within printed interval" if lo <= number <= hi else "outside printed interval"
            return f" (printed interval: {m.group(1)}–{m.group(2)})", status
    m = _UPPER_RE.search(after)
    if m:
        ok = number <= _to_float(m.group(1))
        return f" (printed limit: <{m.group(1)})", "within printed limit" if ok else "outside printed limit"
    m = _LOWER_RE.search(after)
    if m:
        ok = number >= _to_float(m.group(1))
        return f" (printed limit: >{m.group(1)})", "within printed limit" if ok else "outside printed limit"
    return "", "not assessed (no reference interval detected on this line)"


def _find_results(lines: Iterable[str]) -> List[str]:
    found: List[str] = []
    for line in lines:
        hit = _best_analyte(line)
        if not hit:
            continue
        label, end = hit
        vm = _VALUE_RE.search(line, end)
        if not vm:
            continue
        value = vm.group(1)
        try:
            number = _to_float(value)
        except ValueError:
            continue
        after = line[vm.end():]
        unit_m = _UNIT_RE.search(after)
        unit = f" {unit_m.group(1)}" if unit_m else ""
        interval, status = _assess(number, after)
        flag_m = _FLAG_RE.search(after)
        flag = f" [lab flag: {flag_m.group(1).upper()}]" if flag_m else ""
        found.append(f"{label}: {value}{unit}{interval}{flag} — {status}.")
    return found


def parse_lab_text(text: str) -> str:
    """Extract supported analytes from already-extracted report text."""
    if not isinstance(text, str) or not text.strip():
        return f"No text provided. {DISCLAIMER}"
    results = _find_results(_extract_lines(text[:MAX_TEXT_CHARS]))
    if not results:
        return f"No supported analyte/value pairs were confidently recognized. {DISCLAIMER}"
    return ("Local extraction only (not a diagnosis; verify against the original report and units):\n"
            + "\n".join(results[:40]) + "\n\n" + DISCLAIMER)


def parse_lab_report(file_path: str) -> str:
    """Read up to 40 pages of a local text-based PDF and extract selected values."""
    path, error = _safe_file(file_path, ".pdf", magic=b"%PDF")
    if error:
        return f"Lab report not processed: {error} {DISCLAIMER}"
    try:
        import pdfplumber
    except ImportError:
        return f"Lab report not processed: install pdfplumber to enable local PDF text extraction. {DISCLAIMER}"
    try:
        chunks: List[str] = []
        used = 0
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return f"Lab report contains no pages. {DISCLAIMER}"
            for page in pdf.pages[:MAX_PDF_PAGES]:
                remaining = MAX_TEXT_CHARS - used
                if remaining <= 0:
                    break
                piece = (page.extract_text() or "")[:remaining]
                chunks.append(piece)
                used += len(piece)
        text = "\n".join(chunks)
    except Exception as exc:  # noqa: BLE001 - never leak document content in errors
        return f"Lab report could not be parsed ({type(exc).__name__}). It was not uploaded. {DISCLAIMER}"
    if not text.strip():
        return f"No selectable text was found. Scanned PDFs are not OCR'd by this tool. {DISCLAIMER}"
    return parse_lab_text(text)


# --------------------------------------------------------------------------------------
# Calculators
# --------------------------------------------------------------------------------------
@_register("Body-mass index screening (adults 20+). Optional Asian-population cutoffs.",
           ("bmi", "body mass index", "obesity", "overweight", "weight", "height"),
           {"weight_kg": "Weight in kilograms (1-1000)", "height_m": "Height in metres (0.3-3)",
            "asian_cutoffs": "Use Asian-population cutoffs (overweight >=23, obese >=25)"})
def calculate_bmi(weight_kg: float, height_m: float, asian_cutoffs: bool = False) -> str:
    weight = _number(weight_kg, "weight_kg", 1, 1000)
    height = _number(height_m, "height_m", 0.3, 3)
    asian = _flag(asian_cutoffs, "asian_cutoffs")
    bmi = weight / (height * height)
    over, obese = (23.0, 25.0) if asian else (25.0, 30.0)
    if bmi < 18.5:
        category = "below the usual adult screening range"
    elif bmi < over:
        category = "within the usual adult screening range"
    elif bmi < obese:
        category = "above the usual adult screening range"
    else:
        category = "well above the usual adult screening range"
    basis = "Asian-population" if asian else "standard WHO"
    return (f"BMI: {bmi:.1f} ({category}; {basis} cutoffs). Intended for adults 20 and older; it does not account for "
            f"pregnancy, muscle mass, body composition, or clinical context. {DISCLAIMER}")


@_register("HEART score for chest pain in the emergency setting (major adverse cardiac event risk). "
           "Not valid for ST-elevation MI.",
           ("chest pain", "heart score", "acute coronary", "acs", "troponin", "angina", "mace"),
           {"history": "slightly / moderately / highly suspicious",
            "ecg": "normal / nonspecific repolarization / significant ST deviation",
            "age": "Age in years",
            "risk_factors": "Count of risk factors (HTN, hypercholesterolemia, diabetes, obesity, smoking, family history)",
            "troponin_x_uln": "Troponin as a MULTIPLE of the assay's upper limit of normal (2.0 = twice the limit)",
            "known_atherosclerotic_disease": "Prior MI, PCI/CABG, stroke/TIA or peripheral arterial disease"})
def calculate_heart_score(history: str, ecg: str, age: int, risk_factors: int, troponin_x_uln: float,
                          known_atherosclerotic_disease: bool = False) -> str:
    h = _choice(history, "history", {"slightly suspicious": 0, "slight": 0, "low": 0,
                                    "moderately suspicious": 1, "moderate": 1,
                                    "highly suspicious": 2, "high": 2})
    e = _choice(ecg, "ecg", {"normal": 0, "nonspecific repolarization": 1, "nonspecific": 1,
                            "significant st deviation": 2, "significant": 2})
    a = _number(age, "age", 0, 120, integer=True)
    rf = _number(risk_factors, "risk_factors", 0, 20, integer=True)
    tx = _number(troponin_x_uln, "troponin_x_uln", 0, 10_000)
    ascvd = _flag(known_atherosclerotic_disease, "known_atherosclerotic_disease")
    a_pts = 2 if a >= 65 else 1 if a >= 45 else 0
    rf_pts = 2 if (rf >= 3 or ascvd) else 1 if rf >= 1 else 0
    t_pts = 2 if tx > 3 else 1 if tx > 1 else 0
    score = h + e + a_pts + rf_pts + t_pts
    tier = "Low (0-3)" if score <= 3 else "Moderate (4-6)" if score <= 6 else "High (7-10)"
    return (f"HEART score: {score}/10 [history {h}, ECG {e}, age {a_pts}, risk factors {rf_pts}, troponin {t_pts}]. "
            f"Risk tier: {tier}. Troponin points assume the value is relative to the assay's upper limit of normal. "
            f"Not for ST-elevation MI; ongoing chest pain needs clinician evaluation regardless of score. {DISCLAIMER}")


@_register("qSOFA bedside screen for risk of poor outcome in suspected infection/sepsis.",
           ("sepsis", "qsofa", "infection", "respiratory rate", "hypotension", "altered mentation", "gcs"),
           {"respiratory_rate": "Breaths per minute", "systolic_bp": "Systolic BP mmHg",
            "gcs": "Glasgow Coma Scale (3-15)"})
def calculate_qsofa(respiratory_rate: int, systolic_bp: int, gcs: int) -> str:
    rr = _number(respiratory_rate, "respiratory_rate", 1, 80)
    sbp = _number(systolic_bp, "systolic_bp", 20, 300)
    g = _number(gcs, "gcs", 3, 15, integer=True)
    score = int(rr >= 22) + int(sbp <= 100) + int(g < 15)
    if score >= 2:
        msg = "Score >=2: higher risk of poor outcome; urgent clinical evaluation for sepsis/organ dysfunction is needed."
    else:
        msg = "Score <2 does NOT rule out sepsis; qSOFA is a prompt, not a diagnostic test."
    return f"qSOFA: {score}/3 (RR>=22, SBP<=100, GCS<15). {msg} {DISCLAIMER}"


@_register("CURB-65 severity score for community-acquired pneumonia.",
           ("pneumonia", "curb-65", "curb65", "cough", "lung infection", "community acquired"),
           {"confusion": "New confusion", "urea_mmol_l": "Blood urea in mmol/L (BUN mg/dL x 0.357)",
            "respiratory_rate": "Breaths per minute", "systolic_bp": "Systolic BP mmHg",
            "diastolic_bp": "Diastolic BP mmHg", "age": "Age in years"})
def calculate_curb65(confusion: bool, urea_mmol_l: float, respiratory_rate: int,
                     systolic_bp: int, diastolic_bp: int, age: int) -> str:
    c = _flag(confusion, "confusion")
    u = _number(urea_mmol_l, "urea_mmol_l", 0, 100)
    rr = _number(respiratory_rate, "respiratory_rate", 1, 80)
    sbp = _number(systolic_bp, "systolic_bp", 20, 300)
    dbp = _number(diastolic_bp, "diastolic_bp", 10, 200)
    a = _number(age, "age", 0, 120, integer=True)
    score = int(c) + int(u > 7) + int(rr >= 30) + int(sbp < 90 or dbp <= 60) + int(a >= 65)
    tier = ("low severity (clinicians often consider outpatient care)" if score <= 1 else
            "intermediate severity (clinicians often consider hospital assessment)" if score == 2 else
            "high severity (urgent hospital care; ICU assessment if 4-5)")
    return f"CURB-65: {score}/5 — {tier}. Clinical judgment and social factors also drive disposition. {DISCLAIMER}"


@_register("CHA2DS2-VASc stroke-risk score in atrial fibrillation.",
           ("atrial fibrillation", "afib", "af", "stroke", "anticoagulation", "cha2ds2", "palpitations"),
           {"chf": "Heart failure / LV dysfunction", "hypertension": "Hypertension", "age": "Age in years",
            "diabetes": "Diabetes", "stroke_tia_thromboembolism": "Prior stroke, TIA or thromboembolism",
            "vascular_disease": "Prior MI, peripheral artery disease or aortic plaque", "female": "Female sex"})
def calculate_cha2ds2_vasc(chf: bool, hypertension: bool, age: int, diabetes: bool,
                           stroke_tia_thromboembolism: bool, vascular_disease: bool, female: bool) -> str:
    a = _number(age, "age", 0, 120, integer=True)
    score = (int(_flag(chf, "chf")) + int(_flag(hypertension, "hypertension"))
             + (2 if a >= 75 else 1 if a >= 65 else 0)
             + int(_flag(diabetes, "diabetes"))
             + 2 * int(_flag(stroke_tia_thromboembolism, "stroke_tia_thromboembolism"))
             + int(_flag(vascular_disease, "vascular_disease")) + int(_flag(female, "female")))
    return (f"CHA2DS2-VASc: {score}/9. Guidelines differ on the score at which anticoagulation is recommended "
            f"(and on how sex counts); the decision rests with the treating clinician. {DISCLAIMER}")


@_register("Wells criteria for pulmonary embolism pre-test probability.",
           ("pulmonary embolism", "pe", "wells", "shortness of breath", "dvt", "leg swelling", "hemoptysis", "d-dimer"),
           {"dvt_signs": "Clinical signs/symptoms of DVT", "pe_most_likely": "PE is the most likely diagnosis",
            "heart_rate_over_100": "Heart rate >100",
            "immobilization_or_surgery": "Immobilization >=3 days or surgery in prior 4 weeks",
            "previous_pe_dvt": "Previous PE or DVT", "hemoptysis": "Hemoptysis",
            "malignancy": "Active cancer (treated within 6 months or palliative)"})
def calculate_wells_pe(dvt_signs: bool, pe_most_likely: bool, heart_rate_over_100: bool,
                       immobilization_or_surgery: bool, previous_pe_dvt: bool, hemoptysis: bool,
                       malignancy: bool) -> str:
    score = (3.0 * _flag(dvt_signs, "dvt_signs") + 3.0 * _flag(pe_most_likely, "pe_most_likely")
             + 1.5 * _flag(heart_rate_over_100, "heart_rate_over_100")
             + 1.5 * _flag(immobilization_or_surgery, "immobilization_or_surgery")
             + 1.5 * _flag(previous_pe_dvt, "previous_pe_dvt") + 1.0 * _flag(hemoptysis, "hemoptysis")
             + 1.0 * _flag(malignancy, "malignancy"))
    three = "low" if score < 2 else "moderate" if score <= 6 else "high"
    two = "PE unlikely" if score <= 4 else "PE likely"
    return (f"Wells (PE): {score:g}. Three-tier: {three}; two-tier: {two}. Sudden breathlessness or chest pain "
            f"needs prompt clinical assessment. {DISCLAIMER}")


@_register("eGFR by the CKD-EPI 2021 (race-free) creatinine equation, adults 18+.",
           ("kidney", "renal", "creatinine", "egfr", "gfr", "ckd"),
           {"creatinine_mg_dl": "Serum creatinine in mg/dL (umol/L / 88.4)", "age": "Age in years (18+)",
            "female": "Female sex"})
def calculate_egfr_ckd_epi(creatinine_mg_dl: float, age: int, female: bool) -> str:
    scr = _number(creatinine_mg_dl, "creatinine_mg_dl", 0.1, 30)
    a = _number(age, "age", 18, 120, integer=True)
    f = _flag(female, "female")
    kappa, alpha = (0.7, -0.241) if f else (0.9, -0.302)
    egfr = 142 * min(scr / kappa, 1) ** alpha * max(scr / kappa, 1) ** -1.200 * 0.9938 ** a * (1.012 if f else 1.0)
    stage = ("G1" if egfr >= 90 else "G2" if egfr >= 60 else "G3a" if egfr >= 45 else
             "G3b" if egfr >= 30 else "G4" if egfr >= 15 else "G5")
    return (f"eGFR (CKD-EPI 2021): {egfr:.0f} mL/min/1.73 m² (GFR category {stage} if persistent >3 months). "
            f"Unreliable in acute kidney injury, extremes of muscle mass, pregnancy or dialysis. {DISCLAIMER}")


@_register("Mean arterial pressure from systolic and diastolic BP.",
           ("blood pressure", "map", "mean arterial", "hypotension", "shock"),
           {"systolic_bp": "Systolic BP mmHg", "diastolic_bp": "Diastolic BP mmHg"})
def calculate_map(systolic_bp: float, diastolic_bp: float) -> str:
    s = _number(systolic_bp, "systolic_bp", 20, 300)
    d = _number(diastolic_bp, "diastolic_bp", 10, 200)
    if d > s:
        raise InputError("diastolic_bp cannot exceed systolic_bp.")
    return f"MAP: {(s + 2 * d) / 3:.0f} mmHg. Targets depend on the clinical context. {DISCLAIMER}"


@_register("Serum anion gap (Na - Cl - HCO3).",
           ("anion gap", "acidosis", "metabolic", "electrolytes", "sodium", "chloride", "bicarbonate"),
           {"sodium": "Na mmol/L", "chloride": "Cl mmol/L", "bicarbonate": "HCO3 mmol/L"})
def calculate_anion_gap(sodium: float, chloride: float, bicarbonate: float) -> str:
    na = _number(sodium, "sodium", 90, 200)
    cl = _number(chloride, "chloride", 50, 150)
    hc = _number(bicarbonate, "bicarbonate", 2, 60)
    return (f"Anion gap: {na - cl - hc:.0f} mmol/L (potassium not included). Reference intervals vary by "
            f"laboratory and analyser; compare with the lab's own range. {DISCLAIMER}")


@_register("Albumin-corrected calcium.",
           ("calcium", "albumin", "hypercalcemia", "hypocalcemia"),
           {"calcium_mg_dl": "Total calcium mg/dL", "albumin_g_dl": "Albumin g/dL"})
def calculate_corrected_calcium(calcium_mg_dl: float, albumin_g_dl: float) -> str:
    ca = _number(calcium_mg_dl, "calcium_mg_dl", 3, 20)
    alb = _number(albumin_g_dl, "albumin_g_dl", 0.5, 7)
    return (f"Corrected calcium: {ca + 0.8 * (4.0 - alb):.1f} mg/dL. The correction is approximate and unreliable in "
            f"critical illness; ionized calcium is the direct measure. {DISCLAIMER}")


@_register("Crude metabolic-risk screen from BMI, diabetes and hypertension flags.",
           ("metabolic", "diabetes", "hypertension", "obesity", "prediabetes"),
           {"weight_kg": "Weight in kilograms", "height_m": "Height in metres", "has_diabetes": "Diagnosed diabetes",
            "has_hypertension": "Diagnosed hypertension",
            "asian_cutoffs": "Use Asian-population obesity cutoff (BMI >=25)"})
def assess_metabolic_risk(weight_kg: float, height_m: float, has_diabetes: bool, has_hypertension: bool,
                          asian_cutoffs: bool = False) -> str:
    w = _number(weight_kg, "weight_kg", 1, 1000)
    h = _number(height_m, "height_m", 0.3, 3)
    bmi = w / (h * h)
    cutoff = 25.0 if _flag(asian_cutoffs, "asian_cutoffs") else 30.0
    flags = []
    if bmi >= cutoff:
        flags.append(f"Obesity (BMI >= {cutoff:g})")
    if _flag(has_diabetes, "has_diabetes"):
        flags.append("Diabetes")
    if _flag(has_hypertension, "has_hypertension"):
        flags.append("Hypertension")
    if len(flags) >= 2:
        return (f"Multiple cardiometabolic risk flags: {', '.join(flags)}. BMI {bmi:.1f}. "
                f"Discuss a full assessment with a clinician. {DISCLAIMER}")
    return (f"BMI {bmi:.1f}. Flags: {', '.join(flags) if flags else 'none'}. This crude screen ignores age, lipids, "
            f"glucose, family history and smoking. {DISCLAIMER}")


# --------------------------------------------------------------------------------------
# Symptom red flags (deterministic phrase matching; deliberately errs toward alerting)
# --------------------------------------------------------------------------------------
_RED_FLAGS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("chest pain", "chest pressure", "chest tightness", "chest feels heavy", "crushing chest"),
     "Chest symptoms can be a heart emergency."),
    (("difficulty breathing", "trouble breathing", "shortness of breath", "can't breathe", "cannot breathe",
      "gasping for air", "breathless", "unable to speak because of breathing"),
     "Breathing difficulty can be urgent."),
    (("face drooping", "facial droop", "one-sided weakness", "arm weakness", "slurred speech", "speech difficulty",
      "sudden numbness", "sudden confusion", "sudden vision loss"),
     "Possible stroke warning sign."),
    (("unconscious", "unresponsive", "not waking", "passed out", "seizure", "convulsion"),
     "Possible emergency involving consciousness or seizure."),
    (("severe bleeding", "bleeding heavily", "won't stop bleeding", "cannot stop bleeding", "vomiting blood",
      "coughing up blood", "blood in vomit"),
     "Possible serious bleeding."),
    (("throat swelling", "tongue swelling", "swollen tongue", "anaphylaxis"),
     "Possible severe allergic reaction."),
    (("worst headache of my life", "thunderclap headache", "sudden severe headache"),
     "Sudden severe headache can signal a brain emergency."),
    (("overdose", "swallowed poison", "poisoning", "took too many"),
     "Possible overdose or poisoning."),
)
_CRISIS = ("suicid", "kill myself", "end my life", "want to die", "self-harm", "self harm", "hurt myself")


def check_symptom_red_flags(symptoms: str) -> str:
    """Phrase matching only; not triage. Negations ('no chest pain') are NOT interpreted."""
    if not isinstance(symptoms, str) or not symptoms.strip():
        return f"Describe the symptoms in plain text. {DISCLAIMER}"
    if len(symptoms) > 5000:
        return f"Input is too long; limit it to 5,000 characters. {DISCLAIMER}"
    text = re.sub(r"\s+", " ", symptoms.casefold().replace("’", "'"))
    if any(t in text for t in _CRISIS):
        return ("If you may harm yourself or are in crisis, contact your local emergency number or a crisis line now, "
                "or go to the nearest emergency department, and reach out to someone you trust. " + DISCLAIMER)
    alerts = [msg for terms, msg in _RED_FLAGS if any(t in text for t in terms)]
    if alerts:
        return ("EMERGENCY WARNING: " + " ".join(alerts) + " Call your local emergency number now or seek emergency "
                "care. Do not wait for this tool. (Phrase match only; negated mentions are not detected.) " + DISCLAIMER)
    return ("No configured red-flag phrase was detected. This does not rule out an emergency and is not a risk "
            "assessment. If symptoms are severe, sudden, worsening, or concerning, contact a clinician or local "
            "emergency service. " + DISCLAIMER)


__all__ = [
    "ALLOWED_ROOTS", "DISCLAIMER", "calculate_bmi", "calculate_heart_score", "calculate_qsofa", "calculate_curb65",
    "calculate_cha2ds2_vasc", "calculate_wells_pe", "calculate_egfr_ckd_epi", "calculate_map", "calculate_anion_gap",
    "calculate_corrected_calcium", "assess_metabolic_risk", "check_symptom_red_flags", "parse_lab_report",
    "parse_lab_text", "list_calculators", "suggest_calculators", "run_calculator", "tool_specs",
]
