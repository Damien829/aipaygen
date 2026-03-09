import pytest
from unittest.mock import patch

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

def test_send_nudge_email():
    from email_service import send_free_tier_nudge
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-456"}
        result = send_free_tier_nudge("user@example.com", tools_used=4, calls_made=10)
        assert result is True
        assert "10" in mock_send.call_args[0][0]["html"]

def test_send_magic_link():
    from email_service import send_magic_link
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-789"}
        result = send_magic_link("user@example.com", "https://aipaygen.com/auth/verify?token=abc")
        assert result is True
        assert "verify" in mock_send.call_args[0][0]["html"]

def test_send_weekly_digest():
    from email_service import send_weekly_digest
    with patch("email_service.resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-weekly"}
        result = send_weekly_digest("user@example.com", calls=42, top_tools=["research", "summarize"], spent=1.25)
        assert result is True
        assert "42" in mock_send.call_args[0][0]["html"]
