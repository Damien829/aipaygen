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
        "description": "Execute any of 646+ dynamic skills by name.",
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


# ---------------------------------------------------------------------------
# ReAct Agent — Think → Act → Observe loop
# ---------------------------------------------------------------------------

REACT_SYSTEM_PROMPT = """You are AiPayGent, an autonomous AI agent with access to tools.

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


class ReActAgent:
    def __init__(self, call_model_fn, tool_handler_fn, memory_fns=None):
        self.call_model = call_model_fn
        self.handle_tool = tool_handler_fn
        self.memory = memory_fns or {}
        self.tools = build_tool_registry()

    def run(self, task: str, max_steps: int = 10, max_cost_usd: float = 1.0,
            model: str = "auto", agent_id: str = "") -> dict:
        from model_router import CostTracker
        tracker = CostTracker()
        trace = []
        observations = []
        max_steps = min(max_steps, 20)

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
            if not tracker.can_afford(0.001, max_cost_usd):
                stop_reason = "budget_exhausted"
                break

            obs_text = "\n".join(
                f"Step {o['step']}: [{o['action']}] -> {str(o['result'])[:500]}"
                for o in observations
            ) or "None yet."

            system = REACT_SYSTEM_PROMPT.format(
                tools=format_tools_for_prompt(self.tools),
                budget_remaining=tracker.remaining(max_cost_usd),
                memories=memories_text,
                observations=obs_text,
            )

            user_msg = task if step == 1 else f"Continue. Step {step} of {max_steps}. What's your next action?"
            try:
                result = self.call_model(
                    model, [{"role": "user", "content": user_msg}],
                    system=system, max_tokens=1024, temperature=0.3,
                    max_cost_usd=tracker.remaining(max_cost_usd) if max_cost_usd else None,
                )
            except Exception as e:
                stop_reason = f"model_error: {e}"
                break

            tracker.add(result.get("cost_usd", 0), {"step": step, "type": "think", "model": result.get("model", "")})
            parsed = _parse_agent_response(result["text"])
            thought = parsed.get("thought", "")

            if "answer" in parsed:
                trace.append({"step": step, "thought": thought, "action": "final_answer", "params": {},
                              "result": parsed["answer"], "cost": result.get("cost_usd", 0), "model": result.get("model", "")})
                if agent_id and self.memory.get("set"):
                    try:
                        self.memory["set"](agent_id, f"task_result:{datetime.utcnow().isoformat()}", {
                            "task": task[:200], "answer": str(parsed["answer"])[:500], "steps": step, "cost": tracker.total})
                    except Exception:
                        pass
                return {"answer": parsed["answer"], "reasoning_trace": trace, "total_cost_usd": round(tracker.total, 6),
                        "steps_taken": step, "stop_reason": "completed", "memories_recalled": memories_recalled,
                        "model_selections": {t["step"]: t["model"] for t in tracker.steps}}

            action = parsed.get("action", "")
            params = parsed.get("params", {})

            if not action or action not in self.tools:
                observations.append({"step": step, "action": action or "unknown",
                                     "result": f"Error: unknown tool '{action}'."})
                trace.append({"step": step, "thought": thought, "action": action, "params": params,
                              "result": "error: unknown tool", "cost": result.get("cost_usd", 0), "model": result.get("model", "")})
                continue

            try:
                tool_result = self.handle_tool(action, params)
            except Exception as e:
                tool_result = {"error": str(e)}

            observations.append({"step": step, "action": action, "result": tool_result})
            trace.append({"step": step, "thought": thought, "action": action, "params": params,
                          "result": tool_result, "cost": result.get("cost_usd", 0), "model": result.get("model", "")})

        if stop_reason != "completed" or not trace:
            stop_reason = stop_reason if stop_reason != "completed" else "max_steps_reached"

        answer = _synthesize_answer(observations, task)
        return {"answer": answer, "reasoning_trace": trace, "total_cost_usd": round(tracker.total, 6),
                "steps_taken": len(trace), "stop_reason": stop_reason, "memories_recalled": memories_recalled,
                "model_selections": {t["step"]: t["model"] for t in tracker.steps}}

    def run_stream(self, task: str, max_steps: int = 10, max_cost_usd: float = 1.0,
                   model: str = "auto", agent_id: str = ""):
        """Generator that yields SSE events as the agent reasons."""
        from model_router import CostTracker
        tracker = CostTracker()
        observations = []
        max_steps = min(max_steps, 20)

        memories_text = "None"
        memories_recalled = 0
        if agent_id and self.memory.get("search"):
            try:
                mem_results = self.memory["search"](agent_id, task)
                if mem_results:
                    memories_text = "\n".join(f"- [{m.get('key', '')}]: {str(m.get('value', ''))[:200]}" for m in mem_results[:3])
                    memories_recalled = len(mem_results[:3])
            except Exception:
                pass

        for step in range(1, max_steps + 1):
            if not tracker.can_afford(0.001, max_cost_usd):
                yield {"event": "done", "data": {"reason": "budget_exhausted", "total_cost": tracker.total, "steps": step - 1}}
                return

            obs_text = "\n".join(f"Step {o['step']}: [{o['action']}] -> {str(o['result'])[:500]}" for o in observations) or "None yet."
            system = REACT_SYSTEM_PROMPT.format(tools=format_tools_for_prompt(self.tools), budget_remaining=tracker.remaining(max_cost_usd), memories=memories_text, observations=obs_text)

            user_msg = task if step == 1 else f"Continue. Step {step}/{max_steps}."
            try:
                result = self.call_model(model, [{"role": "user", "content": user_msg}], system=system, max_tokens=1024, temperature=0.3, max_cost_usd=tracker.remaining(max_cost_usd))
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
                yield {"event": "observation", "data": {"step": step, "action": action, "result": str(tool_result)[:300]}}
            else:
                observations.append({"step": step, "action": action, "result": f"Unknown tool: {action}"})
                yield {"event": "observation", "data": {"step": step, "action": action, "result": f"Error: unknown tool '{action}'"}}

        answer = _synthesize_answer(observations, task)
        yield {"event": "answer", "data": {"answer": answer}}
        yield {"event": "done", "data": {"reason": "max_steps_reached", "total_cost": round(tracker.total, 6), "steps": max_steps}}


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


def _synthesize_answer(observations: list, task: str) -> str:
    if not observations:
        return "I was unable to complete this task within the given constraints."
    parts = []
    for obs in observations:
        result = obs.get("result", "")
        if isinstance(result, dict):
            result = result.get("result") or result.get("summary") or str(result)
        parts.append(str(result)[:300])
    return f"Based on {len(observations)} steps:\n\n" + "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tool Handler Factory
# ---------------------------------------------------------------------------

def make_tool_handler(batch_handlers: dict, memory_search_fn, memory_set_fn,
                      skills_db_path: str, agent_id: str = ""):
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
