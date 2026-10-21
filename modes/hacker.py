"""
modes/hacker.py - Ethical Security & OSINT Engine for BERU AI AGENT.
Engineered by Navneet Jha.
Maximum Power Level within Authorized Ethical Boundaries.

Provides:
  - Deep DNS & Network Reconnaissance (A, MX, TXT, NS, PTR, ASN)
  - Multi-Threaded Port Scanner with Service Banner Grabbing (timeout=10)
  - HTTP Security Header & Cookie Posture Auditor (CSP, HSTS, CORS)
  - SSL/TLS Certificate & Cipher Inspector (timeout=10)
  - Feature 30: Shodan-Lite Integration (InternetDB API)
  - Feature 31: CVE Lookup by Service & Version
  - Feature 32: Multi-Threaded Subdomain Enumeration
  - Feature 33: Wayback Machine Intel & Archived Endpoints
  - Feature 34: JWT Decoder & Security Posture Auditor
  - Feature 35: Advanced Cookie Security Posture Audit
"""
import base64
import concurrent.futures
import json
import re
import socket
import ssl
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests


# --------------------------------------------------------------------------- #
# Deep DNS & Network Recon
# --------------------------------------------------------------------------- #
def deep_dns_recon(domain_or_ip: str) -> str:
    """
    Performs comprehensive DNS enumeration (A, AAAA, MX, TXT, NS, SOA, PTR)
    using DNS-over-HTTPS (DoH) and local socket lookups with strict timeout=10.
    """
    target = domain_or_ip.strip().lower()
    if target.startswith("http://") or target.startswith("https://"):
        target = urlparse(target).hostname or target

    recon_data: Dict[str, Any] = {"Target": target, "IPs": [], "Reverse_PTR": "", "Records": {}}

    # 1. Resolve IP with socket timeout
    socket.setdefaulttimeout(10.0)
    try:
        ip = socket.gethostbyname(target)
        recon_data["IPs"].append(ip)
        try:
            ptr = socket.gethostbyaddr(ip)[0]
            recon_data["Reverse_PTR"] = ptr
        except Exception:
            recon_data["Reverse_PTR"] = "None"
    except Exception as e:
        return f"Failed: Could not resolve host '{target}': {e}"

    # 2. Query DoH (Cloudflare public resolver) for DNS records
    record_types = ["A", "AAAA", "MX", "TXT", "NS", "SOA"]
    for r_type in record_types:
        try:
            url = f"https://cloudflare-dns.com/dns-query?name={target}&type={r_type}"
            headers = {"Accept": "application/dns-json"}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                answers = res.json().get("Answer", [])
                recon_data["Records"][r_type] = [a.get("data") for a in answers if "data" in a]
        except Exception:
            pass

    # Format Output
    lines = [
        f"--- DNS Reconnaissance: {target} ---",
        f"Primary IP: {', '.join(recon_data['IPs'])}",
        f"Reverse PTR: {recon_data['Reverse_PTR']}",
    ]
    for r_type, values in recon_data["Records"].items():
        if values:
            lines.append(f"[{r_type} Records]:")
            for v in values[:6]:
                lines.append(f"  • {v}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Multi-Threaded Port Scanner & Banner Grabber
# --------------------------------------------------------------------------- #
COMMON_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 445: "SMB",
    1433: "MSSQL", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    6379: "Redis", 8080: "HTTP-Proxy", 8443: "HTTPS-Alt", 27017: "MongoDB"
}

