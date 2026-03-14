"""Extended email service tests — boundary conditions, HTML safety,
argument combinations, and subject line verification."""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# send_api_key_email — additional edge cases
# ---------------------------------------------------------------------------

class TestApiKeyEmailExtended:

    def test_zero_balance_displayed(self):
        from email_service import send_api_key_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_api_key_email("u@x.com", "apk_zero", 0.0)
            assert "$0.00" in mock.call_args[0][0]["html"]

    def test_large_balance_formatted(self):
        from email_service import send_api_key_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_api_key_email("u@x.com", "apk_big", 1234.56)
            assert "$1234.56" in mock.call_args[0][0]["html"]

    def test_api_key_in_curl_example(self):
        from email_service import send_api_key_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_api_key_email("u@x.com", "apk_curl_test", 5.0)
            html = mock.call_args[0][0]["html"]
            assert "Bearer apk_curl_test" in html

    def test_subject_line(self):
        from email_service import send_api_key_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_api_key_email("u@x.com", "apk_x", 1.0)
            assert "API Key" in mock.call_args[0][0]["subject"]

    def test_none_email_still_attempts(self):
        """send_api_key_email does not validate email format — Resend handles it."""
        from email_service import send_api_key_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            result = send_api_key_email(None, "apk_x", 1.0)
            assert result is True  # function doesn't guard against None email


# ---------------------------------------------------------------------------
# send_welcome_email — additional edge cases
# ---------------------------------------------------------------------------

class TestWelcomeEmailExtended:

    def test_curl_example_in_welcome(self):
        from email_service import send_welcome_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_welcome_email("u@x.com", "apk_welcome_curl")
            html = mock.call_args[0][0]["html"]
            assert "Bearer apk_welcome_curl" in html
            assert "summarize" in html

    def test_docs_and_try_links(self):
        from email_service import send_welcome_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_welcome_email("u@x.com", "apk_links")
            html = mock.call_args[0][0]["html"]
            assert "aipaygen.com/docs" in html
            assert "aipaygen.com/try" in html

    def test_whitespace_email_attempts_send(self):
        """Whitespace-only email passes the `if not to` check (truthy string)."""
        from email_service import send_welcome_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            # Whitespace string is truthy, so it passes guard and calls Resend
            result = send_welcome_email("   ", "apk_x")
            assert result is True
            mock.assert_called_once()

    def test_whitespace_key_attempts_send(self):
        from email_service import send_welcome_email
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            result = send_welcome_email("u@x.com", "   ")
            assert result is True


# ---------------------------------------------------------------------------
# send_free_tier_nudge — additional edge cases
# ---------------------------------------------------------------------------

class TestNudgeExtended:

    def test_nudge_pricing_info(self):
        from email_service import send_free_tier_nudge
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_free_tier_nudge("u@x.com", tools_used=3, calls_made=10)
            html = mock.call_args[0][0]["html"]
            assert "$1" in html  # pricing reference
            assert "100" in html  # ~100 API calls

    def test_nudge_subject_line(self):
        from email_service import send_free_tier_nudge
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_free_tier_nudge("u@x.com")
            assert "free" in mock.call_args[0][0]["subject"].lower()

    def test_nudge_buy_credits_link(self):
        from email_service import send_free_tier_nudge
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_free_tier_nudge("u@x.com", calls_made=10)
            html = mock.call_args[0][0]["html"]
            assert "buy-credits" in html

    def test_nudge_zero_stats(self):
        from email_service import send_free_tier_nudge
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            result = send_free_tier_nudge("u@x.com", tools_used=0, calls_made=0)
            assert result is True
            html = mock.call_args[0][0]["html"]
            assert "0" in html


# ---------------------------------------------------------------------------
# send_magic_link — additional edge cases
# ---------------------------------------------------------------------------

