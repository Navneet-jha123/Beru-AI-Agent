"""Offline, read-only helpers for static analysis of bytes and PE files.

Nothing here loads, executes, or modifies a target. Findings are indicators for a human
analyst -- never proof of malice or benignity.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_HEX_CHARS = 131_072  # 64 KiB of bytecode
MAX_STRINGS = 1000
MAX_OUTPUT_CHARS = 24_000
HIGH_ENTROPY = 7.2  # section entropy above this often indicates packing/encryption

# If set, only files under these folders can be analysed. Recommended when an LLM picks paths.
ALLOWED_ROOTS: Optional[Tuple[Path, ...]] = None

_API_CATEGORIES: Dict[str, frozenset] = {
    "process injection": frozenset({"CreateRemoteThread", "WriteProcessMemory", "VirtualAllocEx", "NtCreateThreadEx",
                                    "QueueUserAPC", "SetThreadContext", "NtMapViewOfSection", "RtlCreateUserThread"}),
    "anti-debugging": frozenset({"IsDebuggerPresent", "CheckRemoteDebuggerPresent", "NtQueryInformationProcess",
                                 "OutputDebugStringA", "OutputDebugStringW"}),
    "dynamic API resolution": frozenset({"LoadLibraryA", "LoadLibraryW", "GetProcAddress", "LdrGetProcedureAddress"}),
    "network download": frozenset({"URLDownloadToFileA", "URLDownloadToFileW", "InternetOpenA", "InternetOpenW",
                                   "InternetOpenUrlA", "InternetOpenUrlW", "WinHttpOpen", "HttpSendRequestA"}),
    "persistence/registry": frozenset({"RegSetValueExA", "RegSetValueExW", "RegCreateKeyExA", "RegCreateKeyExW",
                                       "CreateServiceA", "CreateServiceW"}),
    "privilege/token": frozenset({"AdjustTokenPrivileges", "OpenProcessToken", "LookupPrivilegeValueA",
                                  "LookupPrivilegeValueW"}),
    "keylogging/hooks": frozenset({"SetWindowsHookExA", "SetWindowsHookExW", "GetAsyncKeyState", "GetKeyState"}),
}
_MACHINES = {0x14C: "x86 (I386)", 0x8664: "x64 (AMD64)", 0x1C0: "ARM", 0x1C4: "ARMv7 Thumb-2",
             0xAA64: "ARM64", 0x200: "IA64"}
_SCN_EXEC, _SCN_WRITE = 0x20000000, 0x80000000
_STANDARD_SECTIONS = {".text", ".data", ".rdata", ".rsrc", ".reloc", ".idata", ".edata", ".pdata", ".bss",
                      ".tls", ".crt", ".didat", "code", "data", "bss", ".xdata", ".gfids", ".00cfg"}


def _regular_file(file_path: str, *, max_bytes: int = MAX_FILE_BYTES) -> Tuple[Optional[Path], Optional[str]]:
    try:
        path = Path(file_path).expanduser().resolve(strict=True)
        if ALLOWED_ROOTS is not None and not any(path.is_relative_to(r) for r in ALLOWED_ROOTS):
            return None, "File is outside the allowed folders."
        if not path.is_file():
            return None, "Path is not a regular file."
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            return None, f"File must be between 1 byte and {max_bytes // (1024 * 1024)} MB."
        return path, None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None, "File could not be accessed. Check path and permissions."


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in Counter(data).values())


def hash_file(file_path: str) -> str:
    """MD5/SHA-1/SHA-256 and overall entropy (streamed; never executes the file)."""
    path, error = _regular_file(file_path)
    if error:
        return f"Hashing failed: {error}"
    md5, sha1, sha256 = hashlib.md5(usedforsecurity=False), hashlib.sha1(usedforsecurity=False), hashlib.sha256()
    counts: Counter = Counter()
    total = 0
    try:
        with path.open("rb") as fh:
            while chunk := fh.read(1024 * 1024):
                md5.update(chunk)
                sha1.update(chunk)
                sha256.update(chunk)
                counts.update(chunk)
                total += len(chunk)
    except OSError:
        return "Hashing failed: file could not be read."
    ent = -sum((c / total) * math.log2(c / total) for c in counts.values())
    return (f"File: {path.name}\nSize: {total} bytes\nMD5: {md5.hexdigest()}\nSHA1: {sha1.hexdigest()}\n"
            f"SHA256: {sha256.hexdigest()}\nEntropy: {ent:.2f}/8.00")


def analyze_pe_header(file_path: str) -> str:
    """Parse PE headers/sections/imports/exports locally; never loads or executes the target."""
    path, error = _regular_file(file_path)
    if error:
        return f"PE analysis failed: {error}"
    try:
        with path.open("rb") as fh:
            if fh.read(2) != b"MZ":
                return "PE analysis failed: file does not start with the MZ signature (not a Windows PE file)."
    except OSError:
        return "PE analysis failed: file could not be read."
    try:
        import pefile
    except ImportError:
        return "PE analysis requires the optional 'pefile' package. Install project requirements first."
    try:
        pe = pefile.PE(str(path), fast_load=True)
        d = pefile.DIRECTORY_ENTRY
        pe.parse_data_directories(directories=[d["IMAGE_DIRECTORY_ENTRY_IMPORT"], d["IMAGE_DIRECTORY_ENTRY_EXPORT"],
                                               d["IMAGE_DIRECTORY_ENTRY_TLS"]])
    except Exception as exc:  # noqa: BLE001
        return f"PE parse failed ({type(exc).__name__}); target was not executed."
    try:
        size = path.stat().st_size
        lines = [f"Static PE report for {path.name} (file was not executed):"]
        fh_ = pe.FILE_HEADER
        machine = getattr(fh_, "Machine", None)
        lines.append(f"Machine: {_MACHINES.get(machine, hex(machine) if machine is not None else 'unknown')}")
        lines.append("Type: " + ("DLL" if pe.is_dll() else "driver" if pe.is_driver() else "EXE" if pe.is_exe() else "unknown"))
        ts = getattr(fh_, "TimeDateStamp", None)
        if ts is not None:
            try:
                when = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            except (OverflowError, OSError, ValueError):
                when = "invalid"
            lines.append(f"Compile timestamp (untrusted; easily forged): {ts} ({when})")
        try:
            lines.append(f"Imphash: {pe.get_imphash() or 'n/a'}")
        except Exception:  # noqa: BLE001
            pass

        findings: List[str] = []
        ep = pe.OPTIONAL_HEADER.AddressOfEntryPoint
        ep_sec = pe.get_section_by_rva(ep) if ep else None
        if ep:
            ep_name = ep_sec.Name.split(b"\0", 1)[0].decode("ascii", "replace") if ep_sec else "outside any section"
            lines.append(f"Entry point RVA: {hex(ep)} (section: {ep_name})")
            if ep_sec is None:
                findings.append("Entry point lies outside all sections")
            elif ep_name.casefold() not in {".text", "code", ".text0"}:
                findings.append(f"Entry point is in non-standard section {ep_name!r}")

        for section in list(pe.sections)[:80]:
            name = bytes(section.Name).split(b"\0", 1)[0].decode("ascii", "replace")
            try:
                ent = section.get_entropy()
            except Exception:  # noqa: BLE001
                ent = 0.0
            flags = section.Characteristics
            perms = ("R" if flags & 0x40000000 else "-") + ("W" if flags & _SCN_WRITE else "-") + ("X" if flags & _SCN_EXEC else "-")
            lines.append(f"Section {name!r}: virtual={section.Misc_VirtualSize}, raw={section.SizeOfRawData}, "
                         f"entropy={ent:.2f}, perms={perms}")
            if flags & _SCN_EXEC and flags & _SCN_WRITE:
                findings.append(f"Section {name!r} is writable and executable")
            if ent >= HIGH_ENTROPY and section.SizeOfRawData > 512:
                findings.append(f"Section {name!r} has high entropy ({ent:.2f}); possible packing/encryption")
            if section.SizeOfRawData == 0 and section.Misc_VirtualSize > 0x1000 and flags & _SCN_EXEC:
                findings.append(f"Section {name!r} is executable with no raw data (runtime-unpacked code?)")
            if name.casefold() not in _STANDARD_SECTIONS:
                findings.append(f"Non-standard section name {name!r} (some packers leave recognisable names)")

        overlay_start = pe.get_overlay_data_start_offset()
        if overlay_start is not None and 0 < overlay_start < size:
            lines.append(f"Overlay: {size - overlay_start} bytes appended after the last section")
        try:
            sec_dir = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
            lines.append("Authenticode signature data: " + ("present (not verified here)" if sec_dir.Size else "absent"))
        except (AttributeError, IndexError):
            pass
        if hasattr(pe, "DIRECTORY_ENTRY_TLS"):
            lines.append("TLS directory present (TLS callbacks run before the entry point; review them)")

        imports: List[str] = []
        by_cat: Dict[str, List[str]] = {}
        total_imports = 0
        for entry in list(getattr(pe, "DIRECTORY_ENTRY_IMPORT", []))[:100]:
            dll = bytes(entry.dll).decode("ascii", "replace")
            imports.append(dll)
            for symbol in list(entry.imports)[:500]:
                total_imports += 1
                if symbol.name:
                    fn = bytes(symbol.name).decode("ascii", "replace")
                    for cat, names in _API_CATEGORIES.items():
                        if fn in names:
                            by_cat.setdefault(cat, []).append(f"{dll}!{fn}")
        lines.append("Imported DLLs: " + (", ".join(imports) if imports else "none detected"))
        if 0 < total_imports < 10:
            findings.append(f"Very few imports ({total_imports}); typical of packed or dynamically-resolving code")
        for cat, apis in by_cat.items():
            lines.append(f"Review imports [{cat}]: {', '.join(sorted(set(apis)))}")

        exports = getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])
        names = [bytes(s.name).decode("ascii", "replace") for s in exports[:200] if s.name]
        if names:
            lines.append(f"Exports ({len(names)} shown, max 200): {', '.join(names[:50])}")

        lines.append("Indicators (heuristics only, not proof of malware):" if findings else
                     "No structural indicators from the checks performed (this does not prove the file is safe).")
        lines.extend(f"  ! {f}" for f in findings)
        return "\n".join(lines)[:MAX_OUTPUT_CHARS]
    finally:
        close = getattr(pe, "close", None)
        if callable(close):
            close()


def extract_strings(file_path: str, min_length: int = 4) -> List[str]:
    """Extract bounded ASCII and UTF-16LE printable runs without executing files."""
    path, error = _regular_file(file_path)
    if error:
        return [f"String extraction failed: {error}"]
    try:
        minimum = int(min_length)
    except (TypeError, ValueError, OverflowError):
        return ["String extraction failed: min_length must be an integer from 4 to 64."]
    if not 4 <= minimum <= 64:
        return ["String extraction failed: min_length must be from 4 to 64."]
    try:
        raw = path.read_bytes()
    except OSError:
        return ["String extraction failed: file could not be read."]
    return _strings_from_bytes(raw, minimum)


def _strings_from_bytes(raw: bytes, minimum: int) -> List[str]:
    n = str(minimum).encode("ascii")
    ascii_runs = re.finditer(rb"[\x20-\x7e]{" + n + rb",}", raw)
    wide_runs = re.finditer(rb"(?:[\x20-\x7e]\x00){" + n + rb",}", raw)
    results: List[str] = []
    seen = set()
    for pattern_iter, codec in ((ascii_runs, "ascii"), (wide_runs, "utf-16le")):
        for m in pattern_iter:
            value = m.group(0).decode(codec, "replace")[:500]
            if value not in seen:
                seen.add(value)
                results.append(value)
                if len(results) >= MAX_STRINGS:
                    break
        if len(results) >= MAX_STRINGS:
            break
    total, output = 0, []
    for value in results:
        if total + len(value) > MAX_OUTPUT_CHARS:
            break
        output.append(value)
        total += len(value)
    return output


_IOC_PATTERNS = {
    "url": re.compile(r"https?://[^\s\"'<>]{4,200}", re.I),
    "ipv4": re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"),
    "registry key": re.compile(r"\b(?:HKEY_[A-Z_]+|HK(?:LM|CU|CR|U))\\[^\s\"']{3,200}", re.I),
    "windows path": re.compile(r"\b[A-Za-z]:\\[^\s\"'<>|*?]{3,200}"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b"),
}


def _defang(value: str) -> str:
    """Make indicators non-clickable/non-resolvable when displayed."""
    return (value.replace("http://", "hxxp://").replace("https://", "hxxps://")
            .replace(".", "[.]") if "://" in value or re.fullmatch(r"[\d.]+", value) else value)


def find_indicators(file_path: str) -> str:
    """Group interesting strings (URLs, IPs, registry keys, paths, emails); output is defanged."""
    strings = extract_strings(file_path, 5)
    if strings and strings[0].startswith("String extraction failed"):
        return strings[0]
    groups: Dict[str, List[str]] = {}
    for s in strings:
        for kind, pat in _IOC_PATTERNS.items():
            for m in pat.finditer(s):
                bucket = groups.setdefault(kind, [])
                v = _defang(m.group(0))
                if v not in bucket and len(bucket) < 50:
                    bucket.append(v)
    if not groups:
        return "No URLs, IPs, registry keys, paths or emails found in extracted strings."
    out = ["Indicators found in strings (defanged; treat as leads, not verdicts):"]
    for kind, vals in groups.items():
        out.append(f"[{kind}]")
        out.extend(f"  {v}" for v in vals)
    return "\n".join(out)[:MAX_OUTPUT_CHARS]


def disassemble_bytes(hex_string: str, architecture: str = "x86", base_address: int = 0) -> str:
    """Disassemble bounded hex bytes in memory; never writes or executes them."""
    if not isinstance(hex_string, str) or not hex_string.strip():
        return "Disassembly failed: provide a non-empty hexadecimal string."
    if len(hex_string) > MAX_HEX_CHARS * 4:  # allow generous formatting overhead before cleaning
        return f"Disassembly failed: input too long (limit 64 KiB of bytes)."
    cleaned = re.sub(r"0x|\\x|[\s,:;]", "", hex_string, flags=re.I)
    if len(cleaned) > MAX_HEX_CHARS:
        return f"Disassembly failed: input exceeds {MAX_HEX_CHARS} hex characters (64 KiB of bytes)."
    try:
        code = bytes.fromhex(cleaned)
    except ValueError:
        return "Disassembly failed: input must contain only valid hexadecimal byte pairs."
    if not code:
        return "Disassembly failed: no bytes were provided."
    try:
        base = int(base_address)
        if not 0 <= base < 2 ** 64:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return "Disassembly failed: base_address must be an integer from 0 to 2^64-1."
    arch_name = (architecture or "x86").strip().casefold()
    try:
        from capstone import (Cs, CS_ARCH_ARM, CS_ARCH_ARM64, CS_ARCH_X86, CS_MODE_32, CS_MODE_64, CS_MODE_ARM,
                              CS_MODE_LITTLE_ENDIAN, CS_MODE_THUMB)
    except ImportError:
        return "Disassembly requires the optional 'capstone' package. Install project requirements first."
    modes = {
        "x86": (CS_ARCH_X86, CS_MODE_32), "x86_32": (CS_ARCH_X86, CS_MODE_32),
        "x64": (CS_ARCH_X86, CS_MODE_64), "x86_64": (CS_ARCH_X86, CS_MODE_64),
        "arm": (CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_LITTLE_ENDIAN),
        "thumb": (CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN),
        "arm64": (CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN), "aarch64": (CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN),
    }
    if arch_name not in modes:
        return "Disassembly failed: architecture must be x86, x64, arm, thumb, or arm64."
    try:
        arch, mode = modes[arch_name]
        engine = Cs(arch, mode)
        rows: List[str] = []
        last_end = 0
        for ins in engine.disasm(code, base, count=4096):
            rows.append(f"{ins.address:08x}: {bytes(ins.bytes).hex():<20} {ins.mnemonic} {ins.op_str}".rstrip())
            last_end = ins.address + ins.size - base
    except Exception as exc:  # noqa: BLE001
        return f"Disassembly failed ({type(exc).__name__})."
    if not rows:
        return "No instructions decoded for these bytes and architecture."
    if last_end < len(code) and len(rows) < 4096:
        rows.append(f"; {len(code) - last_end} trailing byte(s) could not be decoded (data, wrong architecture, or truncated)")
    return "\n".join(rows)[:MAX_OUTPUT_CHARS]


__all__ = ["ALLOWED_ROOTS", "hash_file", "analyze_pe_header", "extract_strings", "find_indicators", "disassemble_bytes"]
