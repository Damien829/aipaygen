"""Agent Tools — memory, registry, messaging, knowledge base, task board, builder."""

import os
from typing import Annotated
from pydantic import Field

from mcp_tools import (
    mcp, metered_tool, _log,
    memory_set, memory_get, memory_search, memory_list,
    register_agent, list_agents,
    send_message, get_inbox, add_knowledge, search_knowledge,
    get_trending_topics, browse_tasks,
)
import requests as _mcp_requests


# ── Agent Memory Tools ───────────────────────────────────────────────────────

@metered_tool("standard")
def memory_store(agent_id: Annotated[str, Field(description="Stable agent identifier (UUID, DID, or name)")], key: Annotated[str, Field(description="Memory key to store under")], value: Annotated[str, Field(description="Value to store")], tags: Annotated[str, Field(description="Comma-separated tags for organization")] = "") -> dict:
    """
    Store a persistent memory for an agent. Survives across sessions.
    agent_id: stable identifier for your agent (UUID, DID, or name).
    tags: comma-separated (optional).
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    return memory_set(agent_id, key, value, tag_list)


@metered_tool("standard")
def memory_recall(agent_id: Annotated[str, Field(description="Agent identifier to recall memory for")], key: Annotated[str, Field(description="Memory key to retrieve")]) -> dict:
    """Retrieve a stored memory by agent_id and key. Returns value, tags, and timestamps."""
    result = memory_get(agent_id, key)
    return result or {"error": "not_found", "agent_id": agent_id, "key": key}


@metered_tool("standard")
def memory_find(agent_id: Annotated[str, Field(description="Agent identifier to search memories for")], query: Annotated[str, Field(description="Keyword to search across memories")]) -> dict:
    """Search all memories for an agent by keyword. Returns ranked matching key-value pairs."""
    results = memory_search(agent_id, query)
    return {"agent_id": agent_id, "query": query, "results": results, "count": len(results)}


@metered_tool("standard")
def memory_keys(agent_id: Annotated[str, Field(description="Agent identifier to list memory keys for")]) -> dict:
    """List all memory keys stored for an agent, with tags and last-updated timestamps."""
    return {"agent_id": agent_id, "keys": memory_list(agent_id)}


# ── Agent Registry Tools ─────────────────────────────────────────────────────

@metered_tool("standard")
def register_my_agent(agent_id: Annotated[str, Field(description="Unique agent identifier")], name: Annotated[str, Field(description="Display name for the agent")], description: Annotated[str, Field(description="What the agent does")],
                      capabilities: Annotated[str, Field(description="Comma-separated list of capabilities")], endpoint: Annotated[str, Field(description="URL where other agents can reach you")] = "") -> dict:
    """
    Register your agent in the AiPayGen agent registry.
    capabilities: comma-separated list of what your agent can do.
    endpoint: optional URL where other agents can reach you.
    """
    cap_list = [c.strip() for c in capabilities.split(",") if c.strip()]
    return register_agent(agent_id, name, description, cap_list, endpoint or None)


@metered_tool("standard")
def list_registered_agents() -> dict:
    """Browse all agents registered in the AiPayGen registry."""
    agents = list_agents()
    return {"agents": agents, "count": len(agents)}


# ── Agent Messaging ──────────────────────────────────────────────────────────

@metered_tool("standard")
def send_agent_message(from_agent: Annotated[str, Field(description="Sender agent ID")], to_agent: Annotated[str, Field(description="Recipient agent ID")], subject: Annotated[str, Field(description="Message subject line")], body: Annotated[str, Field(description="Message body text")]) -> dict:
    """Send a direct message from one agent to another via the agent network."""
    return send_message(from_agent, to_agent, subject, body)


@metered_tool("standard")
def read_agent_inbox(agent_id: Annotated[str, Field(description="Agent ID to read inbox for")], unread_only: Annotated[bool, Field(description="Only return unread messages")] = False) -> dict:
    """Read messages from an agent's inbox. Set unread_only=True to filter."""
    messages = get_inbox(agent_id, unread_only=unread_only)
    return {"agent_id": agent_id, "messages": messages, "count": len(messages)}


# ── Knowledge Base ───────────────────────────────────────────────────────────

@metered_tool("standard")
def add_to_knowledge_base(topic: Annotated[str, Field(description="Topic or title for the knowledge entry")], content: Annotated[str, Field(description="Knowledge content to store")], author_agent: Annotated[str, Field(description="Agent ID of the author")],
                          tags: Annotated[list, Field(description="Tags for categorization")] = None) -> dict:
    """Add an entry to the shared agent knowledge base."""
    return add_knowledge(topic, content, author_agent, tags or [])


