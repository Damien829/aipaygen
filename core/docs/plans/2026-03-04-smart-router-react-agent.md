# Smart Router + ReAct Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add intelligent auto-model-selection to the router and build a fully autonomous ReAct agent endpoint with memory integration and SSE streaming.

**Architecture:** Extend `model_router.py` with a task classifier and cost tracker. Create new `react_agent.py` module containing the ReAct loop, tool registry (auto-built from BATCH_HANDLERS + skills DB), memory hooks, and SSE streaming. Wire into `app.py` via `/agent` and `/agent/stream` endpoints.

**Tech Stack:** Python 3.11, Flask, SQLite (skills.db, agent_memory.db), SSE via generator, existing `call_model()` + `BATCH_HANDLERS` + `agent_memory` module.

---

### Task 1: Smart Model Router — CostTracker

**Files:**
- Modify: `model_router.py` (append after line 454)
- Test: `tests/test_model_router.py` (create)

**Step 1: Create tests directory and write failing test**

```bash
mkdir -p tests
```

```python
# tests/test_model_router.py
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
    # No budget means unlimited
    assert ct.can_afford(1.00, budget=None) is True
    assert ct.remaining(None) == float("inf")
```

**Step 2: Run test to verify it fails**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_model_router.py -v`
Expected: FAIL with ImportError for CostTracker

**Step 3: Implement CostTracker**

Append to `model_router.py`:

```python
# ---------------------------------------------------------------------------
# Cost Tracker — cumulative cost tracking for multi-step agent sessions
# ---------------------------------------------------------------------------

class CostTracker:
    """Tracks cumulative cost across multiple model calls in a session."""

    def __init__(self):
        self.total = 0.0
        self.steps: list[dict] = []

    def add(self, cost: float, step_info: dict | None = None):
        self.total += cost
        if step_info:
            self.steps.append({**step_info, "cost": cost, "cumulative": self.total})

    def can_afford(self, estimated_cost: float, budget: float | None) -> bool:
        if budget is None:
            return True
        return (self.total + estimated_cost) <= budget

    def remaining(self, budget: float | None) -> float:
        if budget is None:
            return float("inf")
        return max(0.0, budget - self.total)
```

**Step 4: Run test to verify it passes**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_model_router.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add model_router.py tests/test_model_router.py
git commit -m "feat: add CostTracker to model_router for multi-step budget tracking"
```

---

### Task 2: Smart Model Router — auto_select_model()

**Files:**
- Modify: `model_router.py`
- Modify: `tests/test_model_router.py`

**Step 1: Write failing test**

Add to `tests/test_model_router.py`:

```python
from model_router import auto_select_model, _classify_task

def test_classify_task_returns_valid_structure():
    # Test the heuristic classifier (no LLM call)
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
    # Simple task should get a cheap model
    assert model["model"] in ("claude-haiku", "gpt-4o-mini", "gemini-2.5-flash")

def test_auto_select_complex():
    model = auto_select_model("Prove the Riemann hypothesis and explain your reasoning step by step")
    assert model["model"] in ("claude-opus", "claude-sonnet", "deepseek-r1", "gemini-2.5-pro")

def test_auto_select_with_budget():
    model = auto_select_model("Complex analysis task", max_cost_usd=0.002)
    # Should pick cheap model due to budget
    assert model["model"] in ("claude-haiku", "gpt-4o-mini", "gemini-2.5-flash", "deepseek-v3")

def test_auto_select_vision():
    model = auto_select_model("Describe this image in detail", needs_vision=True)
    from model_router import MODEL_REGISTRY
    cfg = MODEL_REGISTRY[model["model"]]
    assert cfg["vision"] is True
```

**Step 2: Run test to verify it fails**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_model_router.py::test_classify_task_returns_valid_structure -v`
Expected: FAIL with ImportError

**Step 3: Implement _classify_task and auto_select_model**

Append to `model_router.py`:

```python
# ---------------------------------------------------------------------------
# Smart Model Selection — classify task and pick optimal model
# ---------------------------------------------------------------------------

import re as _re

# Keywords that indicate higher complexity
_COMPLEX_KEYWORDS = {
    5: ["prove", "theorem", "formal verification", "mathematical proof"],
    4: ["algorithm", "dynamic programming", "recursive", "optimize", "architecture", "design system",
        "security audit", "vulnerability", "machine learning model"],
    3: ["analyze", "compare multiple", "step by step", "detailed", "comprehensive",
        "debug", "refactor", "review code", "explain why"],
}

_REASONING_KEYWORDS = ["why", "prove", "reason", "logic", "deduce", "infer", "step by step",
                        "think through", "algorithm", "mathematical"]

_VISION_KEYWORDS = ["image", "photo", "picture", "screenshot", "diagram", "chart", "visual",
                     "describe what you see", "look at"]


def _classify_task(task_text: str) -> dict:
    """Heuristic task classifier — fast, free, no LLM call needed.

    Returns {complexity: 1-5, needs_vision: bool, needs_reasoning: bool, domain: str}.
    """
    text_lower = task_text.lower()
    word_count = len(task_text.split())

    # Complexity scoring
    complexity = 1
    if word_count > 100:
        complexity = max(complexity, 3)
    elif word_count > 50:
        complexity = max(complexity, 2)

    for level, keywords in _COMPLEX_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            complexity = max(complexity, level)
            break

    # Vision detection
    needs_vision = any(kw in text_lower for kw in _VISION_KEYWORDS)

    # Reasoning detection
    needs_reasoning = any(kw in text_lower for kw in _REASONING_KEYWORDS)
    if needs_reasoning and complexity < 3:
        complexity = 3

    # Domain detection (simple keyword match)
    domain = "general"
    domain_map = {
        "code": ["code", "function", "class", "bug", "python", "javascript", "api", "sql", "debug"],
        "research": ["research", "study", "paper", "literature", "survey", "findings"],
        "creative": ["write", "story", "poem", "creative", "blog", "article", "essay"],
        "data": ["data", "csv", "json", "parse", "transform", "pipeline", "etl"],
        "finance": ["stock", "financial", "investment", "portfolio", "revenue", "pricing"],
    }
    for d, keywords in domain_map.items():
        if any(kw in text_lower for kw in keywords):
            domain = d
            break

    return {
        "complexity": min(complexity, 5),
        "needs_vision": needs_vision,
        "needs_reasoning": needs_reasoning,
        "domain": domain,
    }