class TestMagicLinkExtended:

    def test_magic_link_subject(self):
        from email_service import send_magic_link
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_magic_link("u@x.com", "https://aipaygen.com/auth/verify?t=abc")
            assert "Sign in" in mock.call_args[0][0]["subject"]

    def test_magic_link_expiry_notice(self):
        from email_service import send_magic_link
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_magic_link("u@x.com", "https://link.com/v?t=x")
            html = mock.call_args[0][0]["html"]
            assert "15 minutes" in html

    def test_magic_link_url_in_html(self):
        from email_service import send_magic_link
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            url = "https://aipaygen.com/auth/verify?token=my_secret_token_123"
            send_magic_link("u@x.com", url)
            html = mock.call_args[0][0]["html"]
            assert url in html

    def test_magic_link_from_address(self):
        from email_service import send_magic_link
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_magic_link("u@x.com", "https://link.com")
            assert "noreply@aipaygen.com" in mock.call_args[0][0]["from"]


# ---------------------------------------------------------------------------
# send_deposit_confirmation — additional edge cases
# ---------------------------------------------------------------------------

class TestDepositConfirmationExtended:

    def test_base_network_explorer_link(self):
        from email_service import send_deposit_confirmation
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"email": "u@x.com"}
        with patch("sqlite3.connect", return_value=mock_conn), \
             patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_deposit_confirmation("apk_test", 25.50, "base", "0xabc123")
            html = mock.call_args[0][0]["html"]
            assert "basescan.org/tx/0xabc123" in html
            assert "$25.50" in html

    def test_solana_network_explorer_link(self):
        from email_service import send_deposit_confirmation
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"email": "u@x.com"}
        with patch("sqlite3.connect", return_value=mock_conn), \
             patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_deposit_confirmation("apk_test", 10.0, "solana", "5sig123")
            html = mock.call_args[0][0]["html"]
            assert "solscan.io/tx/5sig123" in html

    def test_subject_includes_amount(self):
        from email_service import send_deposit_confirmation
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"email": "u@x.com"}
        with patch("sqlite3.connect", return_value=mock_conn), \
             patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_deposit_confirmation("apk_test", 42.00, "base", "0xhash")
            subject = mock.call_args[0][0]["subject"]
            assert "$42.00" in subject

    def test_empty_email_field_returns_false(self):
        from email_service import send_deposit_confirmation
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"email": ""}
        with patch("sqlite3.connect", return_value=mock_conn):
            result = send_deposit_confirmation("apk_test", 5.0, "base", "0x1")
            assert result is False


# ---------------------------------------------------------------------------
# send_weekly_digest — additional edge cases
# ---------------------------------------------------------------------------

class TestWeeklyDigestExtended:

    def test_digest_default_values(self):
        from email_service import send_weekly_digest
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_weekly_digest("u@x.com")
            html = mock.call_args[0][0]["html"]
            assert "0" in html  # default calls=0
            assert "$0.00" in html  # default spent=0.0
            assert "None" in html  # no tools

    def test_digest_multiple_tools(self):
        from email_service import send_weekly_digest
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_weekly_digest("u@x.com", top_tools=["research", "summarize", "code"])
            html = mock.call_args[0][0]["html"]
            assert "research" in html
            assert "summarize" in html
            assert "code" in html

    def test_digest_subject_line(self):
        from email_service import send_weekly_digest
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_weekly_digest("u@x.com")
            assert "Weekly" in mock.call_args[0][0]["subject"]

    def test_digest_dashboard_link(self):
        from email_service import send_weekly_digest
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_weekly_digest("u@x.com")
            html = mock.call_args[0][0]["html"]
            assert "aipaygen.com/dashboard" in html

    def test_digest_unsubscribe_includes_email(self):
        from email_service import send_weekly_digest
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_weekly_digest("alice@example.com")
            html = mock.call_args[0][0]["html"]
            assert "alice@example.com" in html
            assert "unsubscribe" in html

    def test_digest_html_escapes_xss_in_tools(self):
        """XSS in tool names must be escaped."""
        from email_service import send_weekly_digest
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_weekly_digest("u@x.com", top_tools=['<img onerror="alert(1)">'])
            html = mock.call_args[0][0]["html"]
            assert "<img" not in html
            assert "&lt;img" in html

    def test_digest_large_numbers(self):
        from email_service import send_weekly_digest
        with patch("email_service.resend.Emails.send") as mock:
            mock.return_value = {"id": "ok"}
            send_weekly_digest("u@x.com", calls=999999, spent=12345.67)
            html = mock.call_args[0][0]["html"]
            assert "999999" in html
            assert "$12345.67" in html
