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
import logging
import os
import re
import socket
import urllib.parse
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

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

# Dunder attributes that are safe and commonly needed
ALLOWED_DUNDERS = frozenset({
    "__init__", "__str__", "__repr__", "__len__",
    "__iter__", "__next__", "__getitem__", "__setitem__",
    "__contains__",
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

        # Block BLOCKED_BUILTINS referenced in ANY context (not just calls)
        if isinstance(node, ast.Name) and node.id in BLOCKED_BUILTINS:
            raise SandboxViolation(f"Reference to blocked builtin '{node.id}' is not allowed")

        # Block assignment to BLOCKED_BUILTINS names (prevents aliasing)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in BLOCKED_BUILTINS:
                    raise SandboxViolation(f"Cannot assign to blocked builtin: {target.id}")

        # Block dangerous builtin calls
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in BLOCKED_BUILTINS:
                raise SandboxViolation(f"Call to '.{func.attr}()' is not allowed")

        # Block dangerous attribute access
        if isinstance(node, ast.Attribute):
            if node.attr in BLOCKED_ATTRS:
                raise SandboxViolation(f"Access to '.{node.attr}' is not allowed")
            # Block all dunder attributes except explicitly allowed ones
            if node.attr.startswith('__') and node.attr.endswith('__'):
                if node.attr not in ALLOWED_DUNDERS:
                    raise SandboxViolation(f"Blocked dunder attribute: {node.attr}")

        # Block string-based code execution patterns
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value.lower()
            if "__import__" in val or "__subclasses__" in val:
                raise SandboxViolation("Suspected code injection in string literal")


def code_run_disabled_response():
    """Error body while untrusted code execution is off, else None.

    The AST blocklist above is defense in depth, not isolation: Python blocklists
    are routinely bypassed, and the code would run as the server user next to its
    secrets and databases. Execution stays off unless an operator opts in with
    CODE_RUN_ENABLED=1, which is only safe inside an isolated sandbox.
    """
    if os.getenv("CODE_RUN_ENABLED") == "1":
        return None
    return {"error": "temporarily_unavailable",
            "message": "Code execution is moving to an isolated sandbox and is not available right now."}


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
    # ::ffff:127.0.0.1 and friends must be judged as the IPv4 address they carry.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if not ip.is_global or ip.is_multicast:
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS)


# ── SSRF-safe HTTP client ─────────────────────────────────────────────
# validate_url() alone is not enough: the HTTP library resolves DNS again when it
# connects (rebinding) and follows redirects without re-checking them. These
# classes vet the address at the moment of connecting, on every hop, and connect
# to exactly the address that was vetted.

import requests as _requests_lib
from requests.adapters import HTTPAdapter as _HTTPAdapter
from urllib3.connection import HTTPConnection as _HTTPConnection, HTTPSConnection as _HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool as _HTTPPool, HTTPSConnectionPool as _HTTPSPool


def _guarded_connect(address, timeout, source_address=None, socket_options=None):
    host, port = address
    try:
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFError(f"DNS resolution failed for {host}") from e
    for *_, sockaddr in infos:
        if _is_blocked_ip(ipaddress.ip_address(sockaddr[0])):
            raise SSRFError(f"{host} resolves to blocked address {sockaddr[0]}")
    err = None
    for family, socktype, proto, _, sockaddr in infos:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            for opt in socket_options or ():
                sock.setsockopt(*opt)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            err = e
            if sock is not None:
                sock.close()
    raise err or OSError(f"Could not connect to {host}")


class _GuardedHTTPConnection(_HTTPConnection):
    def _new_conn(self):
        return _guarded_connect((self._dns_host, self.port), self.timeout, self.source_address, self.socket_options)


class _GuardedHTTPSConnection(_HTTPSConnection):
    def _new_conn(self):
        return _guarded_connect((self._dns_host, self.port), self.timeout, self.source_address, self.socket_options)


class _GuardedHTTPPool(_HTTPPool):
    ConnectionCls = _GuardedHTTPConnection


class _GuardedHTTPSPool(_HTTPSPool):
    ConnectionCls = _GuardedHTTPSConnection


class _GuardedAdapter(_HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _GuardedHTTPPool, "https": _GuardedHTTPSPool}

    def proxy_manager_for(self, *args, **kwargs):
        raise SSRFError("Proxies are not allowed for outbound fetches")


def _check_scheme(url: str, allow_http: bool) -> None:
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in (("http", "https") if allow_http else ("https",)):
        raise SSRFError(f"Scheme '{scheme}' not allowed")


class _GuardedSession(_requests_lib.Session):
    def __init__(self, allow_http: bool):
        super().__init__()
        self.trust_env = False  # ignore HTTP(S)_PROXY and .netrc from the server environment
        self.max_redirects = 5
        self._allow_http = allow_http
        adapter = _GuardedAdapter(max_retries=0)
        self.mount("http://", adapter)
        self.mount("https://", adapter)

    def get_redirect_target(self, resp):
        target = super().get_redirect_target(resp)
        if target:
            _check_scheme(urllib.parse.urljoin(resp.url, target), self._allow_http)
        return target


class _GuardedClient:
    """Drop-in for the `requests` module (get/post/head/request) that refuses
    private, loopback, link-local and metadata addresses. Raises SSRFError."""

    def __getattr__(self, name):
        return getattr(_requests_lib, name)  # exceptions, utils, codes, ...

    def request(self, method, url, allow_http=True, **kwargs):
        _check_scheme(url, allow_http)
        kwargs.setdefault("timeout", 15)
        with _GuardedSession(allow_http) as s:
            return s.request(method, url, **kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def head(self, url, **kwargs):
        kwargs.setdefault("allow_redirects", False)  # same default as requests.head
        return self.request("HEAD", url, **kwargs)


guarded_http = _GuardedClient()


def safe_fetch(url: str, headers: dict = None, timeout: int = 15,
               method: str = "GET", data: bytes = None,
               user_agent: str = "AiPayGen/2.0",
               max_size: int = 100000, allow_http: bool = False) -> dict:
    """SSRF-safe URL fetch, including redirects. Never raises."""
    hdrs = {"User-Agent": user_agent}
    if headers:
        hdrs.update(headers)

    try:
        resp = guarded_http.request(method, url, allow_http=allow_http, headers=hdrs,
                                    data=data, timeout=timeout, stream=True)
    except SSRFError as e:
        return {"error": f"SSRF blocked: {e}", "blocked": True}
    except Exception as e:
        logger.error("Safe fetch failed for %s: %s", url, e)
        return {"error": "Fetch failed"}
    try:
        raw = resp.raw.read(max_size if resp.status_code < 400 else 2000, decode_content=True)
        body = raw.decode(resp.encoding or "utf-8", errors="replace")
    except Exception as e:
        logger.error("Safe fetch read failed for %s: %s", url, e)
        return {"error": "Fetch failed"}
    finally:
        resp.close()
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}", "status": resp.status_code, "body": body}
    return {"status": resp.status_code, "body": body, "headers": dict(resp.headers)}


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