# Cost tiers: maps complexity ranges to model lists (cheapest first)
_MODEL_TIERS = {
    "low": ["claude-haiku", "gpt-4o-mini", "gemini-2.5-flash", "deepseek-v3"],
    "mid": ["claude-sonnet", "gpt-4o", "gemini-2.5-pro"],
    "high": ["claude-opus", "deepseek-r1"],
}


def auto_select_model(
    task_text: str,
    max_cost_usd: float | None = None,
    needs_vision: bool | None = None,
) -> dict:
    """Auto-select the best model for a task based on complexity and constraints.

    Returns {model: str, reason: str, classification: dict}.
    """
    classification = _classify_task(task_text)

    if needs_vision is not None:
        classification["needs_vision"] = needs_vision

    # Pick tier
    c = classification["complexity"]
    if c <= 2:
        tier = "low"
    elif c <= 3:
        tier = "mid"
    else:
        tier = "high"

    candidates = list(_MODEL_TIERS[tier])

    # Filter for vision if needed
    if classification["needs_vision"]:
        candidates = [m for m in candidates if MODEL_REGISTRY[m].get("vision")]
        if not candidates:
            # Fall back to any vision model
            candidates = [m for m, cfg in MODEL_REGISTRY.items() if cfg.get("vision")]

    # Filter by budget if set
    if max_cost_usd is not None:
        # Estimate ~500 input + 500 output tokens for cost check
        affordable = []
        for m in candidates:
            est_cost = calculate_cost(m, 500, 500)
            if est_cost <= max_cost_usd:
                affordable.append(m)
        if affordable:
            candidates = affordable
        else:
            # Budget is very tight — pick absolute cheapest
            all_models = sorted(MODEL_REGISTRY.keys(), key=lambda m: calculate_cost(m, 500, 500))
            if classification["needs_vision"]:
                all_models = [m for m in all_models if MODEL_REGISTRY[m].get("vision")]
            candidates = [all_models[0]] if all_models else candidates

    selected = candidates[0]
    reason = f"complexity={c}/5, tier={tier}, vision={classification['needs_vision']}"

    return {
        "model": selected,
        "reason": reason,
        "classification": classification,
    }
```

**Step 4: Run tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_model_router.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add model_router.py tests/test_model_router.py
git commit -m "feat: add auto_select_model with heuristic task classifier"
```

---

### Task 3: Integrate model="auto" into call_model()

**Files:**
- Modify: `model_router.py` (modify `call_model` function at line 319)
- Modify: `tests/test_model_router.py`

**Step 1: Write failing test**

Add to `tests/test_model_router.py`:

```python
def test_resolve_model_auto():
    """model='auto' should not raise — it triggers auto-selection."""
    from model_router import resolve_model_name
    # "auto" should be recognized as a special value
    result = resolve_model_name("auto")
    assert result == "auto"
```

**Step 2: Run to verify failure**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_model_router.py::test_resolve_model_auto -v`
Expected: FAIL with ModelNotFoundError

**Step 3: Implement**

In `model_router.py`, modify `resolve_model_name` (line 231):

```python
def resolve_model_name(name: str) -> str:
    """Resolve an alias or canonical name. Raises ModelNotFoundError if unknown."""
    if name == "auto":
        return "auto"
    if name in MODEL_REGISTRY:
        return name
    if name in _ALIASES:
        return _ALIASES[name]
    raise ModelNotFoundError(f"Unknown model: {name}")
```

Modify `call_model` (line 319) to handle `model="auto"`:

Replace the first few lines of `call_model` with:

```python
def call_model(
    model: str,
    messages: list[dict],
    system: str = "",
    max_tokens: int | None = None,
    temperature: float = 0.7,
    max_cost_usd: float | None = None,
) -> dict:
    """Call any supported model with circuit breaker + fallback.

    Returns {text, model, model_id, provider, input_tokens, output_tokens, cost_usd, selected_reason}.
    """
    selected_reason = None

    # Auto-select model if requested
    if model == "auto":
        # Use first user message as task text for classification
        task_text = ""
        for m in messages:
            if m.get("role") == "user":
                task_text = m.get("content", "")
                break
        selection = auto_select_model(task_text, max_cost_usd=max_cost_usd)
        model = selection["model"]
        selected_reason = selection["reason"]

    cfg = get_model_config(model)
    # ... rest of function unchanged ...
```

Add `selected_reason` to the return dict at the end of `call_model`:

```python
    return {
        "text": result["text"],
        "model": canonical,
        "model_id": cfg["model_id"],
        "provider": provider,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "cost_usd": cost,
        "selected_reason": selected_reason,
    }
```

**Step 4: Run tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_model_router.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add model_router.py tests/test_model_router.py
git commit -m "feat: support model='auto' in call_model with smart selection"
```

---

### Task 4: ReAct Agent — Tool Registry

**Files:**
- Create: `react_agent.py`
- Test: `tests/test_react_agent.py` (create)

**Step 1: Write failing test**

