import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# send_api_key_email
# ---------------------------------------------------------------------------

def test_send_api_key_email():
    from email_service import send_api_key_email
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-123"}
        result = send_api_key_email("user@example.com", "apk_test123", 5.0)
        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["user@example.com"]
        assert "apk_test123" in call_args["html"]

def test_send_api_key_email_no_key():
    from email_service import send_api_key_email
    result = send_api_key_email("user@example.com", "", 5.0)
    assert result is False

def test_send_api_key_email_resend_failure():
    """Resend API raises an exception — should return False gracefully."""
    from email_service import send_api_key_email
    with patch("email_service.resend.Emails.send", side_effect=Exception("API error")):
        result = send_api_key_email("user@example.com", "apk_fail", 10.0)
        assert result is False

def test_send_api_key_email_balance_in_html():
    """Balance amount should appear formatted in the email body."""
    from email_service import send_api_key_email
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "bal-check"}
        send_api_key_email("user@example.com", "apk_bal", 25.50)
        html = mock_send.call_args[0][0]["html"]
        assert "$25.50" in html

def test_send_api_key_email_subject():
    """Subject line should mention API Key."""
    from email_service import send_api_key_email
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "subj-check"}
        send_api_key_email("user@example.com", "apk_subj", 1.0)
        subject = mock_send.call_args[0][0]["subject"]
        assert "API Key" in subject


# ---------------------------------------------------------------------------
# send_welcome_email
# ---------------------------------------------------------------------------

def test_send_welcome_email_success():
    """Happy path — welcome email sent successfully."""
    from email_service import send_welcome_email
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "welcome-ok"}
        result = send_welcome_email("new@example.com", "apk_welcome123")
        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["new@example.com"]
        assert "apk_welcome123" in call_args["html"]

def test_send_welcome_email_empty_to():
    """Empty 'to' should return False without calling Resend."""
    from email_service import send_welcome_email
    with patch("email_service.resend.Emails.send") as mock_send:
        result = send_welcome_email("", "apk_key")
        assert result is False
        mock_send.assert_not_called()

def test_send_welcome_email_empty_api_key():
    """Empty api_key should return False without calling Resend."""
    from email_service import send_welcome_email
    with patch("email_service.resend.Emails.send") as mock_send:
        result = send_welcome_email("user@example.com", "")
        assert result is False
        mock_send.assert_not_called()

def test_send_welcome_email_none_to():
    """None 'to' should return False."""
    from email_service import send_welcome_email
    result = send_welcome_email(None, "apk_key")
    assert result is False

def test_send_welcome_email_none_api_key():
    """None api_key should return False."""
    from email_service import send_welcome_email
    result = send_welcome_email("user@example.com", None)
    assert result is False

def test_send_welcome_email_resend_failure():
    """Resend API raises — should return False gracefully."""
    from email_service import send_welcome_email
    with patch("email_service.resend.Emails.send", side_effect=Exception("timeout")):
        result = send_welcome_email("user@example.com", "apk_fail")
        assert result is False

def test_send_welcome_email_subject():
    """Subject line should mention Welcome and AiPayGen."""
    from email_service import send_welcome_email
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "subj-welcome"}
        send_welcome_email("user@example.com", "apk_subj")
        subject = mock_send.call_args[0][0]["subject"]
        assert "Welcome" in subject
        assert "AiPayGen" in subject

def test_send_welcome_email_contains_docs_and_try_links():
    """Email body should contain links to docs and try-it page."""
    from email_service import send_welcome_email
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "links-check"}
        send_welcome_email("user@example.com", "apk_links")
        html = mock_send.call_args[0][0]["html"]
        assert "aipaygen.com/docs" in html
        assert "aipaygen.com/try" in html

def test_send_welcome_email_contains_curl_example():
    """Email body should contain a curl quick-start example."""
    from email_service import send_welcome_email
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "curl-check"}
        send_welcome_email("user@example.com", "apk_curl_test")
        html = mock_send.call_args[0][0]["html"]
        assert "curl" in html
        assert "apk_curl_test" in html

def test_send_welcome_email_from_address():
    """From address should be the AiPayGen noreply address."""
    from email_service import send_welcome_email, FROM_EMAIL
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "from-check"}
        send_welcome_email("user@example.com", "apk_from")
        call_args = mock_send.call_args[0][0]
        assert call_args["from"] == FROM_EMAIL