def _probe_port(ip: str, port: int, service: str) -> Optional[Dict[str, Any]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    try:
        if sock.connect_ex((ip, port)) == 0:
            banner = ""
            try:
                sock.send(b"HEAD / HTTP/1.0\r\n\r\n" if port in (80, 8080) else b"\r\n")
                raw = sock.recv(256)
                banner = raw.decode("utf-8", errors="ignore").strip().splitlines()[0][:80]
            except Exception:
                pass
            return {"port": port, "service": service, "banner": banner}
    except Exception:
        pass
    finally:
        sock.close()
    return None


def audit_ports_and_services(target: str, max_threads: int = 15) -> str:
    """
    Safely scans common ports and captures service version banners.
    Works on localhost, staging, or authorized audit targets with timeout=10.
    """
    clean_target = target.strip()
    if clean_target.startswith("http://") or clean_target.startswith("https://"):
        clean_target = urlparse(clean_target).hostname or clean_target

    socket.setdefaulttimeout(10.0)
    try:
        ip = socket.gethostbyname(clean_target)
    except Exception as e:
        return f"Failed to resolve target '{clean_target}': {e}"

    open_ports = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(_probe_port, ip, p, s) for p, s in COMMON_PORTS.items()]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                open_ports.append(res)

    if not open_ports:
        return f"Scanned {len(COMMON_PORTS)} ports on {clean_target} ({ip}). Zero exposed ports detected."

    open_ports.sort(key=lambda x: x["port"])
    lines = [f"--- Port Audit: {clean_target} ({ip}) ---", f"Exposed Ports ({len(open_ports)}):"]
    for p in open_ports:
        banner_info = f" | Banner: {p['banner']}" if p["banner"] else ""
        lines.append(f"  • Port {p['port']:5d} ({p['service']}) [OPEN]{banner_info}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# HTTP Security Headers
# --------------------------------------------------------------------------- #
def audit_security_headers(url: str) -> str:
    """
    Inspects critical web application security headers:
    HSTS, Content-Security-Policy (CSP), X-Frame-Options, X-Content-Type-Options,
    Referrer-Policy, and Permissions-Policy with timeout=10.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Beru-Security-Engine/2.0"}, allow_redirects=True)
    except Exception as e:
        return f"Failed to query '{url}': {e}"

    headers = resp.headers
    findings = []
    score = 100

    checks = [
        ("Strict-Transport-Security", "Missing HSTS (Strict-Transport-Security) — vulnerable to SSL strip attacks.", 20),
        ("Content-Security-Policy", "Missing Content-Security-Policy (CSP) — vulnerable to Cross-Site Scripting (XSS).", 25),
        ("X-Frame-Options", "Missing X-Frame-Options — vulnerable to Clickjacking.", 15),
        ("X-Content-Type-Options", "Missing X-Content-Type-Options — vulnerable to MIME type sniffing.", 10),
        ("Referrer-Policy", "Missing Referrer-Policy — may leak sensitive URLs in Referer header.", 10),
        ("Permissions-Policy", "Missing Permissions-Policy — device features not restricted.", 5),
    ]

    for header, msg, penalty in checks:
        if header.lower() not in [h.lower() for h in headers.keys()]:
            findings.append(f"❌ [MISSING] {msg}")
            score -= penalty
        else:
            val = next(v for k, v in headers.items() if k.lower() == header.lower())
            findings.append(f"✅ [PRESENT] {header}: `{val[:70]}`")

    score = max(0, score)
    return (
        f"--- HTTP Security Header Audit: {url} ---\n"
        f"Security Posture Score: {score}/100\n"
        + "\n".join(findings)
    )


# --------------------------------------------------------------------------- #
# SSL/TLS Certificate Inspector
# --------------------------------------------------------------------------- #
def inspect_ssl_certificate(hostname: str) -> str:
    """Inspects SSL/TLS certificate validity, issuer, SANs, and expiration with timeout=10."""
    clean = hostname.strip().lower()
    if clean.startswith("https://") or clean.startswith("http://"):
        clean = urlparse(clean).hostname or clean

    context = ssl.create_default_context()
    try:
        with socket.create_connection((clean, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=clean) as ssock:
                cert = ssock.getpeercert()
                cipher = ssock.cipher()
                tls_version = ssock.version()

        if not cert:
            return f"SSL Inspection failed: No peer certificate returned for '{clean}'."

        subject = dict(x[0] for x in cert.get("subject", []))
        issuer = dict(x[0] for x in cert.get("issuer", []))
        not_after = cert.get("notAfter", "")
        sans = [v for k, v in cert.get("subjectAltName", []) if k == "DNS"]

        return (
            f"--- SSL/TLS Audit: {clean} ---\n"
            f"TLS Protocol: {tls_version} | Cipher: {cipher[0]} ({cipher[2]} bits)\n"
            f"Subject CN: {subject.get('commonName', 'N/A')}\n"
            f"Issuer Org: {issuer.get('organizationName', 'N/A')} ({issuer.get('commonName', 'N/A')})\n"
            f"Expires On: {not_after}\n"
            f"Subject Alt Names (SANs): {', '.join(sans[:8]) if sans else 'None'}"
        )
    except Exception as e:
        return f"SSL Inspection failed for '{clean}': {e}"


# --------------------------------------------------------------------------- #
# Feature 30: Shodan-Lite Integration (InternetDB API)
# --------------------------------------------------------------------------- #
def shodan_lite_lookup(target: str) -> str:
    """
    Queries Shodan's free open InternetDB API to discover exposed services,
    open ports, known CVEs, hostnames, and CPEs for any domain or IP without an API key.
    """
    clean = target.strip().lower()
    if clean.startswith(("http://", "https://")):
        clean = urlparse(clean).hostname or clean

    socket.setdefaulttimeout(10.0)
    try:
        ip = socket.gethostbyname(clean)
    except Exception as e:
        return f"Shodan-Lite: Failed to resolve '{clean}': {e}"

    url = f"https://internetdb.shodan.io/{ip}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 404:
            return f"Shodan-Lite: No exposed public records found in InternetDB for {clean} ({ip}). Host appears clean or filtered."
        if resp.status_code != 200:
            return f"Shodan-Lite: Lookup returned HTTP {resp.status_code} for {ip}."

        data = resp.json()
        ports = data.get("ports", [])
        cves = data.get("vulns", [])
        tags = data.get("tags", [])
        hostnames = data.get("hostnames", [])
        cpes = data.get("cpes", [])

        lines = [
            f"🌐 --- Shodan-Lite Intelligence: {clean} ({ip}) ---",
            f"• Exposed Ports ({len(ports)}): {', '.join(map(str, ports)) if ports else 'None'}",
            f"• Detected CVEs ({len(cves)}): {', '.join(cves[:10]) if cves else 'None identified'}",
            f"• Tags / Classifications: {', '.join(tags) if tags else 'None'}",
            f"• Associated Hostnames: {', '.join(hostnames[:5]) if hostnames else 'None'}",
            f"• Common Platform Enumeration (CPEs): {', '.join(cpes[:5]) if cpes else 'None'}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"Shodan-Lite error for '{clean}': {e}"


# --------------------------------------------------------------------------- #
# Feature 31: CVE Lookup by Service
# --------------------------------------------------------------------------- #
def lookup_cves_by_service(service_name: str, version: str = "") -> str:
    """
    Queries public vulnerability databases (CIRCL / NVD) for known CVEs
    associated with a specific service name and software version.
    """
    query = f"{service_name.strip()} {version.strip()}".strip()
    if not query:
        return "CVE Lookup: Please provide a service name."

    url = f"https://cve.circl.lu/api/search/{query.replace(' ', '/')}"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Beru-Security-Engine/2.0"})
        if resp.status_code != 200:
            # Fallback to CIRCL general browse
            fallback_url = f"https://cve.circl.lu/api/browse/{service_name.strip()}"
            resp = requests.get(fallback_url, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("data", []) or data.get("results", [])

            if not items:
                return f"CVE Lookup: No known CVEs found for service '{query}'."

            lines = [f"🛡️ --- CVE Lookup Results for '{query}' (Found {len(items)}) ---"]
            for item in items[:6]:
                if isinstance(item, dict):
                    cve_id = item.get("id", "Unknown CVE")
                    cvss = item.get("cvss", "N/A")
                    summary = item.get("summary", item.get("description", "No summary available."))
                    summary_clean = re.sub(r"\s+", " ", summary)[:120]
                    lines.append(f"• **{cve_id}** [CVSS: {cvss}]\n  {summary_clean}...")
                elif isinstance(item, str):
                    lines.append(f"• **{item}**")

            return "\n".join(lines)
        return f"CVE Lookup: Public database returned status {resp.status_code} for '{query}'."
    except Exception as e:
        return f"CVE Lookup error for '{query}': {e}"


# --------------------------------------------------------------------------- #
# Feature 32: Subdomain Enumeration
# --------------------------------------------------------------------------- #
SUBDOMAIN_WORDLIST = [
    "www", "mail", "ftp", "localhost", "webmail", "smtp", "pop", "ns1", "webdisk",
    "ns2", "cpanel", "whm", "autodiscover", "autoconfig", "m", "imap", "test",
    "ns", "blog", "pop3", "dev", "www2", "admin", "forum", "news", "vpn",
    "ns3", "mail2", "new", "mysql", "old", "lists", "support", "mobile", "mx",
    "static", "docs", "beta", "shop", "sql", "secure", "demo", "cp", "calendar",
    "wiki", "web", "media", "email", "images", "img", "www1", "intranet",
    "portal", "video", "sip", "dns2", "api", "cdn", "stats", "dns1", "ns4",
    "www3", "dns", "search", "staging", "server", "mx1", "chat", "wap", "my",
    "svn", "mail1", "sites", "proxy", "ads", "host", "crm", "cms", "backup",
    "auth", "app", "monitor", "git", "jenkins", "gitlab", "jira", "grafana",
    "kibana", "elastic", "s3", "storage", "login", "sso", "dashboard", "gateway",
    "internal", "corp", "lab", "stage", "qa", "prod", "preview", "status"
]

def _check_subdomain(sub: str, domain: str) -> Optional[str]:
    fqdn = f"{sub}.{domain}"
    try:
        url = f"https://cloudflare-dns.com/dns-query?name={fqdn}&type=A"
        headers = {"Accept": "application/dns-json"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            answers = res.json().get("Answer", [])
            for a in answers:
                if a.get("type") == 1:  # Type A
                    return f"{fqdn} -> {a.get('data')}"
    except Exception:
        pass
    return None


def enumerate_subdomains(domain: str, max_threads: int = 20) -> str:
    """
    Discovers active subdomains for a domain using multi-threaded DoH queries
    and Certificate Transparency logs with timeout=10.
    """
    clean = domain.strip().lower()
    if clean.startswith(("http://", "https://")):
        clean = urlparse(clean).hostname or clean

    found_subs: List[str] = []

    # 1. Certificate Transparency (crt.sh) lookup
    try:
        crt_url = f"https://crt.sh/?q=%.{clean}&output=json"
        res = requests.get(crt_url, timeout=10)
        if res.status_code == 200:
            entries = res.json()
            for entry in entries:
                name_value = entry.get("name_value", "")
                for sub in name_value.split("\n"):
                    sub = sub.strip().lower()
                    if sub.endswith(clean) and "*" not in sub and sub not in found_subs:
                        found_subs.append(sub)
    except Exception:
        pass

    # 2. Multi-threaded wordlist brute force
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(_check_subdomain, sub, clean) for sub in SUBDOMAIN_WORDLIST]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res and res not in found_subs:
                found_subs.append(res)

    if not found_subs:
        return f"Subdomain Enumeration: No active subdomains discovered for '{clean}'."

    lines = [
        f"🔎 --- Subdomain Enumeration for {clean} (Discovered: {len(found_subs)}) ---",
    ]
    for s in sorted(list(set(found_subs)))[:30]:
        lines.append(f"  • {s}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Feature 33: Wayback Machine Intel
# --------------------------------------------------------------------------- #
def query_wayback_intel(domain: str, limit: int = 40) -> str:
    """
    Extracts historical endpoints, forgotten APIs, admin panels, and leaked paths
    from the Wayback Machine (Internet Archive CDX API) with timeout=10.
    """
    clean = domain.strip().lower()
    if clean.startswith(("http://", "https://")):
        clean = urlparse(clean).hostname or clean

    cdx_url = (
        f"https://web.archive.org/cdx/search/cdx?url=*.{clean}/*"
        f"&output=json&fl=original&collapse=urlkey&limit={limit}"
    )

    try:
        resp = requests.get(cdx_url, timeout=10, headers={"User-Agent": "Beru-Security-Engine/2.0"})
        if resp.status_code != 200 or not resp.text.strip():
            return f"Wayback Intel: No archived records found for '{clean}'."

        rows = resp.json()
        if len(rows) <= 1:
            return f"Wayback Intel: Zero archived snapshots available for '{clean}'."

        urls = [r[0] for r in rows[1:] if isinstance(r, list) and r]
        
        # Identify high-value patterns
        endpoints = []
        apis = []
        docs = []

        for u in urls:
            u_low = u.lower()
            if any(k in u_low for k in ["/api/", "v1", "v2", "graphql", "rest"]):
                apis.append(u)
            elif any(k in u_low for k in [".json", ".xml", ".yaml", ".env", ".config", ".sql", ".bak"]):
                docs.append(u)
            else:
                endpoints.append(u)

        lines = [
            f"🕰️ --- Wayback Machine Intelligence: {clean} (Total Analyzed: {len(urls)}) ---",
        ]
        if apis:
            lines.append("📌 [Archived API Endpoints]:")
            for a in apis[:10]:
                lines.append(f"  • {a}")
        if docs:
            lines.append("⚠️ [Archived Sensitive Files / Configs]:")
            for d in docs[:10]:
                lines.append(f"  • {d}")
        if endpoints:
            lines.append("📄 [Historical URL Paths]:")
            for ep in endpoints[:15]:
                lines.append(f"  • {ep}")

        return "\n".join(lines)
    except Exception as e:
        return f"Wayback Intel query failed for '{clean}': {e}"


# --------------------------------------------------------------------------- #
# Feature 34: JWT Decoder & Auditor
# --------------------------------------------------------------------------- #
def audit_jwt_token(token: str) -> str:
    """
    Decodes and audits a JSON Web Token (JWT) for cryptographic and authorization vulnerabilities:
    detects 'alg: none', weak HMAC symmetric algorithms, missing or expired TTLs,
    and exposes decoded header and payload claims.
    """
    clean_token = token.strip()
    parts = clean_token.split(".")
    if len(parts) != 3:
        return "JWT Auditor Error: Invalid JWT format. A valid JWT must contain exactly 3 dot-separated base64 segments."

    def _b64_decode(segment: str) -> Dict[str, Any]:
        # Add padding if necessary
        padded = segment + "=" * (-len(segment) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return json.loads(raw.decode("utf-8", errors="ignore"))

    try:
        header = _b64_decode(parts[0])
        payload = _b64_decode(parts[1])
    except Exception as e:
        return f"JWT Auditor Error: Could not decode token segments: {e}"

    findings = []
    severity = "INFO"

    # 1. Algorithm checks
    alg = header.get("alg", "").lower()
    if alg in ("none", ""):
        findings.append("🚨 [CRITICAL] Token allows algorithm 'none'! Anyone can forge valid signatures.")
        severity = "CRITICAL"
    elif alg in ("hs256", "hs384", "hs512"):
        findings.append("⚠️ [MEDIUM] Token uses symmetric HMAC algorithm. Ensure secret key has >= 256 bits of entropy.")
    elif alg in ("rs256", "es256", "ps256"):
        findings.append("✅ [GOOD] Token uses asymmetric cryptography.")

    # 2. Expiration check
    exp = payload.get("exp")
    if exp is None:
        findings.append("⚠️ [HIGH] Token lacks an expiration claim ('exp'). Token is perpetually valid if intercepted.")
        if severity != "CRITICAL":
            severity = "HIGH"
    else:
        now = time.time()
        if now > exp:
            findings.append(f"ℹ️ [INFO] Token is EXPIRED (Expired at {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(exp))}).")
        else:
            remaining = int(exp - now)
            findings.append(f"✅ [VALID] Token expires in {remaining} seconds ({time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(exp))}).")

    # 3. Check for sensitive claims
    sensitive_keys = ["password", "secret", "private_key", "ssn", "token", "auth"]
    for k in payload.keys():
        if any(s in k.lower() for s in sensitive_keys):
            findings.append(f"⚠️ [HIGH] Potential sensitive data leak in payload key: '{k}'")

    lines = [
        f"🔐 --- JWT Security Audit [Overall Rating: {severity}] ---",
        f"Header: {json.dumps(header)}",
        f"Payload: {json.dumps(payload, indent=2)}",
        "Security Findings:",
    ]
    for f in findings:
        lines.append(f"  {f}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Feature 35: Cookie Posture Audit
# --------------------------------------------------------------------------- #
def audit_cookie_posture(url: str) -> str:
    """
    Examines HTTP response cookies for compliance with modern browser security standards:
    verifies SameSite (Strict/Lax/None), Secure, HttpOnly, and prefix integrity (__Host-, __Secure-).
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Beru-Security-Engine/2.0"}, allow_redirects=True)
    except Exception as e:
        return f"Cookie Audit failed to query '{url}': {e}"

    cookies = resp.cookies
    if not cookies:
        return f"Cookie Posture Audit: Zero cookies set by '{url}'."

    audit_lines = [f"🍪 --- Cookie Security Posture Audit: {url} ({len(cookies)} cookies) ---"]

    for c in cookies:
        cookie_flaws = []
        cookie_goods = []

        # HttpOnly
        if "httponly" in c._rest:
            cookie_goods.append("HttpOnly=True")
        else:
            cookie_flaws.append("Missing HttpOnly (Vulnerable to XSS theft)")

        # Secure
        if c.secure:
            cookie_goods.append("Secure=True")
        else:
            cookie_flaws.append("Missing Secure flag (Transmitted over plaintext HTTP)")

        # SameSite
        samesite = c._rest.get("samesite", "None")
        if str(samesite).lower() in ("strict", "lax"):
            cookie_goods.append(f"SameSite={samesite}")
        else:
            cookie_flaws.append(f"Weak SameSite ({samesite}) - Risk of CSRF")

        # Prefix Check
        if c.name.startswith("__Host-") and (not c.secure or c.path != "/" or c.domain):
            cookie_flaws.append("Invalid __Host- prefix implementation")
        elif c.name.startswith("__Secure-") and not c.secure:
            cookie_flaws.append("Invalid __Secure- prefix (not marked Secure)")

        status = "⚠️ AT RISK" if cookie_flaws else "✅ COMPLIANT"
        audit_lines.append(f"\n• Cookie: `{c.name}` ({status})")
        audit_lines.append(f"  Domain: {c.domain} | Path: {c.path}")
        if cookie_goods:
            audit_lines.append(f"  Guards: {', '.join(cookie_goods)}")
        if cookie_flaws:
            for fl in cookie_flaws:
                audit_lines.append(f"  ❌ Flaw: {fl}")

    return "\n".join(audit_lines)