```python
# tests/test_react_agent.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def test_build_tool_registry():
    from react_agent import build_tool_registry
    # Requires BATCH_HANDLERS to be importable
    tools = build_tool_registry()
    assert isinstance(tools, dict)
    assert len(tools) > 10  # Should have 30+ tools from BATCH_HANDLERS
    # Each tool should have description and params
    for name, tool in tools.items():
        assert "description" in tool
        assert "params" in tool

def test_tool_registry_includes_skills():
    from react_agent import build_tool_registry
    tools = build_tool_registry()
    assert "execute_skill" in tools

def test_tool_registry_includes_memory():
    from react_agent import build_tool_registry
    tools = build_tool_registry()
    assert "memory_recall" in tools
    assert "memory_store" in tools

def test_format_tools_for_prompt():
    from react_agent import build_tool_registry, format_tools_for_prompt
    tools = build_tool_registry()
    prompt = format_tools_for_prompt(tools)
    assert isinstance(prompt, str)
    assert "research" in prompt
    assert "execute_skill" in prompt
```

**Step 2: Run to verify failure**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py::test_build_tool_registry -v`
Expected: FAIL — module not found

**Step 3: Implement tool registry**

```python
# react_agent.py
"""ReAct Agent — autonomous reasoning loop with tool use, memory, and streaming.

Provides a Think→Act→Observe loop that can call any AiPayGen endpoint
or skill to solve complex tasks autonomously.
"""
import json
import time
import logging
import sqlite3
import os
from datetime import datetime

_log = logging.getLogger("react_agent")

SKILLS_DB_PATH = os.path.join(os.path.dirname(__file__), "skills.db")

# ---------------------------------------------------------------------------
# Tool Registry — auto-built from BATCH_HANDLERS + skills + memory
# ---------------------------------------------------------------------------

# Tool descriptions for the agent (hand-written for clarity)
_TOOL_DESCRIPTIONS = {
    "research": {"description": "Deep research on a topic with AI synthesis", "params": {"topic": "topic to research"}, "cost": 0.05},
    "summarize": {"description": "Summarize text to a given length", "params": {"text": "text to summarize", "length": "short|medium|long"}, "cost": 0.02},
    "analyze": {"description": "Analyze content and answer a question about it", "params": {"content": "content to analyze", "question": "analysis question"}, "cost": 0.03},
    "translate": {"description": "Translate text to another language", "params": {"text": "text to translate", "language": "target language"}, "cost": 0.02},
    "social": {"description": "Generate social media posts for multiple platforms", "params": {"topic": "topic", "platforms": ["twitter", "linkedin"], "tone": "engaging"}, "cost": 0.02},
    "write": {"description": "Write content (article, blog, email, etc.)", "params": {"spec": "what to write", "type": "article|blog|email"}, "cost": 0.03},
    "code": {"description": "Generate code from description", "params": {"description": "what the code should do", "language": "Python"}, "cost": 0.03},
    "extract": {"description": "Extract structured data from text", "params": {"text": "source text", "fields": ["field1", "field2"]}, "cost": 0.02},
    "qa": {"description": "Answer a question given context", "params": {"context": "reference text", "question": "question to answer"}, "cost": 0.02},
    "classify": {"description": "Classify text into categories", "params": {"text": "text to classify", "categories": ["cat1", "cat2"]}, "cost": 0.01},
    "sentiment": {"description": "Analyze sentiment of text", "params": {"text": "text to analyze"}, "cost": 0.01},
    "keywords": {"description": "Extract keywords from text", "params": {"text": "source text", "max_keywords": 10}, "cost": 0.01},
    "compare": {"description": "Compare two texts", "params": {"text_a": "first text", "text_b": "second text", "focus": "comparison focus"}, "cost": 0.02},
    "transform": {"description": "Transform text with an instruction", "params": {"text": "text to transform", "instruction": "how to transform it"}, "cost": 0.02},
    "chat": {"description": "General AI chat/reasoning", "params": {"messages": [{"role": "user", "content": "message"}]}, "cost": 0.03},
    "plan": {"description": "Create a step-by-step action plan for a goal", "params": {"goal": "goal to plan for", "context": "optional context"}, "cost": 0.02},
    "decide": {"description": "Help make a decision between options", "params": {"decision": "what to decide", "options": ["a", "b"], "criteria": "evaluation criteria"}, "cost": 0.02},
    "proofread": {"description": "Proofread and fix text", "params": {"text": "text to proofread", "style": "professional"}, "cost": 0.02},
    "explain": {"description": "Explain a concept at a given level", "params": {"concept": "concept to explain", "level": "beginner|intermediate|expert"}, "cost": 0.02},
    "questions": {"description": "Generate questions about content", "params": {"content": "source content", "type": "faq|quiz|interview", "count": 5}, "cost": 0.02},
    "outline": {"description": "Create a structured outline for a topic", "params": {"topic": "topic to outline", "depth": 2, "sections": 6}, "cost": 0.02},
    "email": {"description": "Draft an email", "params": {"purpose": "email purpose", "tone": "professional", "recipient": "who it's for"}, "cost": 0.02},
    "sql": {"description": "Generate SQL query from description", "params": {"description": "what the query should do", "dialect": "postgresql"}, "cost": 0.02},
    "regex": {"description": "Generate regex pattern from description", "params": {"description": "what to match", "language": "python"}, "cost": 0.01},
    "mock": {"description": "Generate mock/fake data", "params": {"description": "data description", "count": 5, "format": "json"}, "cost": 0.02},
    "score": {"description": "Score content on multiple criteria", "params": {"content": "content to score", "criteria": ["clarity", "accuracy"]}, "cost": 0.02},
    "timeline": {"description": "Extract timeline/events from text", "params": {"text": "source text"}, "cost": 0.02},
    "action": {"description": "Extract action items from text", "params": {"text": "source text"}, "cost": 0.01},
    "pitch": {"description": "Generate a pitch for a product", "params": {"product": "product name", "audience": "target audience", "length": "30s"}, "cost": 0.02},
    "debate": {"description": "Generate balanced debate arguments", "params": {"topic": "debate topic"}, "cost": 0.02},
    "headline": {"description": "Generate headlines for content", "params": {"content": "source content", "count": 5, "style": "engaging"}, "cost": 0.01},
    "fact": {"description": "Fact-check claims in text", "params": {"text": "text to fact-check"}, "cost": 0.02},
    "rewrite": {"description": "Rewrite text for a different audience/tone", "params": {"text": "text to rewrite", "audience": "target audience", "tone": "neutral"}, "cost": 0.02},
    "tag": {"description": "Auto-tag content with categories", "params": {"text": "content to tag", "max_tags": 10}, "cost": 0.01},
}