@metered_tool("standard")
def search_knowledge_base(query: Annotated[str, Field(description="Search keyword for the knowledge base")], limit: Annotated[int, Field(description="Maximum number of results")] = 10) -> dict:
    """Search the shared agent knowledge base by keyword."""
    results = search_knowledge(query, limit=limit)
    return {"query": query, "results": results, "count": len(results)}


@metered_tool("standard")
def get_trending_knowledge() -> dict:
    """Get the most popular topics in the shared agent knowledge base."""
    topics = get_trending_topics(limit=10)
    return {"trending": topics}


# ── Task Board ───────────────────────────────────────────────────────────────

@metered_tool("standard")
def submit_agent_task(posted_by: Annotated[str, Field(description="Agent ID posting the task")], title: Annotated[str, Field(description="Task title")], description: Annotated[str, Field(description="Detailed task description")],
                      skills_needed: Annotated[list, Field(description="List of skills required for the task")] = None, reward_usd: Annotated[float, Field(description="Reward amount in USD")] = 0.0) -> dict:
    """Post a task to the agent task board for other agents to claim and complete."""
    from agent_network import submit_task as _submit_task
    return _submit_task(posted_by, title, description, skills_needed or [], reward_usd)


@metered_tool("standard")
def browse_agent_tasks(status: Annotated[str, Field(description="Task status filter: open, claimed, completed")] = "open", skill: Annotated[str, Field(description="Filter by required skill")] = None) -> dict:
    """Browse tasks on the agent task board, optionally filtered by skill or status."""
    tasks = browse_tasks(status=status, skill=skill)
    return {"tasks": tasks, "count": len(tasks)}


# ── Agent Builder & Management ───────────────────────────────────────────────

@metered_tool("standard")
def create_agent(name: Annotated[str, Field(description="Name for the custom agent")], description: Annotated[str, Field(description="What the agent does")], tools: Annotated[list, Field(description="List of tool names the agent can use")] = None,
                 template: Annotated[str, Field(description="Agent template: research, monitor, content, sales, etc.")] = "", model: Annotated[str, Field(description="AI model to use, or auto for best fit")] = "auto") -> dict:
    """Create a custom AI agent with selected tools and configuration."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/agents/build",
            json={"name": name, "description": description,
                  "tools": tools or [], "template": template, "model": model},
            timeout=30)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def list_my_agents() -> dict:
    """List all agents you have created. Requires AIPAYGEN_API_KEY env var."""
    api_key = os.environ.get("AIPAYGEN_API_KEY", "")
    try:
        resp = _mcp_requests.get("http://localhost:5001/agents/list",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("ai")
def run_agent(agent_id: Annotated[str, Field(description="ID of the agent to run")], input_text: Annotated[str, Field(description="Input text or prompt for the agent")] = "") -> dict:
    """Run a custom agent by ID with optional input text."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/run",
            json={"input": input_text}, timeout=120)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def schedule_agent(agent_id: Annotated[str, Field(description="ID of the agent to schedule")], schedule_type: Annotated[str, Field(description="Schedule type: cron, loop, or event")] = "cron",
                   schedule_value: Annotated[str, Field(description="Schedule value (cron expression, interval, or event name)")] = "") -> dict:
    """Schedule an agent to run automatically. schedule_type: cron | loop | event."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/schedule",
            json={"schedule_type": schedule_type, "schedule_value": schedule_value},
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def pause_agent(agent_id: Annotated[str, Field(description="ID of the agent to pause")]) -> dict:
    """Pause a scheduled agent."""
    try:
        resp = _mcp_requests.post(f"http://localhost:5001/agents/{agent_id}/pause",
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def get_agent_runs(agent_id: Annotated[str, Field(description="ID of the agent to get run history for")]) -> dict:
    """Get execution history for an agent."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/agents/{agent_id}/runs",
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def delete_agent(agent_id: Annotated[str, Field(description="ID of the agent to delete")]) -> dict:
    """Delete a custom agent by ID."""
    try:
        resp = _mcp_requests.delete(f"http://localhost:5001/agents/{agent_id}",
            timeout=10)
        return resp.json()
    except Exception:
        _log.exception("Tool execution failed")
        return {"error": "Tool execution failed"}


