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
        from agent_network import init_network_db
        init_network_db()
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