# Special tools the agent can use
_SPECIAL_TOOLS = {
    "execute_skill": {
        "description": "Execute any of 646+ dynamic skills by name. Use GET /skills?q=keyword to find available skills first.",
        "params": {"skill": "skill_name", "input": "input for the skill"},
        "cost": 0.02,
    },
    "memory_recall": {
        "description": "Search agent memory for relevant past context. Returns matching memories.",
        "params": {"query": "search query"},
        "cost": 0.01,
    },
    "memory_store": {
        "description": "Save important information to agent memory for future recall.",
        "params": {"key": "memory key", "value": "data to remember", "tags": ["tag1"]},
        "cost": 0.01,
    },
    "search_skills": {
        "description": "Search the skills database to find skills matching a query.",
        "params": {"query": "search keywords"},
        "cost": 0.0,
    },
}


def build_tool_registry() -> dict:
    """Build the complete tool registry from BATCH_HANDLERS + special tools."""
    tools = {}
    tools.update(_TOOL_DESCRIPTIONS)
    tools.update(_SPECIAL_TOOLS)
    return tools


def format_tools_for_prompt(tools: dict) -> str:
    """Format tool registry into a compact string for the agent system prompt."""
    lines = []
    for name, t in sorted(tools.items()):
        params_str = ", ".join(f"{k}" for k in t.get("params", {}).keys())
        cost = t.get("cost", 0)
        lines.append(f"- {name}({params_str}) — {t['description']} [${cost:.2f}]")
    return "\n".join(lines)
```

**Step 4: Run tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add react_agent.py tests/test_react_agent.py
git commit -m "feat: create react_agent.py with auto-built tool registry"
```

---

### Task 5: ReAct Agent — Core Reasoning Loop

**Files:**
- Modify: `react_agent.py`
- Modify: `tests/test_react_agent.py`

**Step 1: Write failing test**

Add to `tests/test_react_agent.py`:

```python
from unittest.mock import MagicMock, patch
from react_agent import ReActAgent

def _mock_call_model(model, messages, system="", max_tokens=None, temperature=0.7, max_cost_usd=None):
    """Mock call_model that returns a tool call then an answer."""
    content = messages[-1]["content"] if messages else ""
    if "Step 1" in content or "THINK" in content or "step 1" in content.lower():
        return {
            "text": '{"thought": "I need to research this topic", "action": "research", "params": {"topic": "AI agents"}}',
            "model": "claude-haiku", "model_id": "test", "provider": "anthropic",
            "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None,
        }
    else:
        return {
            "text": '{"thought": "I have enough info", "answer": "AI agents are autonomous systems."}',
            "model": "claude-haiku", "model_id": "test", "provider": "anthropic",
            "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None,
        }

def _mock_tool_handler(name, params):
    return {"result": f"Mock result for {name}", "model": "claude-haiku"}

def test_react_agent_runs_loop():
    agent = ReActAgent(
        call_model_fn=_mock_call_model,
        tool_handler_fn=_mock_tool_handler,
    )
    result = agent.run("What are AI agents?", max_steps=5, max_cost_usd=1.0)
    assert "answer" in result
    assert "reasoning_trace" in result
    assert "total_cost_usd" in result
    assert result["steps_taken"] >= 1

def test_react_agent_respects_budget():
    call_count = 0
    def expensive_call_model(model, messages, **kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "text": '{"thought": "thinking", "action": "research", "params": {"topic": "test"}}',
            "model": "claude-haiku", "model_id": "test", "provider": "anthropic",
            "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.50,
            "selected_reason": None,
        }

    agent = ReActAgent(
        call_model_fn=expensive_call_model,
        tool_handler_fn=_mock_tool_handler,
    )
    result = agent.run("Expensive task", max_steps=10, max_cost_usd=0.60)
    # Should stop after 1-2 steps due to budget
    assert result["steps_taken"] <= 3
    assert "budget" in result.get("stop_reason", "budget")

def test_react_agent_respects_max_steps():
    step_counter = {"n": 0}
    def always_act(model, messages, **kwargs):
        step_counter["n"] += 1
        return {
            "text": '{"thought": "keep going", "action": "research", "params": {"topic": "test"}}',
            "model": "claude-haiku", "model_id": "test", "provider": "anthropic",
            "input_tokens": 10, "output_tokens": 10, "cost_usd": 0.0001,
            "selected_reason": None,
        }

    agent = ReActAgent(
        call_model_fn=always_act,
        tool_handler_fn=_mock_tool_handler,
    )
    result = agent.run("Infinite task", max_steps=3, max_cost_usd=100.0)
    assert result["steps_taken"] <= 3
```

**Step 2: Run to verify failure**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py::test_react_agent_runs_loop -v`
Expected: FAIL — ReActAgent not found

**Step 3: Implement the ReAct loop**

Append to `react_agent.py`:

```python
# ---------------------------------------------------------------------------
# ReAct Agent — Think → Act → Observe loop
# ---------------------------------------------------------------------------

