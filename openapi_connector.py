"""Opt-in OpenAPI client with host allowlisting and bounded requests.

Specs are held in memory only. Remote hosts must be listed in
BERU_API_ALLOWED_HOSTS (comma-separated exact DNS names). File specs must live
inside the project or workspace. API response bodies are truncated.
"""
from __future__ import annotations

import ipaddress
import hashlib
import json
import os
import re
import socket
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import requests

from config import BASE_DIR, WORKSPACE_DIR

_lock = RLock()
_specs: dict[str, dict[str, Any]] = {}
_MAX_SPEC_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024
_METHODS = {"get", "post", "put", "patch", "delete"}
_SAFE_HEADERS = {"accept", "content-type", "if-match", "if-none-match", "prefer", "authorization", "x-api-key"}
_ENV_HEADER = re.compile(r"^\$\{ENV:([A-Za-z_][A-Za-z0-9_]*)\}$")


def _allowed_host(host: str) -> bool:
    allowed = {item.strip().lower().rstrip(".") for item in os.getenv("BERU_API_ALLOWED_HOSTS", "").split(",") if item.strip()}
    return host.lower().rstrip(".") in allowed


def _validate_url(raw: str, *, require_allowlist: bool = True) -> str:
    parts = urlsplit(raw)
    allow_http = os.getenv("BERU_API_ALLOW_HTTP", "").lower() in {"1", "true", "yes"}
    if parts.scheme not in ({"https", "http"} if allow_http else {"https"}) or not parts.hostname:
        raise ValueError("Only HTTPS API URLs with a hostname are allowed (HTTP requires BERU_API_ALLOW_HTTP=1).")
    if parts.username or parts.password or parts.fragment:
        raise ValueError("URLs must not contain embedded credentials or fragments.")
    if parts.query:
        raise ValueError("API base/server URLs must not contain query strings; use configured parameters instead.")
    if parts.port not in (None, 443) and parts.scheme == "https" and not _allowed_host(parts.hostname):
        raise ValueError("Non-standard ports require the exact host in BERU_API_ALLOWED_HOSTS.")
    if require_allowlist and not _allowed_host(parts.hostname):
        raise ValueError("Host is not allowed. Add its exact DNS name to BERU_API_ALLOWED_HOSTS after reviewing it.")
    # Reject literal IPs for a safer default; enterprise internal DNS names can be explicitly allowlisted.
    try:
        ipaddress.ip_address(parts.hostname)
        if not _allowed_host(parts.hostname):
            raise ValueError("Literal IP hosts must be explicitly allowlisted.")
    except ValueError as exc:
        if "explicitly allowlisted" in str(exc):
            raise
    return raw.rstrip("/")


def _read_spec(location: str) -> tuple[dict[str, Any], str]:
    if location.startswith(("https://", "http://")):
        url = _validate_url(location)
        response = requests.get(url, timeout=(4, 12), allow_redirects=False, stream=True,
                                headers={"Accept": "application/json, application/yaml, text/yaml"})
        try:
            response.raise_for_status()
            raw = response.raw.read(_MAX_SPEC_BYTES + 1, decode_content=True)
            if len(raw) > _MAX_SPEC_BYTES:
                raise ValueError("OpenAPI specification exceeds 2 MiB.")
            base = url
        finally:
            response.close()
    else:
        candidate = Path(location).expanduser().resolve(strict=True)
        roots = [Path(BASE_DIR).resolve(), Path(WORKSPACE_DIR).resolve()]
        if not any(candidate == root or root in candidate.parents for root in roots):
            raise ValueError("Local specification must be inside the project folder or workspace.")
        if not candidate.is_file() or candidate.stat().st_size > _MAX_SPEC_BYTES:
            raise ValueError("Specification must be a regular file no larger than 2 MiB.")
        raw = candidate.read_bytes()
        base = str(candidate)
    text = raw.decode("utf-8-sig")
    try:
        spec = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
            spec = yaml.safe_load(text)
        except ImportError as exc:
            raise ValueError("This appears to be YAML; install PyYAML to parse YAML specs.") from exc
    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3."):
        raise ValueError("Expected a valid OpenAPI 3.x document.")
    return spec, base


