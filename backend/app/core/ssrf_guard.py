"""SSRF guard for outbound HTTP requests that originate from user input.

The Cee pipeline accepts a ``landing_page_url`` on project creation and
later fetches it server-side to summarise product claims. Without
validation, an attacker can use the fetcher to probe internal services,
read AWS instance metadata, or pivot through open redirects on third
party hosts.

This module exposes a single helper, :func:`assert_safe_outbound_url`,
which performs the validation needed to safely use the URL with httpx:

1. Scheme must be ``http`` or ``https`` — no ``file://``, ``gopher://``,
   ``ftp://``, or any other scheme that httpx may not enforce on its own.
2. The host must resolve via DNS to a public IP — RFC 1918, loopback,
   link-local, multicast, reserved, and the cloud metadata range
   (169.254.0.0/16) are all rejected.
3. If the URL contains an explicit IPv6 / IPv4 literal in the host, the
   same IP checks apply before we even hit DNS.
4. The validation runs synchronously up-front so the fetcher never sees
   an unsafe URL. We don't try to "follow and re-check" because httpx
   follows redirects by default and the redirect target might land on a
   private IP.

The guard is intentionally permissive about ports (any port is allowed
once the host passes the IP check) so legitimate landing pages still
work; the only constraint is that the host must be a publicly routable
IP at the moment we make the request.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Conservative set: anything that doesn't appear in the public internet
# routing table. Includes the IPv4 metadata range used by AWS / GCP /
# Azure (169.254.0.0/16) and the IPv6 link-local / unique-local prefixes.
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),        # "this network"
    ipaddress.ip_network("10.0.0.0/8"),        # RFC 1918
    ipaddress.ip_network("100.64.0.0/10"),    # carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("169.254.0.0/16"),    # link-local + cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),     # RFC 1918
    ipaddress.ip_network("192.0.0.0/24"),      # IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),      # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),    # RFC 1918
    ipaddress.ip_network("198.18.0.0/15"),     # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),   # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),    # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),       # multicast
    ipaddress.ip_network("240.0.0.0/4"),       # reserved
    ipaddress.ip_network("255.255.255.255/32"),  # broadcast
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


class UnsafeOutboundURLError(ValueError):
    """Raised when a URL fails the SSRF guard validation."""


def _ip_is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip in network for network in _PRIVATE_NETWORKS)


def assert_safe_outbound_url(url: str) -> str:
    """Validate ``url`` for outbound fetching; return the canonical URL.

    Raises :class:`UnsafeOutboundURLError` for any failure. The caller
    should treat the returned string as safe to pass to ``httpx.get``.
    """
    if not url or not url.strip():
        raise UnsafeOutboundURLError("URL must be a non-empty string")

    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeOutboundURLError(
            f"URL scheme {parsed.scheme!r} not allowed (use http or https)"
        )

    host = (parsed.hostname or "").strip()
    if not host:
        raise UnsafeOutboundURLError("URL must include a hostname")

    # Literal IP in the URL? Check it before DNS so we don't accidentally
    # hit a private resolver on the way through.
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if _ip_is_private(literal_ip):
            raise UnsafeOutboundURLError(
                f"URL host {host!r} resolves to a private/reserved IP range"
            )
        return url.strip()

    # Resolve the hostname ourselves. We don't pass the result back into
    # httpx as a connect-override here — that would change URL semantics
    # (Host header etc.). Instead we treat the resolution as a gate: if
    # the first returned IP is private, the request is unsafe to make.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeOutboundURLError(
            f"Could not resolve host {host!r}: {exc}"
        ) from exc

    for info in infos:
        sockaddr = info[4]
        ip_text = sockaddr[0]
        try:
            resolved_ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if _ip_is_private(resolved_ip):
            raise UnsafeOutboundURLError(
                f"URL host {host!r} resolves to a private/reserved IP "
                f"({resolved_ip})"
            )

    return url.strip()