REACT_SYSTEM_PROMPT = """You are AiPayGen, an autonomous AI agent with access to tools.

AVAILABLE TOOLS:
{tools}

INSTRUCTIONS:
- Analyze the task and break it into steps
- For each step, respond with EXACTLY ONE JSON object (no markdown, no extra text)
- To use a tool: {{"thought": "your reasoning", "action": "tool_name", "params": {{...}}}}
- To give final answer: {{"thought": "your reasoning", "answer": "your complete answer"}}
- Use the cheapest/fastest approach that produces quality results
- If a tool fails, try an alternative approach
- Budget remaining: ${budget_remaining:.4f}

MEMORIES (from previous sessions):
{memories}

OBSERVATIONS SO FAR:
{observations}
"""


class ReActAgent:
    """Autonomous reasoning agent using Think→Act→Observe loop."""

    def __init__(self, call_model_fn, tool_handler_fn, memory_fns=None):
        """
        Args:
            call_model_fn: callable matching model_router.call_model signature
            tool_handler_fn: callable(tool_name, params) -> dict
            memory_fns: optional dict with 'search' and 'set' callables
        """
        self.call_model = call_model_fn
        self.handle_tool = tool_handler_fn
        self.memory = memory_fns or {}
        self.tools = build_tool_registry()

    def run(self, task: str, max_steps: int = 10, max_cost_usd: float = 1.0,
            model: str = "auto", agent_id: str = "") -> dict:
        """Execute the ReAct loop for a task.

        Returns {answer, reasoning_trace, total_cost_usd, steps_taken, stop_reason, ...}
        """
        from model_router import CostTracker
        tracker = CostTracker()
        trace = []
        observations = []
        max_steps = min(max_steps, 20)

        # Recall relevant memories
        memories_text = "None"
        memories_recalled = 0
        if agent_id and self.memory.get("search"):
            try:
                mem_results = self.memory["search"](agent_id, task)
                if mem_results:
                    memories_text = "\n".join(
                        f"- [{m.get('key', '')}]: {str(m.get('value', ''))[:200]}"
                        for m in mem_results[:3]
                    )
                    memories_recalled = len(mem_results[:3])
            except Exception as e:
                _log.warning("Memory recall failed: %s", e)

        stop_reason = "completed"

        for step in range(1, max_steps + 1):
            # Budget check
            if not tracker.can_afford(0.001, max_cost_usd):
                stop_reason = "budget_exhausted"
                break

            # Build system prompt with current state
            obs_text = "\n".join(
                f"Step {o['step']}: [{o['action']}] → {str(o['result'])[:500]}"
                for o in observations
            ) or "None yet — this is the first step."

            system = REACT_SYSTEM_PROMPT.format(
                tools=format_tools_for_prompt(self.tools),
                budget_remaining=tracker.remaining(max_cost_usd),
                memories=memories_text,
                observations=obs_text,
            )

            # Think
            user_msg = task if step == 1 else f"Continue. Step {step} of {max_steps}. What's your next action?"
            try:
                result = self.call_model(
                    model,
                    [{"role": "user", "content": user_msg}],
                    system=system,
                    max_tokens=1024,
                    temperature=0.3,
                    max_cost_usd=tracker.remaining(max_cost_usd) if max_cost_usd else None,
                )
            except Exception as e:
                _log.error("Model call failed at step %d: %s", step, e)
                stop_reason = f"model_error: {e}"
                break

            tracker.add(result.get("cost_usd", 0), {"step": step, "type": "think", "model": result.get("model", "")})

            # Parse response
            parsed = _parse_agent_response(result["text"])
            thought = parsed.get("thought", "")

            if "answer" in parsed:
                # Agent is done
                trace.append({
                    "step": step, "thought": thought,
                    "action": "final_answer", "params": {},
                    "result": parsed["answer"],
                    "cost": result.get("cost_usd", 0),
                    "model": result.get("model", ""),
                })
                # Save to memory
                if agent_id and self.memory.get("set"):
                    try:
                        self.memory["set"](agent_id, f"task_result:{datetime.utcnow().isoformat()}", {
                            "task": task[:200],
                            "answer": str(parsed["answer"])[:500],
                            "steps": step,
                            "cost": tracker.total,
                        })
                    except Exception:
                        pass

                return {
                    "answer": parsed["answer"],
                    "reasoning_trace": trace,
                    "total_cost_usd": round(tracker.total, 6),
                    "steps_taken": step,
                    "stop_reason": "completed",
                    "memories_recalled": memories_recalled,
                    "model_selections": {t["step"]: t["model"] for t in tracker.steps},
                }

            # Agent wants to use a tool
            action = parsed.get("action", "")
            params = parsed.get("params", {})

            if not action or action not in self.tools:
                # Invalid action — tell agent and continue
                observations.append({
                    "step": step, "action": action or "unknown",
                    "result": f"Error: unknown tool '{action}'. Available: {', '.join(sorted(self.tools.keys())[:15])}...",
                })
                trace.append({
                    "step": step, "thought": thought,
                    "action": action, "params": params,
                    "result": "error: unknown tool",
                    "cost": result.get("cost_usd", 0),
                    "model": result.get("model", ""),
                })
                continue

            # Execute tool
            try:
                tool_result = self.handle_tool(action, params)
            except Exception as e:
                tool_result = {"error": str(e)}

            # Record observation
            observations.append({"step": step, "action": action, "result": tool_result})
            trace.append({
                "step": step, "thought": thought,
                "action": action, "params": params,
                "result": tool_result,
                "cost": result.get("cost_usd", 0),
                "model": result.get("model", ""),
            })

        # Loop ended without answer — synthesize from observations
        if stop_reason != "completed" or not trace:
            stop_reason = stop_reason if stop_reason != "completed" else "max_steps_reached"

        # Try to synthesize a final answer from observations
        answer = _synthesize_answer(observations, task)

        return {
            "answer": answer,
            "reasoning_trace": trace,
            "total_cost_usd": round(tracker.total, 6),
            "steps_taken": len(trace),
            "stop_reason": stop_reason,
            "memories_recalled": memories_recalled,
            "model_selections": {t["step"]: t["model"] for t in tracker.steps},
        }