def _schema_for(value: Any, depth: int = 0, definitions: dict[str, Any] | None = None,
                visited: frozenset[str] = frozenset()) -> dict[str, Any]:
    if depth > 5 or not isinstance(value, dict):
        return {"type": "string"}
    ref = value.get("$ref")
    if ref is not None:
        prefix = "#/components/schemas/"
        if not isinstance(ref, str) or not ref.startswith(prefix):
            return {"type": "string", "description": "Unsupported or external schema reference omitted."}
        name = ref[len(prefix):].replace("~1", "/").replace("~0", "~")
        if name in visited or not isinstance(definitions, dict) or name not in definitions:
            return {"type": "object", "description": "Recursive or unresolved local schema reference."}
        return _schema_for(definitions[name], depth + 1, definitions, visited | {name})
    typ = value.get("type", "string")
    if typ not in {"string", "number", "integer", "boolean", "array", "object"}:
        typ = "string"
    out: dict[str, Any] = {"type": typ}
    for key in ("description", "enum", "format", "minimum", "maximum", "minLength", "maxLength"):
        if key in value and isinstance(value[key], (str, int, float, list)):
            out[key] = value[key]
    if typ == "array":
        out["items"] = _schema_for(value.get("items", {}), depth + 1, definitions, visited)
    if typ == "object":
        props = value.get("properties", {})
        out["properties"] = {str(k): _schema_for(v, depth + 1, definitions, visited) for k, v in list(props.items())[:100] if isinstance(k, str)} if isinstance(props, dict) else {}
        required = value.get("required", [])
        if isinstance(required, list):
            out["required"] = [name for name in required if isinstance(name, str) and name in out["properties"]]
        additional = value.get("additionalProperties", False)
        out["additionalProperties"] = _schema_for(additional, depth + 1, definitions, visited) if isinstance(additional, dict) else bool(additional)
    return out


def _reject_external_refs(value: Any) -> None:
    """Prevent validation or tool construction from dereferencing remote references."""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if ref is not None and (not isinstance(ref, str) or not ref.startswith("#/")):
            raise ValueError("External OpenAPI $ref values are blocked; bundle schemas into the local document first.")
        for child in value.values():
            _reject_external_refs(child)
    elif isinstance(value, list):
        for child in value:
            _reject_external_refs(child)


