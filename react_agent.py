"""ReAct Agent — autonomous reasoning loop with tool use, memory, and streaming."""
import json
import time
import logging
import sqlite3
import os
from datetime import datetime

_log = logging.getLogger("react_agent")

SKILLS_DB_PATH = os.path.join(os.path.dirname(__file__), "skills.db")

# Tool descriptions for the agent
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

_SPECIAL_TOOLS = {
    "execute_skill": {
        "description": "Execute any of 1000+ dynamic skills by name. Returns the actual skill output.",
        "params": {"skill": "skill_name", "input": "input for the skill"},
        "cost": 0.02,
    },
    "memory_recall": {
        "description": "Search agent memory for relevant past context.",
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
    "search_catalog": {
        "description": "Search the API catalog of discovered APIs. Find APIs by keyword or category to call them.",
        "params": {"query": "search text", "category": "optional category filter"},
        "cost": 0.0,
    },
    "call_api": {
        "description": "Call any API from the catalog. Use search_catalog first to find the api_id.",
        "params": {"api_id": "catalog API id (integer)", "endpoint": "/path", "params": {}},
        "cost": 0.03,
    },
}


def build_tool_registry() -> dict:
    """Build the complete tool registry from tool descriptions + special tools."""
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


def format_tools_compact(tools: dict) -> str:
    """Compact tool reference for subsequent steps — names only, saves ~1.5KB."""
    names = sorted(tools.keys())
    return "Tools: " + ", ".join(names) + "\nUse same JSON format as step 1."


# ---------------------------------------------------------------------------
# Observation compression
# ---------------------------------------------------------------------------

def _compress_observation(result, max_chars=800) -> str:
    """Compress a tool result into a concise observation string."""
    if isinstance(result, dict):
        compact = {}
        for k, v in result.items():
            if k in ("model", "model_id", "provider", "input_tokens", "output_tokens"):
                continue
            if isinstance(v, str) and len(v) > 300:
                compact[k] = v[:297] + "..."
            elif isinstance(v, list) and len(v) > 10:
                compact[k] = v[:10]
            else:
                compact[k] = v
        text = json.dumps(compact, default=str)
    else:
        text = str(result)

    if len(text) <= max_chars:
        return text
    return text[:max_chars - 20] + "... [truncated]"


def _extract_primary_result(result: dict) -> str:
    """Extract the main content from a tool result for piping."""
    for key in ("result", "text", "summary", "content", "output"):
        if key in result:
            return str(result[key])
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# ReAct Agent — Think → Act → Observe loop (v2: conversation history)
# ---------------------------------------------------------------------------

# Legacy prompt kept for backward compat reference
REACT_SYSTEM_PROMPT = """You are AiPayGen, an autonomous AI agent with access to tools.

AVAILABLE TOOLS:
{tools}

INSTRUCTIONS:
- Analyze the task and break it into steps
- For each step, respond with EXACTLY ONE JSON object (no markdown, no extra text)
- To use a tool: {{"thought": "your reasoning", "action": "tool_name", "params": {{...}}}}
- To give final answer: {{"thought": "your reasoning", "answer": "your complete answer"}}
- Budget remaining: ${budget_remaining:.4f}

MEMORIES:
{memories}

OBSERVATIONS SO FAR:
{observations}
"""

# v2 system prompt — static, sent once (no per-step observations or budget)
_SYSTEM_PROMPT_V2 = """You are AiPayGen, an autonomous AI agent with access to tools.

AVAILABLE TOOLS:
{tools}

INSTRUCTIONS:
- Analyze the task and break it into steps
- For each step, respond with EXACTLY ONE JSON object (no markdown, no extra text)
- To use a tool: {{"thought": "your reasoning", "action": "tool_name", "params": {{...}}}}
- To chain tools (pipe output of one into another): {{"thought": "reasoning", "action": "tool_name", "params": {{...}}, "pipe_to": {{"action": "next_tool", "param_key": "text"}}}}
- To give final answer: {{"thought": "your reasoning", "answer": "your complete answer"}}
- If a tool fails, try a DIFFERENT approach or tool. Do NOT retry the same call.
- Be efficient — use the minimum steps needed to complete the task.

MEMORIES:
{memories}
"""


_SYSTEM_PROMPT_V2_COMPACT = """You are AiPayGen, an autonomous AI agent with access to tools.

{tools}

INSTRUCTIONS:
- Respond with EXACTLY ONE JSON object (no markdown, no extra text)
- To use a tool: {{"thought": "your reasoning", "action": "tool_name", "params": {{...}}}}
- To chain tools: {{"thought": "reasoning", "action": "tool_name", "params": {{...}}, "pipe_to": {{"action": "next_tool", "param_key": "text"}}}}
- To give final answer: {{"thought": "your reasoning", "answer": "your complete answer"}}
- If a tool fails, try a DIFFERENT approach. Be efficient.

MEMORIES:
{memories}
"""


class ReActAgent:
    def __init__(self, call_model_fn, tool_handler_fn, memory_fns=None,
                 synthesize_model: str = "claude-haiku"):
        self.call_model = call_model_fn
        self.handle_tool = tool_handler_fn
        self.memory = memory_fns or {}
        self.tools = build_tool_registry()
        self.synthesize_model = synthesize_model

    def _recall_memories(self, agent_id: str, task: str) -> tuple[str, int]:
        """Recall relevant memories. Returns (memories_text, count)."""
        if not agent_id or not self.memory.get("search"):
            return "None", 0
        try:
            mem_results = self.memory["search"](agent_id, task)
            if mem_results:
                text = "\n".join(
                    f"- [{m.get('key', '')}]: {str(m.get('value', ''))[:200]}"
                    for m in mem_results[:3]
                )
                return text, len(mem_results[:3])
        except Exception as e:
            _log.warning("Memory recall failed: %s", e)
        return "None", 0

    def _execute_and_observe(self, action: str, params: dict, parsed: dict,
                             messages: list, trace: list, step: int, thought: str,
                             cost: float, model_name: str) -> None:
        """Execute a tool, handle chaining, and append results to messages/trace."""
        if not action or action not in self.tools:
            msg = f"Error: unknown tool '{action}'. Available: {', '.join(sorted(self.tools.keys())[:10])}..."
            messages.append({"role": "user", "content": f"[Tool Error]: {msg}"})
            trace.append({"step": step, "thought": thought, "action": action, "params": params,
                          "result": "error: unknown tool", "cost": cost, "model": model_name})
            return

        try:
            tool_result = self.handle_tool(action, params)
        except Exception as e:
            tool_result = {"error": str(e)}

        # Check for errors — provide recovery guidance
        if isinstance(tool_result, dict) and "error" in tool_result:
            messages.append({
                "role": "user",
                "content": f"[Tool Error: {action}]: {tool_result['error']}\n"
                           f"Try a DIFFERENT approach or tool. Do NOT retry the same tool with the same params."
            })
            trace.append({"step": step, "thought": thought, "action": action, "params": params,
                          "result": tool_result, "cost": cost, "model": model_name})
            return

        # Handle tool chaining (pipe_to)
        if "pipe_to" in parsed and tool_result:
            pipe_spec = parsed["pipe_to"]
            next_action = pipe_spec.get("action", "")
            param_key = pipe_spec.get("param_key", "text")

            if next_action in self.tools:
                pipe_value = _extract_primary_result(tool_result) if isinstance(tool_result, dict) else str(tool_result)
                next_params = {param_key: pipe_value}
                next_params.update(pipe_spec.get("extra_params", {}))

                try:
                    chained_result = self.handle_tool(next_action, next_params)
                    observation = _compress_observation(chained_result)
                    messages.append({"role": "user", "content": f"[Chained {action} -> {next_action}]: {observation}"})
                    trace.append({"step": step, "thought": thought, "action": f"{action}->{next_action}",
                                  "params": params, "result": chained_result, "cost": cost, "model": model_name})
                    return
                except Exception as e:
                    messages.append({"role": "user", "content": f"[Chain failed: {action} -> {next_action}]: {e}"})

        # Normal observation
        observation = _compress_observation(tool_result)
        messages.append({"role": "user", "content": f"[Observation from {action}]: {observation}"})
        trace.append({"step": step, "thought": thought, "action": action, "params": params,
                      "result": tool_result, "cost": cost, "model": model_name})

    def run(self, task: str, max_steps: int = 10, max_cost_usd: float = 1.0,
            model: str = "auto", agent_id: str = "") -> dict:
        from model_router import CostTracker
        tracker = CostTracker()
        trace = []
        max_steps = min(max_steps, 20)

        memories_text, memories_recalled = self._recall_memories(agent_id, task)

        # Full system prompt for step 1, compact for subsequent steps
        system_full = _SYSTEM_PROMPT_V2.format(
            tools=format_tools_for_prompt(self.tools),
            memories=memories_text,
        )
        system_compact = _SYSTEM_PROMPT_V2_COMPACT.format(
            tools=format_tools_compact(self.tools),
            memories=memories_text,
        )

        # Conversation history — grows each step
        messages = [{"role": "user", "content": task}]

        stop_reason = "completed"

        for step in range(1, max_steps + 1):
            if not tracker.can_afford(0.001, max_cost_usd):
                stop_reason = "budget_exhausted"
                break

            # Use full tool descriptions on step 1, compact reference after
            system = system_full if step == 1 else system_compact

            # Build call messages with budget note for subsequent steps
            call_messages = list(messages)
            if step > 1:
                budget_note = f"[Budget: ${tracker.remaining(max_cost_usd):.4f} remaining, step {step}/{max_steps}]"
                call_messages.append({"role": "user", "content": f"Continue. {budget_note}"})

            try:
                result = self.call_model(
                    model, call_messages,
                    system=system, max_tokens=1024, temperature=0.3,
                    max_cost_usd=tracker.remaining(max_cost_usd) if max_cost_usd else None,
                )
            except Exception as e:
                stop_reason = f"model_error: {e}"
                break

            tracker.add(result.get("cost_usd", 0), {"step": step, "type": "think", "model": result.get("model", "")})
            parsed = _parse_agent_response(result["text"])
            thought = parsed.get("thought", "")

            # Add assistant response to conversation history
            messages.append({"role": "assistant", "content": result["text"]})

            if "answer" in parsed:
                trace.append({"step": step, "thought": thought, "action": "final_answer", "params": {},
                              "result": parsed["answer"], "cost": result.get("cost_usd", 0), "model": result.get("model", "")})
                if agent_id and self.memory.get("set"):
                    try:
                        self.memory["set"](agent_id, f"task_result:{datetime.utcnow().isoformat()}", {
                            "task": task[:200], "answer": str(parsed["answer"])[:500], "steps": step, "cost": tracker.total})
                    except Exception:
                        pass
                # Record positive outcome for models used
                _record_agent_outcome(tracker.steps, task, quality=0.8)
                return {"answer": parsed["answer"], "reasoning_trace": trace, "total_cost_usd": round(tracker.total, 6),
                        "steps_taken": step, "stop_reason": "completed", "memories_recalled": memories_recalled,
                        "model_selections": {t["step"]: t["model"] for t in tracker.steps}}

            action = parsed.get("action", "")
            params = parsed.get("params", {})

            self._execute_and_observe(action, params, parsed, messages, trace, step,
                                      thought, result.get("cost_usd", 0), result.get("model", ""))

        if stop_reason != "completed" or not trace:
            stop_reason = stop_reason if stop_reason != "completed" else "max_steps_reached"

        # Synthesize from trace instead of separate observations list
        observations = [{"step": t["step"], "action": t["action"], "result": t["result"]}
                        for t in trace if t.get("action") != "final_answer"]
        answer = _synthesize_answer(observations, task,
                                    call_model_fn=self.call_model, model=self.synthesize_model)
        # Record neutral/negative outcome — agent didn't complete naturally
        _record_agent_outcome(tracker.steps, task, quality=0.3 if stop_reason == "max_steps_reached" else 0.2)
        return {"answer": answer, "reasoning_trace": trace, "total_cost_usd": round(tracker.total, 6),
                "steps_taken": len(trace), "stop_reason": stop_reason, "memories_recalled": memories_recalled,
                "model_selections": {t["step"]: t["model"] for t in tracker.steps}}

    def run_stream(self, task: str, max_steps: int = 10, max_cost_usd: float = 1.0,
                   model: str = "auto", agent_id: str = ""):
        """Generator that yields SSE events as the agent reasons."""
        from model_router import CostTracker
        tracker = CostTracker()
        max_steps = min(max_steps, 20)

        memories_text, memories_recalled = self._recall_memories(agent_id, task)

        # Full prompt for step 1, compact for subsequent
        system_full = _SYSTEM_PROMPT_V2.format(
            tools=format_tools_for_prompt(self.tools),
            memories=memories_text,
        )
        system_compact = _SYSTEM_PROMPT_V2_COMPACT.format(
            tools=format_tools_compact(self.tools),
            memories=memories_text,
        )

        # Conversation history
        messages = [{"role": "user", "content": task}]

        for step in range(1, max_steps + 1):
            if not tracker.can_afford(0.001, max_cost_usd):
                yield {"event": "done", "data": {"reason": "budget_exhausted", "total_cost": tracker.total, "steps": step - 1}}
                return

            system = system_full if step == 1 else system_compact
            call_messages = list(messages)
            if step > 1:
                budget_note = f"[Budget: ${tracker.remaining(max_cost_usd):.4f} remaining, step {step}/{max_steps}]"
                call_messages.append({"role": "user", "content": f"Continue. {budget_note}"})

            try:
                result = self.call_model(model, call_messages, system=system, max_tokens=1024, temperature=0.3,
                                         max_cost_usd=tracker.remaining(max_cost_usd))
            except Exception as e:
                yield {"event": "done", "data": {"reason": f"model_error: {e}", "total_cost": tracker.total, "steps": step - 1}}
                return

            tracker.add(result.get("cost_usd", 0))
            parsed = _parse_agent_response(result["text"])
            thought = parsed.get("thought", "")

            messages.append({"role": "assistant", "content": result["text"]})

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

                # Handle tool chaining in stream mode
                if "pipe_to" in parsed and tool_result and not (isinstance(tool_result, dict) and "error" in tool_result):
                    pipe_spec = parsed["pipe_to"]
                    next_action = pipe_spec.get("action", "")
                    param_key = pipe_spec.get("param_key", "text")

                    if next_action in self.tools:
                        pipe_value = _extract_primary_result(tool_result) if isinstance(tool_result, dict) else str(tool_result)
                        next_params = {param_key: pipe_value}
                        next_params.update(pipe_spec.get("extra_params", {}))
                        try:
                            chained_result = self.handle_tool(next_action, next_params)
                            observation = _compress_observation(chained_result)
                            messages.append({"role": "user", "content": f"[Chained {action} -> {next_action}]: {observation}"})
                            yield {"event": "observation", "data": {"step": step, "action": f"{action}->{next_action}", "result": observation[:300]}}
                            continue
                        except Exception as e:
                            messages.append({"role": "user", "content": f"[Chain failed: {action} -> {next_action}]: {e}"})

                # Error recovery guidance
                if isinstance(tool_result, dict) and "error" in tool_result:
                    error_msg = f"[Tool Error: {action}]: {tool_result['error']}\nTry a DIFFERENT approach or tool."
                    messages.append({"role": "user", "content": error_msg})
                    yield {"event": "observation", "data": {"step": step, "action": action, "result": f"Error: {tool_result['error']}"}}
                else:
                    observation = _compress_observation(tool_result)
                    messages.append({"role": "user", "content": f"[Observation from {action}]: {observation}"})
                    yield {"event": "observation", "data": {"step": step, "action": action, "result": observation[:300]}}
            else:
                error_msg = f"Error: unknown tool '{action}'"
                messages.append({"role": "user", "content": f"[Tool Error]: {error_msg}"})
                yield {"event": "observation", "data": {"step": step, "action": action, "result": error_msg}}

        # Synthesize from messages
        observations = []
        for msg in messages:
            if msg["role"] == "user" and msg["content"].startswith("[Observation"):
                observations.append({"step": 0, "action": "tool", "result": msg["content"]})
        answer = _synthesize_answer(observations, task,
                                    call_model_fn=self.call_model, model=self.synthesize_model)
        yield {"event": "answer", "data": {"answer": answer}}
        yield {"event": "done", "data": {"reason": "max_steps_reached", "total_cost": round(tracker.total, 6), "steps": max_steps}}


def _record_agent_outcome(steps: list, task: str, quality: float) -> None:
    """Record outcome feedback for models used in this agent run."""
    try:
        from model_router import record_outcome, _classify_task
        domain = _classify_task(task).get("domain", "general")
        models_used = set()
        for s in steps:
            m = s.get("model", "")
            if m and m not in models_used:
                models_used.add(m)
                record_outcome(m, domain, quality)
    except Exception:
        pass  # non-critical


def _parse_agent_response(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
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
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
    return {"thought": "Could not parse structured response", "answer": text}


def _synthesize_answer(observations: list, task: str,
                       call_model_fn=None, model: str = "claude-haiku") -> str:
    """Synthesize a coherent answer from observations using an LLM call.
    Falls back to naive concatenation if the model call fails."""
    if not observations:
        return "I was unable to complete this task within the given constraints."

    # Build observation context
    parts = []
    for obs in observations:
        result = obs.get("result", "")
        if isinstance(result, dict):
            result = result.get("result") or result.get("summary") or str(result)
        parts.append(f"Step {obs.get('step', '?')} ({obs.get('action', 'unknown')}): {str(result)[:500]}")
    observations_text = "\n\n".join(parts)

    # Try LLM synthesis
    if call_model_fn:
        try:
            synth_result = call_model_fn(
                model,
                [{"role": "user", "content": f"Original task: {task}\n\nHere are the results from {len(observations)} steps:\n\n{observations_text}\n\nSynthesize a clear, complete answer to the original task based on these results. Be concise and direct."}],
                system="You are a helpful assistant. Synthesize the provided research steps into a coherent answer.",
                max_tokens=1024,
                temperature=0.3,
            )
            return synth_result.get("text", "").strip()
        except Exception as e:
            _log.warning("LLM synthesis failed, falling back to naive: %s", e)

    # Naive fallback
    fallback_parts = [str(obs.get("result", ""))[:300] if not isinstance(obs.get("result"), dict)
                      else str(obs["result"].get("result") or obs["result"].get("summary") or obs["result"])[:300]
                      for obs in observations]
    return f"Based on {len(observations)} steps:\n\n" + "\n\n".join(fallback_parts)


# ---------------------------------------------------------------------------
# Tool Handler Factory
# ---------------------------------------------------------------------------

def make_tool_handler(batch_handlers: dict, memory_search_fn, memory_set_fn,
                      skills_db_path: str, agent_id: str = "", skills_search_engine=None,
                      call_model_fn=None):
    def handler(tool_name: str, params: dict) -> dict:
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
            if skills_search_engine:
                results = skills_search_engine.search(query, top_n=10)
                return {"skills": [{"name": s["name"], "description": s["description"], "category": s["category"], "score": s.get("score", 0)} for s in results], "count": len(results)}
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

        if tool_name == "search_catalog":
            from api_catalog import get_all_apis
            query = params.get("query", "")
            category = params.get("category")
            apis, total = get_all_apis(page=1, per_page=20, category=category)
            if query:
                q = query.lower()
                apis = [a for a in apis if q in (a.get("name", "") + " " + a.get("description", "")).lower()]
            return {"apis": [{"id": a["id"], "name": a["name"], "description": (a.get("description") or "")[:200],
                              "base_url": a["base_url"], "category": a.get("category"), "score": a.get("quality_score", 0)}
                             for a in apis[:10]], "total": total}

        if tool_name == "call_api":
            from api_catalog import get_api, record_api_economics
            from security import validate_url, SSRFError, safe_fetch
            api_id = params.get("api_id")
            if not api_id:
                return {"error": "api_id required — use search_catalog first"}
            api = get_api(int(api_id))
            if not api:
                return {"error": f"API {api_id} not found in catalog"}
            endpoint = params.get("endpoint", "/")
            url = api["base_url"].rstrip("/") + "/" + endpoint.lstrip("/")
            try:
                validate_url(url, allow_http=False)
            except SSRFError as e:
                return {"error": f"Blocked URL: {e}"}
            # Check for x402 payment capability
            if api.get("x402_compatible"):
                try:
                    from x402_client import call_x402_api
                    result = call_x402_api(url)
                    if "error" not in result:
                        record_api_economics(int(api_id), 0.03, result.get("cost_usd", 0))
                    return {"api": api["name"], "url": url, **result}
                except ImportError:
                    pass  # fall through to regular fetch
            result = safe_fetch(url, timeout=15, max_size=50000)
            if "error" not in result:
                record_api_economics(int(api_id), 0.03, 0)
            return {"api": api["name"], "url": url, "status": result.get("status"),
                    "body": result.get("body", "")[:2000]}

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

                # Actually execute the skill through call_model
                if call_model_fn and skill.get("prompt_template"):
                    prompt = skill["prompt_template"].replace("{{input}}", str(skill_input))
                    use_model = skill.get("model") or "claude-haiku"
                    try:
                        result = call_model_fn(
                            use_model,
                            [{"role": "user", "content": prompt}],
                            system="You are an expert assistant. Complete the task accurately and concisely.",
                            max_tokens=1024,
                        )
                        return {
                            "skill": skill_name,
                            "result": result["text"],
                            "model": result.get("model", use_model),
                            "cost_usd": result.get("cost_usd", 0),
                        }
                    except Exception as e:
                        _log.warning("Skill execution via model failed for %s: %s", skill_name, e)
                        return {"skill": skill_name, "description": skill["description"],
                                "template": skill["prompt_template"][:200], "status": "loaded",
                                "note": f"Model execution failed: {e}"}

                return {"skill": skill_name, "description": skill["description"],
                        "template": skill["prompt_template"][:200], "status": "loaded"}
            except Exception as e:
                return {"error": str(e)}

        if tool_name in batch_handlers:
            try:
                return batch_handlers[tool_name](params)
            except Exception as e:
                return {"error": f"Tool '{tool_name}' failed: {str(e)}"}

        return {"error": f"Unknown tool: {tool_name}"}

    return handler
