"""Tests for the SSRF guard module."""

from __future__ import annotations

import pytest

from app.core.ssrf_guard import UnsafeOutboundURLError, assert_safe_outbound_url


class TestAllowedSchemes:
    def test_http_is_allowed(self) -> None:
        assert (
            assert_safe_outbound_url("http://example.com/")
            == "http://example.com/"
        )

    def test_https_is_allowed(self) -> None:
        assert (
            assert_safe_outbound_url("https://example.com/page")
            == "https://example.com/page"
        )

    def test_uppercase_scheme_is_allowed(self) -> None:
        assert (
            assert_safe_outbound_url("HTTPS://example.com/page")
            == "HTTPS://example.com/page"
        )


class TestDisallowedSchemes:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://attacker.example/",
            "ftp://example.com/file",
            "javascript:alert(1)",
            "data:text/plain,hello",
            "ldap://internal/",
        ],
    )
    def test_non_http_scheme_is_rejected(self, url: str) -> None:
        with pytest.raises(UnsafeOutboundURLError, match="not allowed"):
            assert_safe_outbound_url(url)

    def test_missing_scheme_is_rejected(self) -> None:
        with pytest.raises(UnsafeOutboundURLError, match="not allowed"):
            assert_safe_outbound_url("example.com/page")


class TestEmptyURL:
    def test_empty_string_is_rejected(self) -> None:
        with pytest.raises(UnsafeOutboundURLError, match="non-empty"):
            assert_safe_outbound_url("")

    def test_whitespace_only_is_rejected(self) -> None:
        with pytest.raises(UnsafeOutboundURLError, match="non-empty"):
            assert_safe_outbound_url("   ")

    def test_missing_hostname_is_rejected(self) -> None:
        with pytest.raises(UnsafeOutboundURLError, match="hostname"):
            assert_safe_outbound_url("https://")


class TestLiteralIPRejection:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://127.0.0.1:8080/admin",
            "http://10.0.0.5/",
            "http://10.255.255.254/",
            "http://172.16.0.1/",
            "http://172.31.255.254/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data/",  # AWS metadata
            "http://0.0.0.0/",
            "http://100.64.0.1/",        # carrier-grade NAT
            "http://192.0.2.1/",          # TEST-NET-1
            "http://198.51.100.1/",       # TEST-NET-2
            "http://203.0.113.1/",        # TEST-NET-3
            "http://224.0.0.1/",          # multicast
            "http://255.255.255.255/",    # broadcast
            "http://[::1]/",              # IPv6 loopback
            "http://[fc00::1]/",          # IPv6 unique-local
            "http://[fe80::1]/",          # IPv6 link-local
        ],
    )
    def test_private_ip_is_rejected(self, url: str) -> None:
        with pytest.raises(UnsafeOutboundURLError, match="private/reserved"):
            assert_safe_outbound_url(url)


class TestLiteralIPAcceptance:
    def test_public_ip_is_accepted(self) -> None:
        # 8.8.8.8 is Google public DNS — must pass.
        assert assert_safe_outbound_url("http://8.8.8.8/") == "http://8.8.8.8/"

    def test_public_ip_with_port_is_accepted(self) -> None:
        assert (
            assert_safe_outbound_url("https://1.1.1.1:443/")
            == "https://1.1.1.1:443/"
        )


class TestHostnameNormalization:
    def test_strips_surrounding_whitespace(self) -> None:
        assert (
            assert_safe_outbound_url("  https://example.com/  ")
            == "https://example.com/"
        )

    def test_uppercases_hostname_for_lookup(self) -> None:
        # EXAMPLE.COM should still resolve as a hostname, not a literal IP.
        # We don't care about the DNS result here — just that the guard
        # treats it as a hostname path, not a literal-IP fast-fail.
        try:
            assert_safe_outbound_url("https://EXAMPLE.COM/")
        except UnsafeOutboundURLError as exc:
            # If the local resolver is unreachable in CI, the hostname
            # lookup will raise. The contract we want to lock here is
            # "uppercase host is treated like any other hostname" — not
            # "resolves successfully in this environment".
            assert "private/reserved" not in str(exc)