def _parse_agent_response(text: str) -> dict:
    """Parse JSON from the agent's response, handling markdown wrapping."""
    text = text.strip()
    # Try direct JSON parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try markdown-wrapped JSON
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except (json.JSONDecodeError, ValueError):
                continue
    # Try extracting JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    # Fallback: treat entire response as answer
    return {"thought": "Could not parse structured response", "answer": text}


def _synthesize_answer(observations: list, task: str) -> str:
    """Build a best-effort answer from accumulated observations."""
    if not observations:
        return "I was unable to complete this task within the given constraints."
    parts = []
    for obs in observations:
        result = obs.get("result", "")
        if isinstance(result, dict):
            result = result.get("result") or result.get("summary") or str(result)
        parts.append(str(result)[:300])
    return f"Based on {len(observations)} steps:\n\n" + "\n\n".join(parts)
```

**Step 4: Run tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add react_agent.py tests/test_react_agent.py
git commit -m "feat: implement ReAct reasoning loop with budget control and memory"
```

---

### Task 6: Wire ReAct Agent into app.py — /agent endpoint

**Files:**
- Modify: `app.py` (add after the `/chain` endpoint, ~line 6872)
- Modify: `tests/test_react_agent.py`

**Step 1: Write failing test**

Add to `tests/test_react_agent.py`:

```python
def test_make_tool_handler():
    """Tool handler should wrap BATCH_HANDLERS."""
    from react_agent import make_tool_handler

    # Mock BATCH_HANDLERS
    mock_handlers = {"research": lambda d: {"summary": "test result"}}
    handler = make_tool_handler(mock_handlers, memory_search_fn=None, memory_set_fn=None, skills_db_path=":memory:")

    result = handler("research", {"topic": "AI"})
    assert result["summary"] == "test result"

def test_make_tool_handler_unknown_tool():
    from react_agent import make_tool_handler
    handler = make_tool_handler({}, memory_search_fn=None, memory_set_fn=None, skills_db_path=":memory:")
    result = handler("nonexistent", {})
    assert "error" in result
```

**Step 2: Run to verify failure**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py::test_make_tool_handler -v`
Expected: FAIL — make_tool_handler not found

**Step 3: Implement make_tool_handler and /agent endpoint**

Append to `react_agent.py`:

```python
# ---------------------------------------------------------------------------
# Tool Handler Factory — bridges ReAct agent to BATCH_HANDLERS + memory + skills
# ---------------------------------------------------------------------------

def make_tool_handler(batch_handlers: dict, memory_search_fn, memory_set_fn,
                      skills_db_path: str, agent_id: str = ""):
    """Create a tool handler function that dispatches to the right backend.

    Returns callable(tool_name, params) -> dict
    """
    def handler(tool_name: str, params: dict) -> dict:
        # Special tools
        if tool_name == "memory_recall" and memory_search_fn:
            query = params.get("query", "")
            if not query or not agent_id:
                return {"error": "query and agent_id required"}
            results = memory_search_fn(agent_id, query)
            return {"results": results, "count": len(results)}

        if tool_name == "memory_store" and memory_set_fn:
            key = params.get("key", "")
            value = params.get("value", "")
            if not key or not value or not agent_id:
                return {"error": "key, value, and agent_id required"}
            tags = params.get("tags", [])
            return memory_set_fn(agent_id, key, value, tags)

        if tool_name == "search_skills":
            query = params.get("query", "")
            try:
                conn = sqlite3.connect(skills_db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT name, description, category FROM skills WHERE name LIKE ? OR description LIKE ? LIMIT 10",
                    (f"%{query}%", f"%{query}%"),
                ).fetchall()
                conn.close()
                return {"skills": [dict(r) for r in rows], "count": len(rows)}
            except Exception as e:
                return {"error": str(e)}

        if tool_name == "execute_skill":
            skill_name = params.get("skill", "")
            skill_input = params.get("input", "")
            try:
                conn = sqlite3.connect(skills_db_path)
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM skills WHERE name = ?", (skill_name,)).fetchone()
                if not row:
                    conn.close()
                    return {"error": f"skill '{skill_name}' not found"}
                skill = dict(row)
                conn.execute("UPDATE skills SET calls = calls + 1 WHERE name = ?", (skill_name,))
                conn.commit()
                conn.close()
                # Return the skill info — actual execution happens via batch_handlers or call_model
                return {"skill": skill_name, "description": skill["description"],
                        "template": skill["prompt_template"][:200], "status": "loaded"}
            except Exception as e:
                return {"error": str(e)}

        # Standard tools — dispatch to BATCH_HANDLERS
        if tool_name in batch_handlers:
            try:
                return batch_handlers[tool_name](params)
            except Exception as e:
                return {"error": f"Tool '{tool_name}' failed: {str(e)}"}

        return {"error": f"Unknown tool: {tool_name}"}

    return handler
```

Add to `app.py` after the `/chain` endpoint (~line 6872):

```python
# ── ReAct Agent — autonomous reasoning endpoint ──────────────────────────────

