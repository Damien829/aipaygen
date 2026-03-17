"""Tests for agent_network.py — free tier, messaging, knowledge base."""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Use a temp DB for each test."""
    db_path = str(tmp_path / "network.db")
    with patch("agent_network.DB_PATH", db_path):
        import agent_network
        agent_network._fingerprint_db_initialized = False
        agent_network._free_tier_cache.clear()
        agent_network.init_network_db()
        yield db_path


class TestFreeTier:
    def test_free_tier_allows_up_to_limit(self, fresh_db):
        from agent_network import check_and_use_free_tier, FREE_DAILY_LIMIT
        ip = "test-ip-1"
        for _ in range(FREE_DAILY_LIMIT):
            assert check_and_use_free_tier(ip) is True

    def test_free_tier_blocks_after_limit(self, fresh_db):
        from agent_network import check_and_use_free_tier, FREE_DAILY_LIMIT
        ip = "test-ip-2"
        for _ in range(FREE_DAILY_LIMIT):
            check_and_use_free_tier(ip)
        assert check_and_use_free_tier(ip) is False

    def test_free_tier_limit_is_reasonable(self):
        from agent_network import FREE_DAILY_LIMIT
        assert 1 <= FREE_DAILY_LIMIT <= 10

    def test_free_tier_different_ips_independent(self, fresh_db):
        from agent_network import check_and_use_free_tier, FREE_DAILY_LIMIT
        for _ in range(FREE_DAILY_LIMIT):
            check_and_use_free_tier("ip-a")
        assert check_and_use_free_tier("ip-a") is False
        assert check_and_use_free_tier("ip-b") is True

    def test_get_free_tier_remaining(self, fresh_db):
        from agent_network import check_and_use_free_tier, get_free_tier_remaining, FREE_DAILY_LIMIT
        ip = "test-ip-remaining"
        assert get_free_tier_remaining(ip) == FREE_DAILY_LIMIT
        check_and_use_free_tier(ip)
        assert get_free_tier_remaining(ip) == FREE_DAILY_LIMIT - 1

    def test_get_free_tier_status(self, fresh_db):
        from agent_network import check_and_use_free_tier, get_free_tier_status
        ip = "test-ip-status"
        check_and_use_free_tier(ip)
        status = get_free_tier_status(ip)
        assert "calls_today" in status or "remaining" in status


class TestFingerprinting:
    """Tests for fingerprint-based IP rotation detection."""

    def test_build_fingerprint_deterministic(self, fresh_db):
        from agent_network import build_fingerprint
        fp1 = build_fingerprint("Mozilla/5.0", "en-US", "gzip, br")
        fp2 = build_fingerprint("Mozilla/5.0", "en-US", "gzip, br")
        assert fp1 == fp2
        assert len(fp1) == 32

    def test_different_headers_different_fingerprint(self, fresh_db):
        from agent_network import build_fingerprint
        fp1 = build_fingerprint("Mozilla/5.0", "en-US", "gzip")
        fp2 = build_fingerprint("curl/7.88", "de-DE", "gzip")
        assert fp1 != fp2

    def test_fingerprint_allows_normal_use(self, fresh_db):
        from agent_network import record_fingerprint
        fp = "a" * 32
        # Same fingerprint from 1 IP should be fine
        assert record_fingerprint("1.2.3.4", fp) is True
        assert record_fingerprint("1.2.3.4", fp) is True

    def test_fingerprint_blocks_after_threshold(self, fresh_db):
        from agent_network import record_fingerprint, _FINGERPRINT_IP_THRESHOLD
        fp = "b" * 32
        # Use the fingerprint from many different IPs
        for i in range(_FINGERPRINT_IP_THRESHOLD - 1):
            assert record_fingerprint(f"10.0.0.{i}", fp) is True
        # The 5th IP should trigger the block
        assert record_fingerprint(f"10.0.0.99", fp) is False

    def test_fingerprint_block_exhausts_all_ips(self, fresh_db):
        from agent_network import record_fingerprint, check_and_use_free_tier, _FINGERPRINT_IP_THRESHOLD
        fp = "c" * 32
        ips = [f"10.1.0.{i}" for i in range(_FINGERPRINT_IP_THRESHOLD)]
        for ip in ips[:-1]:
            record_fingerprint(ip, fp)
        # Trigger block on last IP
        record_fingerprint(ips[-1], fp)
        # All those IPs should now be blocked from free tier
        for ip in ips:
            assert check_and_use_free_tier(ip) is False

    def test_is_fingerprint_blocked(self, fresh_db):
        from agent_network import record_fingerprint, is_fingerprint_blocked, _FINGERPRINT_IP_THRESHOLD
        fp = "d" * 32
        assert is_fingerprint_blocked(fp) is False
        for i in range(_FINGERPRINT_IP_THRESHOLD):
            record_fingerprint(f"10.2.0.{i}", fp)
        assert is_fingerprint_blocked(fp) is True

    def test_empty_fingerprint_not_blocked(self, fresh_db):
        from agent_network import record_fingerprint, is_fingerprint_blocked
        assert record_fingerprint("1.2.3.4", "") is True
        assert is_fingerprint_blocked("") is False

    def test_different_fingerprints_independent(self, fresh_db):
        from agent_network import record_fingerprint, _FINGERPRINT_IP_THRESHOLD
        fp_bad = "e" * 32
        fp_good = "f" * 32
        # Block fp_bad
        for i in range(_FINGERPRINT_IP_THRESHOLD):
            record_fingerprint(f"10.3.0.{i}", fp_bad)
        # fp_good should still work
        assert record_fingerprint("10.4.0.1", fp_good) is True


class TestAtomicFreeTier:
    """Tests for atomic (BEGIN IMMEDIATE) free tier enforcement."""

    def test_check_and_use_is_atomic(self, fresh_db):
        """Verify that check_and_use_free_tier correctly limits under sequential calls."""
        from agent_network import check_and_use_free_tier, FREE_DAILY_LIMIT
        ip = "atomic-test-ip"
        results = []
        for _ in range(FREE_DAILY_LIMIT + 5):
            results.append(check_and_use_free_tier(ip))
        assert results.count(True) == FREE_DAILY_LIMIT
        assert results.count(False) == 5


class TestMessaging:
    def test_send_and_read(self, fresh_db):
        from agent_network import send_message, get_inbox
        send_message("sender1", "receiver1", "hello", "greeting")
        inbox = get_inbox("receiver1")
        assert len(inbox) >= 1

    def test_mark_read(self, fresh_db):
        from agent_network import send_message, get_inbox, mark_read
        send_message("s", "r", "test", "t")
        inbox = get_inbox("r")
        msg_id = inbox[0]["id"]
        mark_read(msg_id, "r")


class TestKnowledge:
    def test_add_and_search(self, fresh_db):
        from agent_network import add_knowledge, search_knowledge
        add_knowledge("agent1", "Python is great", json.dumps(["python", "programming"]))
        results = search_knowledge("python")
        assert len(results) >= 1