# ---------------------------------------------------------------------------
# send_free_tier_nudge
# ---------------------------------------------------------------------------

def test_send_nudge_email():
    from email_service import send_free_tier_nudge
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-456"}
        result = send_free_tier_nudge("user@example.com", tools_used=4, calls_made=10)
        assert result is True
        assert "10" in mock_send.call_args[0][0]["html"]

def test_send_nudge_email_resend_failure():
    from email_service import send_free_tier_nudge
    with patch("email_service.resend.Emails.send", side_effect=Exception("rate limit")):
        result = send_free_tier_nudge("user@example.com", tools_used=1, calls_made=3)
        assert result is False

def test_send_nudge_email_tools_in_body():
    from email_service import send_free_tier_nudge
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "tools-check"}
        send_free_tier_nudge("user@example.com", tools_used=7, calls_made=20)
        html = mock_send.call_args[0][0]["html"]
        assert "7" in html
        assert "20" in html

def test_send_nudge_email_default_args():
    """Default tools_used=0 and calls_made=0 should still send."""
    from email_service import send_free_tier_nudge
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "defaults"}
        result = send_free_tier_nudge("user@example.com")
        assert result is True
        mock_send.assert_called_once()

def test_send_nudge_email_subject():
    """Subject should mention free calls."""
    from email_service import send_free_tier_nudge
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "subj-nudge"}
        send_free_tier_nudge("user@example.com")
        subject = mock_send.call_args[0][0]["subject"]
        assert "free" in subject.lower()

def test_send_nudge_email_buy_credits_link():
    """Email should contain a link to buy credits."""
    from email_service import send_free_tier_nudge
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "buy-link"}
        send_free_tier_nudge("user@example.com", tools_used=3, calls_made=10)
        html = mock_send.call_args[0][0]["html"]
        assert "buy-credits" in html


# ---------------------------------------------------------------------------
# send_magic_link
# ---------------------------------------------------------------------------

def test_send_magic_link():
    from email_service import send_magic_link
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-789"}
        result = send_magic_link("user@example.com", "https://aipaygen.com/auth/verify?token=abc")
        assert result is True
        assert "verify" in mock_send.call_args[0][0]["html"]

def test_send_magic_link_resend_failure():
    from email_service import send_magic_link
    with patch("email_service.resend.Emails.send", side_effect=Exception("network")):
        result = send_magic_link("user@example.com", "https://aipaygen.com/auth/verify?token=x")
        assert result is False

def test_send_magic_link_url_in_body():
    """The magic link URL should appear in the email HTML."""
    from email_service import send_magic_link
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "url-check"}
        link = "https://aipaygen.com/auth/verify?token=secret123"
        send_magic_link("user@example.com", link)
        html = mock_send.call_args[0][0]["html"]
        assert "secret123" in html

def test_send_magic_link_subject():
    from email_service import send_magic_link
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "subj-ml"}
        send_magic_link("user@example.com", "https://example.com")
        subject = mock_send.call_args[0][0]["subject"]
        assert "Sign in" in subject


# ---------------------------------------------------------------------------
# send_weekly_digest
# ---------------------------------------------------------------------------

def test_send_weekly_digest():
    from email_service import send_weekly_digest
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-weekly"}
        result = send_weekly_digest("user@example.com", calls=42, top_tools=["research", "summarize"], spent=1.25)
        assert result is True
        assert "42" in mock_send.call_args[0][0]["html"]

def test_send_weekly_digest_no_tools():
    """When top_tools is None, should default to 'None' in body."""
    from email_service import send_weekly_digest
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "no-tools"}
        result = send_weekly_digest("user@example.com", calls=0, top_tools=None, spent=0.0)
        assert result is True
        html = mock_send.call_args[0][0]["html"]
        assert "None" in html

def test_send_weekly_digest_resend_failure():
    from email_service import send_weekly_digest
    with patch("email_service.resend.Emails.send", side_effect=Exception("500")):
        result = send_weekly_digest("user@example.com", calls=5)
        assert result is False

def test_send_weekly_digest_spent_in_body():
    from email_service import send_weekly_digest
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "spent-check"}
        send_weekly_digest("user@example.com", calls=10, spent=3.75)
        html = mock_send.call_args[0][0]["html"]
        assert "$3.75" in html

