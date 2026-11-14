"""Tests for enhanced marketplace: search, categories, reviews, performance, leaderboard."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_memory


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_memory, "DB_PATH", str(tmp_path / "agent_memory.db"))
    agent_memory.init_memory_db()


def test_marketplace_list_with_multi_pricing():
    result = agent_memory.marketplace_list_service(
        agent_id="agent-1", name="TestAgent", description="A test agent",
        endpoint="https://example.com/agent", price_usd=0.05,
        category="research", capabilities=["research", "summarize"],
        wallet_address="0xabc",
        pricing_models={"per_call": 0.05, "monthly": 14.99},
        tags=["research", "web", "summarize"],
    )
    assert result["listed"] is True
    listing = agent_memory.marketplace_get_service(result["listing_id"])
    assert listing is not None
    assert listing["category"] == "research"


def test_marketplace_search():
    agent_memory.marketplace_list_service(
        agent_id="a1", name="AlphaScout", description="Crypto trading agent",
        endpoint="https://x.com/a", price_usd=29.0, category="trading",
    )
    agent_memory.marketplace_list_service(
        agent_id="a2", name="DeepResearch", description="Web research",
        endpoint="https://x.com/b", price_usd=0.02, category="research",
    )
    results, total = agent_memory.marketplace_search("crypto trading")
    assert total >= 1
    assert any("AlphaScout" in r["name"] for r in results)


def test_marketplace_categories():
    agent_memory.marketplace_list_service(
        agent_id="a1", name="Agent1", description="", endpoint="https://x.com/1",
        price_usd=1.0, category="trading",
    )
    agent_memory.marketplace_list_service(
        agent_id="a2", name="Agent2", description="", endpoint="https://x.com/2",
        price_usd=1.0, category="trading",
    )
    agent_memory.marketplace_list_service(
        agent_id="a3", name="Agent3", description="", endpoint="https://x.com/3",
        price_usd=1.0, category="research",
    )
    cats = agent_memory.marketplace_get_categories()
    assert cats["trading"] == 2
    assert cats["research"] == 1


def test_submit_review():
    result = agent_memory.marketplace_list_service(
        agent_id="a1", name="Agent1", description="", endpoint="https://x.com/1",
        price_usd=1.0, category="research",
    )
    listing_id = result["listing_id"]
    review = agent_memory.marketplace_add_review(
        listing_id=listing_id, reviewer_id="user-1", rating=5,
        review_text="Excellent agent", verified=True,
    )
    assert review["rating"] == 5
    reviews = agent_memory.marketplace_get_reviews(listing_id)
    assert len(reviews) == 1
    assert reviews[0]["reviewer_id"] == "user-1"


def test_performance_tracking():
    agent_memory.marketplace_record_performance(
        listing_id="lst-1", metric_name="roi_30d", metric_value=312.0,
    )
    agent_memory.marketplace_record_performance(
        listing_id="lst-1", metric_name="win_rate", metric_value=73.1,
    )
    perf = agent_memory.marketplace_get_performance("lst-1")
    assert len(perf) == 2
    assert any(p["metric_name"] == "roi_30d" for p in perf)


def test_leaderboard():
    agent_memory.marketplace_list_service(
        agent_id="a1", name="TopAgent", description="", endpoint="https://x.com/1",
        price_usd=1.0, category="trading",
    )
    agent_memory.marketplace_list_service(
        agent_id="a2", name="MidAgent", description="", endpoint="https://x.com/2",
        price_usd=1.0, category="trading",
    )
    for listing in agent_memory.marketplace_get_services(category="trading")[0]:
        if listing["name"] == "TopAgent":
            for _ in range(10):
                agent_memory.marketplace_increment_calls(listing["listing_id"])
    leaders = agent_memory.marketplace_leaderboard(category="trading", limit=5)
    assert len(leaders) >= 1
    assert leaders[0]["name"] == "TopAgent"
