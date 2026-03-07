"""
Enterprise Security Module for AiPayGen

Provides:
- Code sandbox validation (AST-based)
- SSRF-safe URL fetching
- Input sanitization utilities
"""
import ast
import html
import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
import urllib.error

# ── Code Sandbox ───────────────────────────────────────────────────────

# Modules that are NEVER allowed in sandboxed code
BLOCKED_IMPORTS = frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests", "httpx", "aiohttp",
    "ctypes", "cffi", "importlib", "pkgutil",
    "signal", "multiprocessing", "threading",
    "code", "codeop", "compile", "compileall",
    "webbrowser", "antigravity",
    "pty", "fcntl", "termios", "resource",
    "tempfile", "glob", "fnmatch",
    "sqlite3", "dbm",
    "smtplib", "imaplib", "poplib", "ftplib", "telnetlib",
    "xml", "html",
    "builtins", "__builtins__",
    "io",
})

BLOCKED_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__",
    "open", "input", "breakpoint",
    "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr",
    "memoryview", "bytearray",
})

BLOCKED_ATTRS = frozenset({
    "__subclasses__", "__bases__", "__mro__", "__class__",
    "__globals__", "__builtins__", "__code__", "__closure__",
    "__import__", "__loader__", "__spec__",
    "system", "popen", "exec", "spawn",
})


class SandboxViolation(Exception):
    pass


def validate_code_safety(code: str) -> None:
    """AST-based code safety check. Raises SandboxViolation if unsafe."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SandboxViolation(f"Syntax error: {e}")

    for node in ast.walk(tree):
        # Block all imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            else:
                if node.module:
                    names = [node.module.split(".")[0]]
            for name in names:
                if name in BLOCKED_IMPORTS or True:  # Block ALL imports in sandbox
                    raise SandboxViolation(f"Import '{name}' is not allowed")

        # Block dangerous builtin calls
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BLOCKED_BUILTINS:
                raise SandboxViolation(f"Builtin '{func.id}()' is not allowed")
            if isinstance(func, ast.Attribute) and func.attr in BLOCKED_BUILTINS:
                raise SandboxViolation(f"Call to '.{func.attr}()' is not allowed")

        # Block dangerous attribute access
        if isinstance(node, ast.Attribute):
            if node.attr in BLOCKED_ATTRS:
                raise SandboxViolation(f"Access to '.{node.attr}' is not allowed")

        # Block string-based code execution patterns
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value.lower()
            if "__import__" in val or "__subclasses__" in val:
                raise SandboxViolation("Suspected code injection in string literal")


def get_sandbox_env():
    """Return a minimal environment for subprocess code execution."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
    }


# ── SSRF Protection ───────────────────────────────────────────────────

# Private/reserved IP ranges that must never be fetched
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("255.255.255.255/32"),
    # IPv6 private ranges
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


class SSRFError(Exception):
    pass


def validate_url(url: str, allow_http: bool = False) -> str:
    """Validate URL is safe to fetch (no SSRF). Returns the validated URL."""
    if not url or not isinstance(url, str):
        raise SSRFError("Empty or invalid URL")

    parsed = urllib.parse.urlparse(url)

    # Scheme check
    allowed_schemes = {"https"}
    if allow_http:
        allowed_schemes.add("http")
    if parsed.scheme not in allowed_schemes:
        raise SSRFError(f"Scheme '{parsed.scheme}' not allowed (use https)")

    # Host check
    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("No hostname in URL")

    # Block numeric/octal/hex IP bypasses
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_blocked_ip(ip):
            raise SSRFError(f"IP address {ip} is in a blocked range")
    except ValueError:
        pass  # It's a hostname, not an IP — will check after DNS resolution

    # DNS resolution check — verify resolved IPs are not private
    try:
        addrs = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise SSRFError(f"DNS resolution failed for {hostname}")

    for family, _, _, _, sockaddr in addrs:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise SSRFError(f"Resolved IP {ip} for {hostname} is in a blocked range")

    return url


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return True
    return False


def safe_fetch(url: str, headers: dict = None, timeout: int = 15,
               method: str = "GET", data: bytes = None,
               user_agent: str = "AiPayGen/2.0",
               max_size: int = 100000, allow_http: bool = False) -> dict:
    """SSRF-safe URL fetch. Validates URL before fetching."""
    try:
        url = validate_url(url, allow_http=allow_http)
    except SSRFError as e:
        return {"error": f"SSRF blocked: {e}", "blocked": True}

    hdrs = {"User-Agent": user_agent}
    if headers:
        hdrs.update(headers)

    try:
        req = urllib.request.Request(url, headers=hdrs, method=method, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:max_size]
            return {"status": resp.status, "body": body, "headers": dict(resp.headers)}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "status": e.code,
                "body": e.read().decode("utf-8", errors="replace")[:2000]}
    except Exception as e:
        return {"error": str(e)}


# ── Input Sanitization ─────────────────────────────────────────────────

def sanitize_html(text: str) -> str:
    """Escape HTML special characters."""
    return html.escape(str(text), quote=True)


def sanitize_filename(filename: str) -> str:
    """Remove dangerous characters from filenames."""
    filename = re.sub(r'[/\\:\r\n\x00-\x1f]', '', filename)
    return filename[:255]


def validate_redirect_url(url: str) -> str:
    """Ensure redirect URL is a safe relative path. Rejects absolute/protocol-relative URLs."""
    if not url:
        return "/"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme or parsed.netloc:
        return "/"
    if url.startswith("//"):
        return "/"
    if not url.startswith("/"):
        return "/"
    return url


def validate_currency_code(code: str) -> str:
    """Validate 3-letter currency code."""
    if not re.match(r'^[A-Z]{3}$', code.upper()):
        raise ValueError(f"Invalid currency code: {code}")
    return code.upper()
