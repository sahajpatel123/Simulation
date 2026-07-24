"""Integration tests for the SSRF guard wiring into fetch_landing_page_summary.

The fetcher must run :func:`assert_safe_outbound_url` before opening any
connection so a malicious ``landing_page_url`` never reaches ``httpx``.
These tests pin that wiring.
"""

from __future__ import annotations

from unittest.mock import patch

from app.core.intake_processor import fetch_landing_page_summary


class TestSSRFGuardRejectsBeforeNetwork:
    """The fetcher must validate first — httpx must never be called for
    a URL that the guard has rejected."""

    @patch("app.core.intake_processor.httpx.get")
    def test_private_ip_url_never_reaches_httpx(self, mock_get) -> None:
        result = fetch_landing_page_summary("http://127.0.0.1/admin")

        assert "rejected" in result.lower() or "unsafe" in result.lower() or "private" in result.lower()
        mock_get.assert_not_called()

    @patch("app.core.intake_processor.httpx.get")
    def test_aws_metadata_url_never_reaches_httpx(self, mock_get) -> None:
        result = fetch_landing_page_summary(
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/"
        )

        assert "rejected" in result.lower() or "private" in result.lower()
        mock_get.assert_not_called()

    @patch("app.core.intake_processor.httpx.get")
    def test_file_scheme_never_reaches_httpx(self, mock_get) -> None:
        result = fetch_landing_page_summary("file:///etc/passwd")

        assert "rejected" in result.lower() or "scheme" in result.lower()
        mock_get.assert_not_called()

    @patch("app.core.intake_processor.httpx.get")
    def test_gopher_scheme_never_reaches_httpx(self, mock_get) -> None:
        result = fetch_landing_page_summary("gopher://attacker.example/")

        assert "rejected" in result.lower() or "scheme" in result.lower()
        mock_get.assert_not_called()


class TestFetcherStillWorksForSafeURL:
    """A safe URL must still flow through to httpx.get — the guard
    must not be over-eager and block legitimate landing pages."""

    @patch("app.core.intake_processor.httpx.get")
    def test_public_ip_url_is_passed_through(self, mock_get) -> None:
        # Make httpx.get return something the LLM summary path will
        # accept (we patch the summary call to short-circuit so we
        # don't need a real LLM response).
        mock_get.return_value.text = "<html><body>hello</body></html>"
        mock_get.return_value.text = "<html><body>hello</body></html>"

        with patch(
            "app.core.intake_processor.claude_call_with_fallback",
            return_value={"content": "ok", "error": None},
        ):
            result = fetch_landing_page_summary("https://8.8.8.8/")

        mock_get.assert_called_once()
        # The URL passed to httpx must be the validated one, not a
        # mutated IP form (the guard returns the original string).
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://8.8.8.8/"
        assert result == "ok"