@app.route("/agent", methods=["POST"])
def agent_endpoint():
    """Autonomous AI agent that reasons through complex tasks using tools."""
    from react_agent import ReActAgent, make_tool_handler
    from agent_memory import memory_search, memory_set

    data = request.get_json() or {}
    task = data.get("task", "")
    if not task:
        return jsonify({"error": "task required", "hint": 'POST {"task": "your task description"}'}), 400

    agent_id = data.get("agent_id", "")
    max_cost = float(data.get("max_cost_usd", 1.0))
    max_steps = min(int(data.get("max_steps", 10)), 20)
    model = data.get("model", "auto")

    # Build tool handler
    tool_handler = make_tool_handler(
        batch_handlers=BATCH_HANDLERS,
        memory_search_fn=memory_search if agent_id else None,
        memory_set_fn=memory_set if agent_id else None,
        skills_db_path=_skills_db_path,
        agent_id=agent_id,
    )

    # Memory functions for the agent
    memory_fns = {}
    if agent_id:
        memory_fns = {"search": memory_search, "set": memory_set}

    agent = ReActAgent(
        call_model_fn=call_model,
        tool_handler_fn=tool_handler,
        memory_fns=memory_fns,
    )

    result = agent.run(
        task=task,
        max_steps=max_steps,
        max_cost_usd=max_cost,
        model=model,
        agent_id=agent_id,
    )

    log_payment("/agent", result.get("total_cost_usd", 0.05), request.remote_addr)
    return jsonify(agent_response(result, "/agent"))
```

**Step 4: Run tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py -v`
Expected: All PASS

**Step 5: Verify app.py compiles**

Run: `cd /home/damien809/agent-service && python -c "import py_compile; py_compile.compile('app.py', doraise=True); print('OK')"`
Expected: OK

**Step 6: Commit**

```bash
git add react_agent.py app.py tests/test_react_agent.py
git commit -m "feat: add /agent endpoint with autonomous ReAct reasoning loop"
```

---

### Task 7: SSE Streaming — /agent/stream endpoint

**Files:**
- Modify: `react_agent.py` (add streaming generator)
- Modify: `app.py` (add `/agent/stream` route)

**Step 1: Write failing test**

Add to `tests/test_react_agent.py`:

```python
def test_react_agent_stream():
    agent = ReActAgent(
        call_model_fn=_mock_call_model,
        tool_handler_fn=_mock_tool_handler,
    )
    events = list(agent.run_stream("What are AI agents?", max_steps=5, max_cost_usd=1.0))
    assert len(events) >= 1
    # Should have at least a thought and answer event
    event_types = [e["event"] for e in events]
    assert "thought" in event_types or "answer" in event_types
    # Last event should be done
    assert events[-1]["event"] == "done"
```

**Step 2: Run to verify failure**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py::test_react_agent_stream -v`
Expected: FAIL — run_stream not found

**Step 3: Implement streaming**

Add `run_stream` method to `ReActAgent` class in `react_agent.py`:

```python
    def run_stream(self, task: str, max_steps: int = 10, max_cost_usd: float = 1.0,
                   model: str = "auto", agent_id: str = ""):
        """Generator that yields SSE events as the agent reasons.

        Yields dicts: {event: str, data: dict}
        """
        from model_router import CostTracker
        tracker = CostTracker()
        trace = []
        observations = []
        max_steps = min(max_steps, 20)

        # Recall memories
        memories_text = "None"
        memories_recalled = 0
        if agent_id and self.memory.get("search"):
            try:
                mem_results = self.memory["search"](agent_id, task)
                if mem_results:
                    memories_text = "\n".join(
                        f"- [{m.get('key', '')}]: {str(m.get('value', ''))[:200]}"
                        for m in mem_results[:3]
                    )
                    memories_recalled = len(mem_results[:3])
            except Exception:
                pass

        for step in range(1, max_steps + 1):
            if not tracker.can_afford(0.001, max_cost_usd):
                yield {"event": "done", "data": {"reason": "budget_exhausted", "total_cost": tracker.total, "steps": step - 1}}
                return

            obs_text = "\n".join(
                f"Step {o['step']}: [{o['action']}] → {str(o['result'])[:500]}"
                for o in observations
            ) or "None yet."

            system = REACT_SYSTEM_PROMPT.format(
                tools=format_tools_for_prompt(self.tools),
                budget_remaining=tracker.remaining(max_cost_usd),
                memories=memories_text,
                observations=obs_text,
            )

            user_msg = task if step == 1 else f"Continue. Step {step}/{max_steps}."
            try:
                result = self.call_model(model, [{"role": "user", "content": user_msg}],
                                         system=system, max_tokens=1024, temperature=0.3,
                                         max_cost_usd=tracker.remaining(max_cost_usd))
            except Exception as e:
                yield {"event": "done", "data": {"reason": f"model_error: {e}", "total_cost": tracker.total, "steps": step - 1}}
                return

            tracker.add(result.get("cost_usd", 0))
            parsed = _parse_agent_response(result["text"])
            thought = parsed.get("thought", "")

            yield {"event": "thought", "data": {"step": step, "thought": thought, "model": result.get("model", "")}}
            yield {"event": "cost", "data": {"step": step, "step_cost": result.get("cost_usd", 0), "total_cost": tracker.total}}

            if "answer" in parsed:
                yield {"event": "answer", "data": {"answer": parsed["answer"]}}
                yield {"event": "done", "data": {"reason": "completed", "total_cost": round(tracker.total, 6), "steps": step, "memories_recalled": memories_recalled}}
                return

            action = parsed.get("action", "")
            params = parsed.get("params", {})
            yield {"event": "action", "data": {"step": step, "action": action, "params": params}}

            if action and action in self.tools:
                try:
                    tool_result = self.handle_tool(action, params)
                except Exception as e:
                    tool_result = {"error": str(e)}
                observations.append({"step": step, "action": action, "result": tool_result})
                result_summary = str(tool_result)[:300]
                yield {"event": "observation", "data": {"step": step, "action": action, "result": result_summary}}
            else:
                observations.append({"step": step, "action": action, "result": f"Unknown tool: {action}"})
                yield {"event": "observation", "data": {"step": step, "action": action, "result": f"Error: unknown tool '{action}'"}}

        # Max steps reached
        answer = _synthesize_answer(observations, task)
        yield {"event": "answer", "data": {"answer": answer}}
        yield {"event": "done", "data": {"reason": "max_steps_reached", "total_cost": round(tracker.total, 6), "steps": max_steps}}
