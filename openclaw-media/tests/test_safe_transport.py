from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import httpx
import pytest

import openclaw_media.safe_transport as safe_transport
from openclaw_media import EndpointPolicy, SafeEndpointTransport, SafeTransportError


class FakeResolver:
    def __init__(self, *answers: str) -> None:
        self.answers = answers
        self.calls: list[str] = []

    def resolve(self, hostname: str) -> tuple[str, ...]:
        self.calls.append(hostname)
        return self.answers


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture
def loopback_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_public_https_is_normalized_and_all_addresses_are_ordered() -> None:
    resolver = FakeResolver("2606:4700:4700::1111", "1.1.1.1", "1.1.1.1")
    endpoint = EndpointPolicy(resolver=resolver).approve(
        "HTTPS://Example.COM.:8443/v1/../models"
    )

    assert endpoint.scheme == "https"
    assert endpoint.hostname == "example.com"
    assert endpoint.port == 8443
    assert endpoint.addresses == ("1.1.1.1", "2606:4700:4700::1111")
    assert endpoint.url == "https://example.com.:8443/models"
    assert resolver.calls == ["example.com"]


@pytest.mark.parametrize(
    ("url", "answers", "code"),
    [
        ("ftp://example.com/a", ("1.1.1.1",), "invalid_endpoint"),
        ("https://user:secret@example.com/a", ("1.1.1.1",), "invalid_endpoint"),
        ("https://example.com/a#fragment", ("1.1.1.1",), "invalid_endpoint"),
        ("http://example.com/a", ("1.1.1.1",), "https_required"),
        ("https://example.com/a", ("1.1.1.1", "127.0.0.1"), "endpoint_not_allowed"),
        ("https://example.com/a", ("169.254.169.254",), "endpoint_not_allowed"),
        ("https://example.com/a", ("10.0.0.1",), "endpoint_not_allowed"),
        ("https://example.com/a", ("224.0.0.1",), "endpoint_not_allowed"),
        ("https://example.com/a", ("0.0.0.0",), "endpoint_not_allowed"),
        ("https://example.com/a", ("192.0.2.1",), "endpoint_not_allowed"),
    ],
)
def test_endpoint_negative_matrix(
    url: str, answers: tuple[str, ...], code: str
) -> None:
    with pytest.raises(SafeTransportError) as caught:
        EndpointPolicy(resolver=FakeResolver(*answers)).approve(url)
    assert caught.value.code == code
    assert str(caught.value) == code
    assert "secret" not in repr(caught.value)
    assert url not in repr(caught.value)


def test_local_profile_accepts_only_localhost_or_loopback() -> None:
    policy = EndpointPolicy(
        local_endpoint_enabled=True, resolver=FakeResolver("127.0.0.1")
    )
    assert policy.approve("http://localhost:8080").addresses == ("127.0.0.1",)
    assert policy.approve("http://127.0.0.1:8080").hostname == "127.0.0.1"

    with pytest.raises(SafeTransportError, match="endpoint_not_allowed"):
        policy.approve("http://example.com:8080")


def test_real_loopback_socket_request(loopback_server: ThreadingHTTPServer) -> None:
    base_url = f"http://localhost:{loopback_server.server_port}/api"
    with SafeEndpointTransport(
        base_url,
        local_endpoint_enabled=True,
        resolver=FakeResolver("127.0.0.1"),
    ) as transport:
        response = transport.request("GET", "health")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_https_non_default_port_is_owned_by_approved_scheme(monkeypatch) -> None:
    policy = EndpointPolicy(resolver=FakeResolver("1.1.1.1"))
    backend = safe_transport._PolicyNetworkBackend(policy, "https")
    approved_urls: list[str] = []

    def approve(url: str):
        approved_urls.append(url)
        return safe_transport.ApprovedEndpoint(
            url=url,
            scheme="https",
            hostname="example.com",
            port=8443,
            addresses=("1.1.1.1",),
        )

    monkeypatch.setattr(policy, "approve", approve)
    monkeypatch.setattr(
        backend._backend,
        "connect_tcp",
        lambda *args, **kwargs: object(),
    )
    backend.connect_tcp("example.com", 8443)

    assert approved_urls == ["https://example.com:8443/"]


def test_each_new_connection_reresolves_and_dials_an_approved_ip(monkeypatch) -> None:
    resolver = FakeResolver("1.1.1.1")
    policy = EndpointPolicy(resolver=resolver)
    backend = safe_transport._PolicyNetworkBackend(policy, "https")
    dialed: list[str] = []

    def connect(host: str, *args, **kwargs):
        dialed.append(host)
        return object()

    monkeypatch.setattr(backend._backend, "connect_tcp", connect)
    backend.connect_tcp("example.com", 443)
    resolver.answers = ("2606:4700:4700::1111",)
    backend.connect_tcp("example.com", 443)

    assert resolver.calls == ["example.com", "example.com"]
    assert dialed == ["1.1.1.1", "2606:4700:4700::1111"]


def test_request_rejects_absolute_paths_and_caller_security_headers() -> None:
    transport = SafeEndpointTransport(
        "http://localhost:9",
        local_endpoint_enabled=True,
        resolver=FakeResolver("127.0.0.1"),
    )
    try:
        with pytest.raises(SafeTransportError, match="invalid_request_path"):
            transport.request("GET", "https://attacker.invalid/")
        for header in ("Authorization", "Proxy-Authorization", "Host"):
            with pytest.raises(SafeTransportError, match="forbidden_header"):
                transport.request("GET", "/", headers={header: "top-secret"})
    finally:
        transport.close()


def test_proxy_environment_is_ignored_and_redirect_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://user:proxy-secret@127.0.0.1:1")
    transport = SafeEndpointTransport(
        "https://example.com",
        resolver=FakeResolver("1.1.1.1"),
    )
    request = httpx.Request("GET", "https://example.com/next")
    redirect = httpx.Response(302, headers={"location": "https://other.invalid"}, request=request)
    monkeypatch.setattr(transport._client, "request", lambda *args, **kwargs: redirect)
    try:
        with pytest.raises(SafeTransportError) as caught:
            transport.request("GET", "/next", credential="api-super-secret")
    finally:
        transport.close()
    assert caught.value.code == "redirect_not_allowed"
    assert "secret" not in repr(caught.value)
    assert "example.com" not in repr(caught.value)


def test_backend_and_client_failures_are_sanitized(monkeypatch) -> None:
    transport = SafeEndpointTransport(
        "https://example.com",
        resolver=FakeResolver("1.1.1.1"),
    )

    def fail(*args, **kwargs):
        raise RuntimeError("api-super-secret at https://example.com/private")

    monkeypatch.setattr(transport._client, "request", fail)
    try:
        with pytest.raises(SafeTransportError) as caught:
            transport.request("GET", "/private", credential="api-super-secret")
    finally:
        transport.close()
    assert caught.value.code == "request_failed"
    assert str(caught.value) == "request_failed"
    assert "secret" not in repr(caught.value)
    assert "example.com" not in repr(caught.value)
