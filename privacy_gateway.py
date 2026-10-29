"""Request-scoped PII redaction for BERU provider requests.

This is a best-effort privacy layer, not a guarantee: regex cannot detect every
sensitive value, and network-enabled tools outside this gateway need their own
controls. Token maps live only for the request and are never written to disk.
"""
from __future__ import annotations

import contextvars
import ipaddress
import os
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlsplit

_EMAIL = re.compile(r"(?i)(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+(?![\w.-])")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_WINDOWS_PATH = re.compile(r'''(?i)(?<![\w])(?:"(?:[A-Z]:\\|\\\\[^\\\s]+\\[^\\\s]+\\)[^"]+"|'(?:[A-Z]:\\|\\\\[^\\\s]+\\[^\\\s]+\\)[^']+'|(?:[A-Z]:\\|\\\\[^\\\s]+\\[^\\\s]+\\)[^\s<>|?*"']+)''')
_POSIX_PATH = re.compile(r"(?<![\w:])/(?:Users|home|root|tmp|private|var|mnt|media|workspace|workspaces)/[^\s\"'<>|]+")
_TOKEN = re.compile(r"\[(EMAIL|IP|PATH)_(\d+)\]")


class PrivacyGateway:
    """Scrub common PII from provider payloads and restore it in replies."""

    def __init__(self, *, local_only: bool = False) -> None:
        self.local_only = bool(local_only)
        self._replacement_to_value: Dict[str, str] = {}
        self._value_to_replacement: Dict[tuple[str, str], str] = {}
        self._counters = {"EMAIL": 0, "IP": 0, "PATH": 0}

    def scrub(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text

        def replace(kind: str, value: str) -> str:
            key = (kind, value.casefold() if kind == "EMAIL" else value)
            token = self._value_to_replacement.get(key)
            if token is None:
                self._counters[kind] += 1
                token = f"[{kind}_{self._counters[kind]}]"
                self._value_to_replacement[key] = token
                self._replacement_to_value[token] = value
            return token

        text = _EMAIL.sub(lambda m: replace("EMAIL", m.group(0)), text)

        def valid_ip(match: re.Match[str]) -> str:
            value = match.group(0)
            try:
                ipaddress.IPv4Address(value)
            except ipaddress.AddressValueError:
                return value
            return replace("IP", value)

        text = _IPV4.sub(valid_ip, text)
        text = _WINDOWS_PATH.sub(lambda m: replace("PATH", m.group(0)), text)
        text = _POSIX_PATH.sub(lambda m: replace("PATH", m.group(0)), text)
        return text

    def rehydrate(self, text: str) -> str:
        if not isinstance(text, str) or not text or not self._replacement_to_value:
            return text
        # Replace only exact tokens we issued; unknown or malformed tokens remain literal.
        return _TOKEN.sub(lambda m: self._replacement_to_value.get(m.group(0), m.group(0)), text)

    def scrub_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Copy and recursively scrub provider payloads, including tool arguments.

        Embedded images, audio, files and data URLs are removed because regex
        cannot inspect their contents; this intentionally fails closed.
        """
        attachment_keys = {"image", "image_url", "input_audio", "audio", "file", "video", "data_url"}
        def scrub_value(value: Any, key: str = "") -> Any:
            if key.casefold() in attachment_keys:
                return "[ATTACHMENT OMITTED BY PRIVACY FILTER]"
            if isinstance(value, str):
                if value.lstrip().casefold().startswith(("data:image/", "data:audio/", "data:application/")):
                    return "[ATTACHMENT OMITTED BY PRIVACY FILTER]"
                return self.scrub(value)
            if isinstance(value, list):
                return [scrub_value(item) for item in value]
            if isinstance(value, dict):
                return {str(k): scrub_value(v, str(k)) for k, v in value.items()}
            return value
        return [scrub_value(message) for message in messages]

    def rehydrate_message(self, message: Any) -> Any:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            message.content = self.rehydrate(content)
        for call in getattr(message, "tool_calls", []) or []:
            args = getattr(getattr(call, "function", None), "arguments", None)
            if isinstance(args, str):
                call.function.arguments = self.rehydrate(args)
        return message


_ACTIVE_GATEWAY: contextvars.ContextVar[Optional[PrivacyGateway]] = contextvars.ContextVar(
    "beru_privacy_gateway", default=None
)


@contextmanager
def privacy_context(*, local_only: bool = False) -> Iterator[PrivacyGateway]:
    """Install a request-local gateway; safe across concurrent async contexts."""
    gateway = PrivacyGateway(local_only=local_only)
    token = _ACTIVE_GATEWAY.set(gateway)
    try:
        yield gateway
    finally:
        _ACTIVE_GATEWAY.reset(token)


def current_privacy_gateway() -> Optional[PrivacyGateway]:
    return _ACTIVE_GATEWAY.get()


def is_local_only() -> bool:
    gateway = current_privacy_gateway()
    return bool(gateway and gateway.local_only) or os.getenv("BERU_PRIVACY_MODE", "").strip().casefold() == "local_only"


def local_endpoint_is_loopback(url: str) -> bool:
    """Fail closed unless the configured model endpoint resolves syntactically to loopback."""
    try:
        host = (urlsplit(url).hostname or "").strip("[]").casefold()
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False