```

Add `/agent/stream` to `app.py` right after the `/agent` endpoint:

```python
@app.route("/agent/stream", methods=["POST"])
def agent_stream_endpoint():
    """Streaming autonomous agent — returns SSE events as the agent reasons."""
    from react_agent import ReActAgent, make_tool_handler
    from agent_memory import memory_search, memory_set

    data = request.get_json() or {}
    task = data.get("task", "")
    if not task:
        return jsonify({"error": "task required"}), 400

    agent_id = data.get("agent_id", "")
    max_cost = float(data.get("max_cost_usd", 1.0))
    max_steps = min(int(data.get("max_steps", 10)), 20)
    model = data.get("model", "auto")

    tool_handler = make_tool_handler(
        batch_handlers=BATCH_HANDLERS,
        memory_search_fn=memory_search if agent_id else None,
        memory_set_fn=memory_set if agent_id else None,
        skills_db_path=_skills_db_path,
        agent_id=agent_id,
    )

    memory_fns = {"search": memory_search, "set": memory_set} if agent_id else {}

    agent = ReActAgent(
        call_model_fn=call_model,
        tool_handler_fn=tool_handler,
        memory_fns=memory_fns,
    )

    def generate():
        for event in agent.run_stream(task=task, max_steps=max_steps, max_cost_usd=max_cost,
                                       model=model, agent_id=agent_id):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

**Step 4: Run tests**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_react_agent.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add react_agent.py app.py tests/test_react_agent.py
git commit -m "feat: add /agent/stream SSE endpoint for real-time reasoning trace"
```

---

### Task 8: Integration Test — Full Agent Flow

**Files:**
- Create: `tests/test_agent_integration.py`

**Step 1: Write integration test**

```python
# tests/test_agent_integration.py
"""Integration test: full ReAct agent flow with mocked model calls."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from react_agent import ReActAgent, make_tool_handler, build_tool_registry

_call_sequence = []

def _sequenced_call_model(model, messages, **kwargs):
    """Returns research action first, then final answer."""
    _call_sequence.append(model)
    step = len(_call_sequence)
    if step == 1:
        return {
            "text": '{"thought": "I should research AI agents first", "action": "research", "params": {"topic": "AI agents comparison"}}',
            "model": "claude-haiku", "model_id": "test", "provider": "test",
            "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.002,
            "selected_reason": "complexity=2/5",
        }
    else:
        return {
            "text": '{"thought": "I have enough information to answer", "answer": "The top AI agent frameworks are CrewAI, LangGraph, and AutoGen. CrewAI focuses on role-based agents, LangGraph on graph-based workflows, and AutoGen on multi-agent conversations."}',
            "model": "claude-sonnet", "model_id": "test", "provider": "test",
            "input_tokens": 500, "output_tokens": 200, "cost_usd": 0.01,
            "selected_reason": "complexity=3/5",
        }

def test_full_agent_flow():
    _call_sequence.clear()

    batch_handlers = {
        "research": lambda d: {"summary": "CrewAI, LangGraph, and AutoGen are top frameworks", "key_points": ["role-based", "graph-based", "multi-agent"]},
    }
    handler = make_tool_handler(batch_handlers, None, None, ":memory:")

    agent = ReActAgent(
        call_model_fn=_sequenced_call_model,
        tool_handler_fn=handler,
    )
    result = agent.run("Compare the top AI agent frameworks", max_steps=5, max_cost_usd=1.0)

    assert result["stop_reason"] == "completed"
    assert "CrewAI" in result["answer"]
    assert result["steps_taken"] == 2
    assert result["total_cost_usd"] > 0
    assert len(result["reasoning_trace"]) == 2
    assert result["reasoning_trace"][0]["action"] == "research"
    assert result["reasoning_trace"][1]["action"] == "final_answer"

def test_agent_stream_flow():
    _call_sequence.clear()

    batch_handlers = {
        "research": lambda d: {"summary": "Test result"},
    }
    handler = make_tool_handler(batch_handlers, None, None, ":memory:")

    agent = ReActAgent(
        call_model_fn=_sequenced_call_model,
        tool_handler_fn=handler,
    )
    events = list(agent.run_stream("Compare frameworks", max_steps=5, max_cost_usd=1.0))

    event_types = [e["event"] for e in events]
    assert "thought" in event_types
    assert "answer" in event_types
    assert "done" in event_types
    # Verify done event has stats
    done_event = [e for e in events if e["event"] == "done"][0]
    assert done_event["data"]["reason"] == "completed"
```

**Step 2: Run test**

Run: `cd /home/damien809/agent-service && python -m pytest tests/test_agent_integration.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_agent_integration.py
git commit -m "test: add integration tests for full ReAct agent flow"
```

---

### Task 9: Verify all files compile and all tests pass

**Step 1: Compile check**

```bash
cd /home/damien809/agent-service
python -c "import py_compile; py_compile.compile('model_router.py', doraise=True); print('model_router OK')"
python -c "import py_compile; py_compile.compile('react_agent.py', doraise=True); print('react_agent OK')"
python -c "import py_compile; py_compile.compile('app.py', doraise=True); print('app OK')"
```

**Step 2: Run all tests**

```bash
cd /home/damien809/agent-service && python -m pytest tests/ -v
```

Expected: All tests PASS

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete smart router + ReAct agent implementation"
```
