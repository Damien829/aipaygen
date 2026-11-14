# Smart Router + ReAct Agent Design

**Date:** 2026-03-04
**Status:** Approved

## Problem

1. **Model Router** is static — callers must manually pick models. No intelligence in matching task to model.
2. **Agent Intelligence** is "prompt in, text out" — no reasoning loop, no tool use, no planning, no autonomy.

## Solution: Two upgrades

### 1. Smart Model Router (`model_router.py`)

**New function: `auto_select_model(task_text, constraints=None)`**

Uses a fast classifier (haiku) to analyze the task and return the optimal model.

Classification output:
- `complexity`: 1-5 scale
- `needs_vision`: bool
- `needs_reasoning`: bool (deep logic, math, code)
- `domain`: string (research, code, creative, data, general)

Model mapping:
- Complexity 1-2 → `claude-haiku` / `gpt-4o-mini` / `gemini-flash` (~$0.001/call)
- Complexity 3 → `claude-sonnet` / `gpt-4o` / `gemini-pro` (~$0.01/call)
- Complexity 4-5 → `claude-opus` / `deepseek-r1` (~$0.05/call)
- `needs_vision=true` → filter to vision-capable models only
- Budget cap → pick cheapest model meeting complexity threshold

Integration with `call_model()`:
- `model="auto"` triggers auto-selection
- Response includes `selected_reason` field

**Cumulative cost tracking:**
- `CostTracker` class: tracks per-session cost across multi-step tasks
- Methods: `add(cost)`, `remaining(budget)`, `can_afford(estimated_cost, budget)`
- Used by the ReAct agent to enforce budget across all steps

### 2. ReAct Agent Loop

**New endpoint: `POST /agent`**

Request:
```json
{
  "task": "Research the top 5 AI agent frameworks and compare pricing",
  "agent_id": "optional — for memory persistence",
  "max_cost_usd": 1.00,
  "model": "auto",
  "max_steps": 10
}
```

**Loop (max 20 iterations):**
1. **THINK** — Agent analyzes task + observations so far, decides next action
2. **ACT** — Calls a tool (any endpoint or skill)
3. **OBSERVE** — Reads tool result, appends to observation history
4. **BUDGET CHECK** — Verify remaining budget before next step
5. **REPEAT** until: answer ready, budget exhausted, or max_steps
6. **SYNTHESIZE** — Final answer combining all observations

**Agent system prompt includes:**
- Full tool registry (auto-generated from Flask routes + skills)
- Accumulated observations
- Remaining budget
- Output format: `{"thought": "...", "action": "tool_name", "params": {...}}` or `{"thought": "...", "answer": "final result"}`

**Model selection per step:**
- Thinking steps: use smart router (`auto`) — typically haiku for simple decisions, sonnet for complex reasoning
- Synthesis step: use sonnet or higher for quality final output
- Tool calls: the tool's own model (each endpoint uses its own model internally)

### 3. Memory Integration

- **Task start:** If `agent_id` provided, auto-recall top 3 relevant memories and inject into context
- **Mid-loop:** Agent can explicitly call `memory_store` and `memory_recall` tools
- **Task end:** Auto-save task summary to memory as `task_result:{timestamp}`

### 4. SSE Streaming

**New endpoint: `POST /agent/stream`** — same params as `/agent`

Event types:
- `event: thought` — agent's current reasoning
- `event: action` — tool being called + params
- `event: observation` — tool result summary
- `event: cost` — running cost total
- `event: answer` — final synthesized answer
- `event: done` — trace complete with stats

### 5. Tool Registry (Auto-generated)

Built dynamically at startup by scanning all Flask routes:
- Every `@app.route` with a docstring becomes an available tool
- Tool metadata: endpoint, method, cost, description, required params
- All 646+ skills accessible via `execute_skill` tool
- Stored in `AGENT_TOOLS` dict, refreshed on skill DB changes

### Response Format

```json
{
  "answer": "Here are the top 5 AI agent frameworks...",
  "reasoning_trace": [
    {"step": 1, "thought": "I need to research...", "action": "research", "params": {"topic": "..."}, "cost": 0.003},
    {"step": 2, "thought": "Now compare...", "action": "compare", "params": {"text_a": "...", "text_b": "..."}, "cost": 0.02}
  ],
  "total_cost_usd": 0.043,
  "steps_taken": 4,
  "budget_remaining": 0.957,
  "model_selections": {"step_1": "claude-haiku", "step_2": "claude-sonnet", "synthesis": "claude-sonnet"},
  "memories_recalled": 2,
  "memories_saved": 1
}
```

## Files to Create/Modify

1. **`model_router.py`** — Add `auto_select_model()`, `CostTracker`, `model="auto"` support
2. **`react_agent.py`** (NEW) — ReAct loop, tool registry, memory integration, streaming
3. **`app.py`** — Add `/agent` and `/agent/stream` endpoints, wire up tool registry

## Non-Goals

- No multi-agent orchestration (single agent only)
- No persistent task queue (synchronous execution only)
- No fine-tuning or custom model training
