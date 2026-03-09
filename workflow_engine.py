"""Multi-step workflow engine — chains AI tools together with 15% discount."""

import time
import json
import requests as _requests

# Every tool name the platform supports
KNOWN_TOOLS = {
    "research", "scrape", "search", "write", "analyze", "code", "summarize",
    "translate", "sentiment", "classify", "extract", "compare", "explain",
    "plan", "decide", "debate", "proofread", "rewrite", "pitch", "headline",
    "keywords", "tag", "questions", "score", "outline", "timeline", "diagram",
    "social", "mock", "test_cases", "json_schema", "regex", "sql", "fact",
    "vision", "qa", "rag", "batch", "chain_operations", "pipeline", "workflow",
    "action", "email", "transform", "chat", "review-code", "generate-docs",
    "convert-code", "generate-api-spec", "diff", "parse-csv", "cron",
    "changelog", "name-generator", "privacy-check", "think", "enrich",
}

MAX_STEPS = 10
DISCOUNT_PERCENT = 15

# Tools that can generate content without prior input
GENERATIVE_TOOLS = {
    "research", "search", "scrape", "code", "write", "mock", "plan",
    "email", "sql", "regex", "json_schema", "test_cases", "outline",
    "headline", "pitch", "diagram", "cron", "changelog", "name-generator",
    "think", "enrich", "social",
}


def validate_workflow(steps: list) -> list[str]:
    """Return list of error strings. Empty list means valid."""
    errors = []
    if not steps:
        errors.append("Workflow must have at least 1 step")
        return errors
    if len(steps) > MAX_STEPS:
        errors.append(f"Workflow exceeds maximum of {MAX_STEPS} steps (got {len(steps)})")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"Step {i+1}: must be a JSON object")
            continue
        tool = step.get("tool")
        if not tool:
            errors.append(f"Step {i+1}: missing 'tool' field")
            continue
        if tool not in KNOWN_TOOLS:
            errors.append(f"Step {i+1}: unknown tool '{tool}'")
    # First step must have explicit input (nothing to pipe from)
    if steps and isinstance(steps[0], dict) and steps[0].get("tool"):
        has_input = bool(steps[0].get("input"))
        tool = steps[0]["tool"]
        if not has_input and tool not in GENERATIVE_TOOLS:
            errors.append(f"Step 1: tool '{tool}' requires explicit input (nothing to pipe from)")
    return errors


def execute_workflow(steps: list, app_client=None) -> dict:
    """Execute workflow steps sequentially, piping output from one step to the next.

    Args:
        steps: validated list of step dicts with 'tool' and optional 'input'
        app_client: Flask test client (for testing). If None, uses requests to localhost.

    Returns:
        dict with 'steps' results, 'total_time_ms', 'discount_applied'
    """
    results = []
    prev_output = None
    t0 = time.time()

    for i, step in enumerate(steps):
        tool = step["tool"]
        explicit_input = step.get("input") or {}

        # Build input: merge previous output into current input
        if prev_output and isinstance(prev_output, dict):
            # Previous output becomes base, explicit input overrides
            step_input = {**prev_output, **explicit_input}
        else:
            step_input = explicit_input
            if prev_output and isinstance(prev_output, str):
                # If previous output was raw text, inject as 'text' key
                step_input.setdefault("text", prev_output)

        # Normalise tool name for URL (underscores -> hyphens)
        url_tool = tool.replace("_", "-")
        step_t0 = time.time()

        try:
            if app_client:
                resp = app_client.post(f"/{url_tool}", json=step_input)
                status = resp.status_code
                try:
                    body = resp.get_json()
                except Exception:
                    body = {"raw": resp.data.decode("utf-8", errors="replace")}
            else:
                resp = _requests.post(
                    f"http://127.0.0.1:5001/{url_tool}",
                    json=step_input,
                    timeout=60,
                )
                status = resp.status_code
                try:
                    body = resp.json()
                except Exception:
                    body = {"raw": resp.text}

            step_ms = round((time.time() - step_t0) * 1000)
            step_result = {
                "step": i + 1,
                "tool": tool,
                "status": status,
                "time_ms": step_ms,
                "output": body,
            }
            results.append(step_result)

            # If step failed, stop the chain
            if status >= 400:
                step_result["error"] = f"Step {i+1} failed with status {status}"
                break

            prev_output = body

        except Exception as exc:
            step_ms = round((time.time() - step_t0) * 1000)
            results.append({
                "step": i + 1,
                "tool": tool,
                "status": 500,
                "time_ms": step_ms,
                "error": str(exc),
            })
            break

    total_ms = round((time.time() - t0) * 1000)
    return {
        "steps": results,
        "total_steps": len(results),
        "total_time_ms": total_ms,
        "discount_applied": f"{DISCOUNT_PERCENT}%",
    }