# ── Agent Network Extended ───────────────────────────────────────────────────

@metered_tool("standard")
def agent_leaderboard() -> dict:
    """View the agent leaderboard ranked by reputation and activity."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/agents/leaderboard", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def agent_search(query: Annotated[str, Field(description="Search query for finding agents")]) -> dict:
    """Search the agent network for agents matching a query."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/agents/search", params={"q": query}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def agent_portfolio(agent_id: Annotated[str, Field(description="Agent ID to view portfolio for")]) -> dict:
    """View an agent's portfolio: services, reputation, and history."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/agents/{agent_id}/portfolio", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def agent_reputation(agent_id: Annotated[str, Field(description="Agent ID to check reputation for")]) -> dict:
    """Check an agent's reputation score and history."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/agent/reputation/{agent_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Task Board Extended ──────────────────────────────────────────────────────

@metered_tool("standard")
def task_claim(task_id: Annotated[str, Field(description="Task ID to claim")], agent_id: Annotated[str, Field(description="Your agent ID")]) -> dict:
    """Claim an open task from the task board."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/task/claim", json={"task_id": task_id, "agent_id": agent_id}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def task_complete(task_id: Annotated[str, Field(description="Task ID to mark complete")], result: Annotated[str, Field(description="Task result or deliverable")] = "") -> dict:
    """Mark a claimed task as completed with results."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/task/complete", json={"task_id": task_id, "result": result}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def task_subscribe(agent_id: Annotated[str, Field(description="Your agent ID")], skill: Annotated[str, Field(description="Skill to subscribe to for task notifications")]) -> dict:
    """Subscribe to task board notifications for a specific skill."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/task/subscribe", json={"agent_id": agent_id, "skill": skill}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Agent Verification ───────────────────────────────────────────────────────

@metered_tool("standard")
def agent_verify(agent_id: Annotated[str, Field(description="Agent ID to verify")]) -> dict:
    """Verify an agent's identity via challenge-response."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/agents/verify", json={"agent_id": agent_id}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Builder Templates ────────────────────────────────────────────────────────

@metered_tool("standard")
def builder_templates() -> dict:
    """List all available agent builder templates (research, monitor, content, sales, etc.)."""
    try:
        resp = _mcp_requests.get("http://localhost:5001/builder/templates", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Session / Conversation Management ────────────────────────────────────────

@metered_tool("standard")
def session_start(agent_id: Annotated[str, Field(description="Agent ID starting the session")] = "default", context: Annotated[str, Field(description="Initial session context or system prompt")] = "") -> dict:
    """Start a persistent conversation session with context tracking."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/session/start", json={"agent_id": agent_id, "context": context}, timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def session_context(session_id: Annotated[str, Field(description="Session ID to retrieve context for")]) -> dict:
    """Get the current context and history of a conversation session."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/session/{session_id}/context", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Streaming AI Tools ───────────────────────────────────────────────────────

@metered_tool("standard")
def stream_research(topic: Annotated[str, Field(description="Topic to research with streaming output")]) -> dict:
    """Research a topic with streaming output for real-time results."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/stream/research", json={"topic": topic}, timeout=60)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def stream_write(spec: Annotated[str, Field(description="Writing specification or prompt")]) -> dict:
    """Generate long-form writing with streaming output."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/stream/write", json={"spec": spec}, timeout=60)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def stream_analyze(content: Annotated[str, Field(description="Content to analyze with streaming output")]) -> dict:
    """Analyze content with streaming output for real-time results."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/stream/analyze", json={"content": content}, timeout=60)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


# ── Async Jobs ───────────────────────────────────────────────────────────────

@metered_tool("standard")
def async_submit(endpoint: Annotated[str, Field(description="API endpoint to run asynchronously (e.g. /research)")], params: Annotated[dict, Field(description="Parameters for the endpoint")] = None) -> dict:
    """Submit a long-running task for async execution. Returns a job_id for polling."""
    try:
        resp = _mcp_requests.post("http://localhost:5001/async/submit", json={"endpoint": endpoint, "params": params or {}}, timeout=15)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}


@metered_tool("standard")
def async_status(job_id: Annotated[str, Field(description="Job ID from async_submit")]) -> dict:
    """Check the status and result of an async job."""
    try:
        resp = _mcp_requests.get(f"http://localhost:5001/async/status/{job_id}", timeout=10)
        return resp.json()
    except Exception:
        return {"error": "Tool execution failed"}