def ingest_openapi_spec(url_or_file_path: str) -> str:
    """Parse and retain an OpenAPI 3.x spec in memory; return operation schemas for discovery."""
    try:
        spec, source = _read_spec(url_or_file_path.strip())
        _reject_external_refs(spec)
        try:
            from openapi_spec_validator import validate
        except ImportError as exc:
            raise ValueError("Install openapi-spec-validator to validate specifications before use.") from exc
        validate(spec)
        servers = spec.get("servers") or []
        if not servers or not isinstance(servers[0], dict) or not isinstance(servers[0].get("url"), str):
            return "OpenAPI spec needs an explicit servers[0].url; this connector will not guess a target host."
        server = servers[0]["url"]
        if server.startswith("/"):
            if source.startswith(("https://", "http://")):
                server = urljoin(source, server)
            else:
                return "Relative server URLs are unsupported for local specs; add an absolute HTTPS server URL."
        base_url = _validate_url(server)
        operations: dict[tuple[str, str], dict[str, Any]] = {}
        discover = []
        for route, item in spec.get("paths", {}).items():
            if not isinstance(route, str) or not route.startswith("/") or ".." in route:
                continue
            if not isinstance(item, dict):
                continue
            for method, operation in item.items():
                if len(operations) >= 200:
                    break
                method = str(method).lower()
                if method not in _METHODS or not isinstance(operation, dict):
                    continue
                operation_id = str(operation.get("operationId") or f"{method}_{route}")
                inherited = item.get("parameters", [])
                local_parameters = operation.get("parameters", [])
                parameter_map = {}
                for param in (inherited if isinstance(inherited, list) else []) + (local_parameters if isinstance(local_parameters, list) else []):
                    if isinstance(param, dict):
                        parameter_map[(str(param.get("in")), str(param.get("name", "")))] = param
                parameters = list(parameter_map.values())
                path_params, query_params = {}, {}
                required_path, required_query = [], []
                for param in parameters:
                    if not isinstance(param, dict) or param.get("in") not in {"path", "query"}:
                        continue
                    definitions = (spec.get("components") or {}).get("schemas", {})
                    schema = _schema_for(param.get("schema", {}), definitions=definitions)
                    target = path_params if param["in"] == "path" else query_params
                    target[param.get("name", "")] = schema
                    if param.get("required") or param["in"] == "path":
                        (required_path if param["in"] == "path" else required_query).append(param.get("name", ""))
                payload_schema: dict[str, Any] = {"type": "object", "additionalProperties": True}
                body = operation.get("requestBody", {})
                required_payload = bool(body.get("required")) if isinstance(body, dict) else False
                content = body.get("content", {}) if isinstance(body, dict) else {}
                media = content.get("application/json", {}) if isinstance(content, dict) else {}
                if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                    definitions = (spec.get("components") or {}).get("schemas", {})
                    payload_schema = _schema_for(media["schema"], definitions=definitions)
                record = {"operation_id": operation_id, "route": route, "method": method.upper(),
                          "summary": str(operation.get("summary", ""))[:300],
                          "path_params": path_params, "required_path": required_path,
                          "query_params": query_params, "required_query": required_query,
                          "payload_schema": payload_schema, "required_payload": required_payload}
                operations[(method, route)] = record
                discover.append({k: record[k] for k in ("operation_id", "method", "route", "summary", "path_params", "query_params", "payload_schema")})
        if not operations:
            return "No supported HTTP operations were found in this OpenAPI document."
        spec_key = f"{base_url}|{len(operations)}"
        with _lock:
            _specs[spec_key] = {"base_url": base_url, "operations": operations}
        dynamic = get_dynamic_api_schemas()
        short_ops = [{"operation_id": op["operation_id"], "method": op["method"],
                      "route": op["route"], "summary": op["summary"]}
                     for op in discover[:50]]
        return json.dumps({"status": "loaded", "spec_key": spec_key,
                           "note": "Operations are added as dynamic tools for the next BERU request. Start a follow-up message to use them. Mutating methods need BERU_API_ALLOW_WRITE_METHODS=1.",
                           "dynamic_tool_count": len(dynamic),
                           "operations": short_ops}, ensure_ascii=False)
    except Exception as exc:
        return f"OpenAPI ingest failed: {type(exc).__name__}: {exc}"


