"""SSRF guard: blocked addresses are refused at connect time, on every redirect hop."""
import http.server
import ipaddress
import socket
import threading
from unittest.mock import patch

import pytest

import security
from security import SSRFError, guarded_http, safe_fetch


def _resolve_to(ip):
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host.endswith(".test"):
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
            return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]
        return real(host, port, *args, **kwargs)

    return patch("security.socket.getaddrinfo", side_effect=fake)


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.1.2.3", "172.16.0.5", "192.168.1.1", "169.254.169.254",
    "100.64.0.1", "0.0.0.0", "::1", "fd00::1", "::ffff:127.0.0.1", "::ffff:169.254.169.254",
])
def test_blocked_addresses(ip):
    assert security._is_blocked_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", ["93.184.216.34", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_allowed(ip):
    assert not security._is_blocked_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:7f00:1]/",
])
def test_literal_private_urls_refused(url):
    with pytest.raises(SSRFError):
        guarded_http.get(url)


def test_hostname_resolving_private_is_refused_at_connect():
    # Covers DNS rebinding: the address is checked when the socket is opened.
    with _resolve_to("10.0.0.7"), pytest.raises(SSRFError):
        guarded_http.get("http://rebind.test/")


def test_scheme_restrictions():
    for url in ("file:///etc/passwd", "gopher://x.test/", "ftp://x.test/"):
        with pytest.raises(SSRFError):
            guarded_http.get(url)
    with pytest.raises(SSRFError):
        guarded_http.get("http://example.test/", allow_http=False)


def test_proxies_refused():
    with pytest.raises(SSRFError):
        guarded_http.get("http://example.test/", proxies={"http": "http://proxy.test:8080"})


class _Redirector(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"hello")
            return
        self.send_response(302)
        self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def public_server():
    """A local server the guard treats as public, so redirects out of it can be tested."""
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Redirector)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = security._is_blocked_ip
    allow_loopback = lambda ip: False if str(ip) == "127.0.0.1" else real(ip)  # noqa: E731
    with _resolve_to("127.0.0.1"), patch("security._is_blocked_ip", side_effect=allow_loopback):
        yield f"http://public.test:{srv.server_address[1]}"
    srv.shutdown()


def test_allowed_host_fetches(public_server):
    assert guarded_http.get(public_server + "/ok").text == "hello"
    assert safe_fetch(public_server + "/ok", allow_http=True)["body"] == "hello"


def test_redirect_into_metadata_is_refused(public_server):
    with pytest.raises(SSRFError):
        guarded_http.get(public_server + "/bounce")
    result = safe_fetch(public_server + "/bounce", allow_http=True)
    assert result.get("blocked") is True
