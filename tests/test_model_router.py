import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from model_router import CostTracker

def test_cost_tracker_basic():
    ct = CostTracker()
    assert ct.total == 0.0
    ct.add(0.01)
    ct.add(0.02)
    assert abs(ct.total - 0.03) < 1e-9

def test_cost_tracker_can_afford():
    ct = CostTracker()
    ct.add(0.90)
    assert ct.can_afford(0.05, budget=1.00) is True
    assert ct.can_afford(0.15, budget=1.00) is False

def test_cost_tracker_remaining():
    ct = CostTracker()
    ct.add(0.25)
    assert abs(ct.remaining(1.00) - 0.75) < 1e-9

def test_cost_tracker_no_budget():
    ct = CostTracker()
    ct.add(5.00)
    assert ct.can_afford(1.00, budget=None) is True
    assert ct.remaining(None) == float("inf")


from model_router import auto_select_model, _classify_task

def test_classify_task_returns_valid_structure():
    result = _classify_task("What is 2+2?")
    assert "complexity" in result
    assert result["complexity"] in (1, 2, 3, 4, 5)
    assert "needs_vision" in result
    assert "needs_reasoning" in result

def test_classify_simple_task():
    result = _classify_task("Summarize this text")
    assert result["complexity"] <= 2

def test_classify_complex_task():
    result = _classify_task("Write a recursive algorithm to solve the traveling salesman problem with dynamic programming and prove its time complexity")
    assert result["complexity"] >= 3

def test_auto_select_simple():
    model = auto_select_model("Say hello")
    assert model["model"] in ("claude-haiku", "gpt-4o-mini", "gemini-2.5-flash", "deepseek-v3")

def test_auto_select_complex():
    model = auto_select_model("Prove the Riemann hypothesis and explain your reasoning step by step")
    assert model["model"] in ("claude-opus", "claude-sonnet", "deepseek-r1", "gemini-2.5-pro")

def test_auto_select_with_budget():
    model = auto_select_model("Complex analysis task", max_cost_usd=0.002)
    assert model["model"] in ("claude-haiku", "gpt-4o-mini", "gemini-2.5-flash", "deepseek-v3")

def test_auto_select_vision():
    model = auto_select_model("Describe this image in detail", needs_vision=True)
    from model_router import MODEL_REGISTRY
    cfg = MODEL_REGISTRY[model["model"]]
    assert cfg["vision"] is True
