"""SSRF-resistant outbound transport for local BYOK providers."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import ssl
from typing import Iterable, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

import dns.resolver
import httpcore
import httpx
import rfc3986


class SafeTransportError(RuntimeError):
    """A stable public-safe transport failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AddressResolver(Protocol):
    def resolve(self, hostname: str) -> tuple[str, ...]: ...


class DnsPythonResolver:
    """Resolve all A and AAAA answers without applying address policy."""

    def __init__(self, resolver: dns.resolver.Resolver | None = None) -> None:
        self._resolver = resolver or dns.resolver.Resolver()

    def resolve(self, hostname: str) -> tuple[str, ...]:
        try:
            return (str(ipaddress.ip_address(hostname)),)
        except ValueError:
            pass
        answers: set[str] = set()
        try:
            for record_type in ("A", "AAAA"):
                try:
                    response = self._resolver.resolve(
                        hostname, record_type, search=False, lifetime=5.0
                    )
                except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                    continue
                answers.update(str(item) for item in response)
        except Exception as exc:
            raise SafeTransportError("dns_resolution_failed") from exc
        if not answers:
            raise SafeTransportError("dns_resolution_failed")
        return tuple(sorted(answers))


_METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("fd00:ec2::254"),
}


@dataclass(frozen=True)
class ApprovedEndpoint:
    url: str
    scheme: str
    hostname: str
    port: int
    addresses: tuple[str, ...]


class EndpointPolicy:
    """Normalize endpoints and approve every resolved address."""

    def __init__(
        self,
        *,
        local_endpoint_enabled: bool = False,
        resolver: AddressResolver | None = None,
    ) -> None:
        self.local_endpoint_enabled = local_endpoint_enabled
        self.resolver = resolver or DnsPythonResolver()

    def approve(self, url: str) -> ApprovedEndpoint:
        if not isinstance(url, str) or not url or "\\" in url:
            raise SafeTransportError("invalid_endpoint")
        try:
            normalized = rfc3986.uri_reference(url).normalize().unsplit()
            parsed = urlsplit(normalized)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except Exception as exc:
            raise SafeTransportError("invalid_endpoint") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise SafeTransportError("invalid_endpoint")
        hostname = parsed.hostname.rstrip(".").lower()
        try:
            hostname.encode("ascii")
        except UnicodeEncodeError as exc:
            raise SafeTransportError("invalid_endpoint") from exc
        if self.local_endpoint_enabled:
            if hostname != "localhost":
                try:
                    if not ipaddress.ip_address(hostname).is_loopback:
                        raise SafeTransportError("endpoint_not_allowed")
                except ValueError as exc:
                    raise SafeTransportError("endpoint_not_allowed") from exc
        elif parsed.scheme != "https":
            raise SafeTransportError("https_required")

        raw_addresses = self.resolver.resolve(hostname)
        if not raw_addresses:
            raise SafeTransportError("dns_resolution_failed")
        approved: list[str] = []
        for raw in raw_addresses:
            try:
                address = ipaddress.ip_address(raw)
            except ValueError as exc:
                raise SafeTransportError("dns_resolution_failed") from exc
            if address in _METADATA_ADDRESSES:
                raise SafeTransportError("endpoint_not_allowed")
            allowed = address.is_loopback if self.local_endpoint_enabled else (
                address.is_global
                and not address.is_loopback
                and not address.is_private
                and not address.is_link_local
                and not address.is_multicast
                and not address.is_reserved
                and not address.is_unspecified
            )
            if not allowed:
                raise SafeTransportError("endpoint_not_allowed")
            approved.append(str(address))
        return ApprovedEndpoint(
            url=normalized,
            scheme=parsed.scheme,
            hostname=hostname,
            port=port,
            addresses=tuple(sorted(set(approved))),
        )


class _PolicyNetworkBackend(httpcore.NetworkBackend):
    def __init__(self, policy: EndpointPolicy, scheme: str) -> None:
        self._policy = policy
        self._scheme = scheme
        self._backend = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int | bytes]] | None = None,
    ) -> httpcore.NetworkStream:
        try:
            hostname = host.decode("ascii") if isinstance(host, bytes) else host
            authority = f"[{hostname}]" if ":" in hostname else hostname
            approved = self._policy.approve(
                f"{self._scheme}://{authority}:{port}/"
            )
            last_error: Exception | None = None
            for address in approved.addresses:
                try:
                    return self._backend.connect_tcp(
                        address, port, timeout, local_address, socket_options
                    )
                except Exception as exc:
                    last_error = exc
            raise SafeTransportError("connection_failed") from last_error
        except SafeTransportError:
            raise
        except Exception as exc:
            raise SafeTransportError("connection_failed") from exc


class _ResponseStream(httpx.SyncByteStream):
    def __init__(self, stream: Iterable[bytes]) -> None:
        self._stream = stream

    def __iter__(self):
        yield from self._stream

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()


class _PinnedTransport(httpx.BaseTransport):
    def __init__(self, policy: EndpointPolicy, scheme: str) -> None:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._pool = httpcore.ConnectionPool(
            ssl_context=context,
            proxy=None,
            retries=0,
            network_backend=_PolicyNetworkBackend(policy, scheme),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = self._pool.handle_request(core_request)
        except SafeTransportError:
            raise
        except Exception as exc:
            raise SafeTransportError("request_failed") from exc
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self._pool.close()


class SafeEndpointTransport:
    """HTTPX facade with one endpoint policy and no proxy/redirect fallback."""

    def __init__(
        self,
        base_url: str,
        *,
        local_endpoint_enabled: bool = False,
        resolver: AddressResolver | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._policy = EndpointPolicy(
            local_endpoint_enabled=local_endpoint_enabled, resolver=resolver
        )
        self._endpoint = self._policy.approve(base_url)
        self._client = httpx.Client(
            transport=_PinnedTransport(self._policy, self._endpoint.scheme),
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        credential: str | None = None,
    ) -> httpx.Response:
        if not isinstance(path, str) or urlsplit(path).scheme or urlsplit(path).netloc:
            raise SafeTransportError("invalid_request_path")
        safe_headers = dict(headers or {})
        forbidden = {"authorization", "proxy-authorization", "host"}
        if any(name.lower() in forbidden for name in safe_headers):
            raise SafeTransportError("forbidden_header")
        if credential is not None:
            if not isinstance(credential, str) or not credential:
                raise SafeTransportError("invalid_credential")
            safe_headers["Authorization"] = f"Bearer {credential}"
        target = self._endpoint.url.rstrip("/") + "/" + path.lstrip("/")
        try:
            response = self._client.request(
                method, target, headers=safe_headers, content=content
            )
        except SafeTransportError:
            raise
        except Exception as exc:
            raise SafeTransportError("request_failed") from exc
        if response.is_redirect:
            response.close()
            raise SafeTransportError("redirect_not_allowed")
        return response

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SafeEndpointTransport":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


__all__ = [
    "AddressResolver",
    "ApprovedEndpoint",
    "DnsPythonResolver",
    "EndpointPolicy",
    "SafeEndpointTransport",
    "SafeTransportError",
]