def test_send_weekly_digest_html_escapes_tools():
    """Tool names with special chars should be HTML-escaped."""
    from email_service import send_weekly_digest
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "escape-check"}
        send_weekly_digest("user@example.com", top_tools=["<script>alert(1)</script>"])
        html = mock_send.call_args[0][0]["html"]
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# send_deposit_confirmation
# ---------------------------------------------------------------------------

def test_send_deposit_confirmation_success():
    from email_service import send_deposit_confirmation
    with patch("email_service.resend.Emails.send") as mock_send, \
         patch("sqlite3.connect") as mock_conn:
        mock_send.return_value = {"id": "dep-ok"}
        mock_db = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = {"email": "user@example.com"}

        result = send_deposit_confirmation("apk_dep123", 10.0, "base", "0xabc123")
        assert result is True
        html = mock_send.call_args[0][0]["html"]
        assert "$10.00" in html
        assert "basescan.org" in html

def test_send_deposit_confirmation_solana_explorer():
    from email_service import send_deposit_confirmation
    with patch("email_service.resend.Emails.send") as mock_send, \
         patch("sqlite3.connect") as mock_conn:
        mock_send.return_value = {"id": "dep-sol"}
        mock_db = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = {"email": "sol@example.com"}

        result = send_deposit_confirmation("apk_sol", 5.0, "solana", "sig123")
        assert result is True
        html = mock_send.call_args[0][0]["html"]
        assert "solscan.io" in html

def test_send_deposit_confirmation_no_email_on_file():
    from email_service import send_deposit_confirmation
    with patch("sqlite3.connect") as mock_conn:
        mock_db = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = None

        result = send_deposit_confirmation("apk_noemail", 1.0, "base", "0x000")
        assert result is False

def test_send_deposit_confirmation_empty_email():
    from email_service import send_deposit_confirmation
    with patch("sqlite3.connect") as mock_conn:
        mock_db = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = {"email": ""}

        result = send_deposit_confirmation("apk_empty", 1.0, "base", "0x000")
        assert result is False

def test_send_deposit_confirmation_db_error():
    from email_service import send_deposit_confirmation
    with patch("sqlite3.connect", side_effect=Exception("db locked")):
        result = send_deposit_confirmation("apk_dberr", 1.0, "base", "0x000")
        assert result is False

def test_send_deposit_confirmation_resend_failure():
    """DB lookup succeeds but Resend API call fails — should return False."""
    from email_service import send_deposit_confirmation
    with patch("email_service.resend.Emails.send", side_effect=Exception("API down")), \
         patch("sqlite3.connect") as mock_conn:
        mock_db = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = {"email": "user@example.com"}
        result = send_deposit_confirmation("apk_sendfail", 5.0, "base", "0xabc")
        assert result is False

def test_send_deposit_confirmation_tx_hash_in_html():
    """Transaction hash should appear in the email body."""
    from email_service import send_deposit_confirmation
    with patch("email_service.resend.Emails.send") as mock_send, \
         patch("sqlite3.connect") as mock_conn:
        mock_send.return_value = {"id": "hash-check"}
        mock_db = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = {"email": "user@example.com"}
        send_deposit_confirmation("apk_hash", 2.0, "base", "0xdeadbeef")
        html = mock_send.call_args[0][0]["html"]
        assert "0xdeadbeef" in html

def test_send_deposit_confirmation_subject_contains_amount():
    """Subject should show the deposited amount."""
    from email_service import send_deposit_confirmation
    with patch("email_service.resend.Emails.send") as mock_send, \
         patch("sqlite3.connect") as mock_conn:
        mock_send.return_value = {"id": "subj-dep"}
        mock_db = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = {"email": "user@example.com"}
        send_deposit_confirmation("apk_subj", 15.50, "base", "0xabc")
        subject = mock_send.call_args[0][0]["subject"]
        assert "$15.50" in subject

def test_send_deposit_confirmation_conn_closed():
    """DB connection should be closed after lookup."""
    from email_service import send_deposit_confirmation
    with patch("email_service.resend.Emails.send") as mock_send, \
         patch("sqlite3.connect") as mock_conn:
        mock_send.return_value = {"id": "close-check"}
        mock_db = MagicMock()
        mock_conn.return_value = mock_db
        mock_db.execute.return_value.fetchone.return_value = {"email": "user@example.com"}
        send_deposit_confirmation("apk_close", 1.0, "base", "0x000")
        mock_db.close.assert_called_once()
