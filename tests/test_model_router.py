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