def execute_api_request(base_url: str, endpoint: str, method: str,
                        headers: dict[str, str] | None = None,
                        payload: dict[str, Any] | list[Any] | None = None,
                        path_params: dict[str, Any] | None = None,
                        query_params: dict[str, Any] | None = None) -> str:
    """Execute a spec-listed API operation on an allowlisted host with bounded I/O."""
    try:
        base = _validate_url(base_url.strip())
        verb = method.strip().lower()
        route = endpoint.strip()
        if verb not in _METHODS or not route.startswith("/") or ".." in route or "?" in route or "#" in route:
            return "Rejected: use a supported method and exact absolute route listed by the ingested spec."
        if verb != "get" and os.getenv("BERU_API_ALLOW_WRITE_METHODS", "").lower() not in {"1", "true", "yes"}:
            return "Rejected: write API calls are disabled. Set BERU_API_ALLOW_WRITE_METHODS=1 after reviewing the target API and credentials."
        with _lock:
            found = next((x for x in _specs.values() if x["base_url"] == base and (verb, route) in x["operations"]), None)
        if not found:
            return "Rejected: this host/route/method has not been ingested from an OpenAPI spec in this process."
        operation = found["operations"][(verb, route)]
        path_values, query_values = path_params or {}, query_params or {}
        if set(path_values) - set(operation["path_params"]) or set(query_values) - set(operation["query_params"]):
            return "Rejected: parameter names must be declared by the OpenAPI operation."
        if any(k not in path_values for k in operation["required_path"]) or any(k not in query_values for k in operation["required_query"]):
            return "Rejected: one or more required OpenAPI parameters are missing."
        if operation.get("required_payload") and payload is None:
            return "Rejected: this operation requires a JSON payload."
        rendered_route = route
        for name, value in path_values.items():
            rendered_route = rendered_route.replace("{" + name + "}", quote(str(value), safe=""))
        if "{" in rendered_route or "}" in rendered_route:
            return "Rejected: path template has unresolved parameters."
        if payload is not None and len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 256_000:
            return "Rejected: JSON request payload exceeds 256 KiB."
        safe_headers = {"Accept": "application/json"}
        for key, value in (headers or {}).items():
            normalized = str(key).lower().strip()
            if normalized not in _SAFE_HEADERS:
                return f"Rejected header '{key}'. This header is not supported by the connector."
            safe_value = str(value)
            env_match = _ENV_HEADER.fullmatch(safe_value)
            if normalized in {"authorization", "x-api-key"} and not env_match:
                return f"Rejected secret header '{key}': use a configured ${{ENV:NAME}} reference, not a literal value."
            if env_match:
                env_name = env_match.group(1)
                safe_value = os.getenv(env_name, "")
                if not safe_value:
                    return f"Rejected: configured environment variable {env_name} is empty or missing."
            if "\r" in safe_value or "\n" in safe_value or len(safe_value) > 2000:
                return "Rejected malformed header value."
            safe_headers[str(key)] = safe_value
        safe_query = dict(query_values)
        for key, value in list(safe_query.items()):
            if re.search(r"(?:token|secret|password|passwd|api[_-]?key|credential)", str(key), re.I):
                env_match = _ENV_HEADER.fullmatch(str(value))
                if not env_match:
                    return f"Rejected sensitive query parameter '{key}': use a configured ${{ENV:NAME}} reference."
                secret = os.getenv(env_match.group(1), "")
                if not secret:
                    return f"Rejected: configured environment variable {env_match.group(1)} is empty or missing."
                safe_query[key] = secret
        target = base + rendered_route
        response = requests.request(verb.upper(), target, params=safe_query, json=payload,
                                    headers=safe_headers, timeout=(4, 15), allow_redirects=False,
                                    stream=True)
        try:
            body = response.raw.read(_MAX_RESPONSE_BYTES + 1, decode_content=True)
            clipped = len(body) > _MAX_RESPONSE_BYTES
            body = body[:_MAX_RESPONSE_BYTES]
            text = body.decode(response.encoding or "utf-8", errors="replace")
            result = {"status_code": response.status_code, "content_type": response.headers.get("Content-Type", ""),
                      "body": text, "truncated": clipped}
            return json.dumps(result, ensure_ascii=False)
        finally:
            response.close()
    except Exception as exc:
        return f"API request failed: {type(exc).__name__}: {exc}"


def get_dynamic_api_schemas() -> list[dict[str, Any]]:
    """Build LLM function schemas for operations loaded in this process."""
    with _lock:
        specs = list(_specs.values())
    output = []
    for spec in specs:
        for (method, route), op in spec["operations"].items():
            digest = hashlib.sha256(f"{spec['base_url']}|{method}|{route}".encode()).hexdigest()[:10]
            name = "apiop_" + digest
            properties: dict[str, Any] = {
                "path_params": {"type": "object", "properties": op["path_params"], "required": op["required_path"], "additionalProperties": False},
                "query_params": {"type": "object", "properties": op["query_params"], "required": op["required_query"], "additionalProperties": False},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}, "description": "Safe headers only; use ${ENV:NAME} for configured environment secrets."},
                "payload": op["payload_schema"],
            }
            output.append({"type": "function", "function": {
                "name": name,
                "description": f"Allowlisted OpenAPI operation {method.upper()} {route}. {op['summary'][:200]} Write methods may be disabled by configuration.",
                "parameters": {"type": "object", "properties": properties,
                               "required": (["path_params"] if op["required_path"] else [])
                                           + (["query_params"] if op["required_query"] else [])
                                           + (["payload"] if op.get("required_payload") else []),
                               "additionalProperties": False},
            }})
    return output


def get_dynamic_api_tools() -> dict[str, Any]:
    """Return closed-over dispatch functions for ingested OpenAPI operations."""
    with _lock:
        specs = list(_specs.values())
    output = {}
    for spec in specs:
        for (method, route), _op in spec["operations"].items():
            digest = hashlib.sha256(f"{spec['base_url']}|{method}|{route}".encode()).hexdigest()[:10]
            name = "apiop_" + digest

            def dispatch(path_params=None, query_params=None, headers=None, payload=None,
                         _base=spec["base_url"], _route=route, _method=method):
                return execute_api_request(_base, _route, _method, headers, payload,
                                          path_params, query_params)

            output[name] = dispatch
    return output
