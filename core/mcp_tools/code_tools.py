"""Code Tools — code generation, test cases, SQL, regex, JSON schema."""

from typing import Annotated
from pydantic import Field

from mcp_tools import (
    mcp, metered_tool, _log,
    code_inner, sql_inner, regex_inner, mock_inner,
    email_inner, proofread_inner, rewrite_inner, tag_inner,
)
import requests as _mcp_requests


@metered_tool("ai")
def code(description: Annotated[str, Field(description="Plain-English description of the code to generate")], language: Annotated[str, Field(description="Programming language for the generated code")] = "Python") -> dict:
    """Generate production-ready code in any language from a plain-English description."""
    return code_inner(description, language)


@metered_tool("ai")
def sql(description: Annotated[str, Field(description="Natural language description of the SQL query")], dialect: Annotated[str, Field(description="SQL dialect: postgresql, mysql, sqlite, etc.")] = "postgresql", schema: Annotated[str, Field(description="Database schema description for context")] = "") -> dict:
    """Natural language to SQL. Returns query, explanation, and notes."""
    return sql_inner(description, dialect, schema)


@metered_tool("ai")
def regex(description: Annotated[str, Field(description="Plain-English description of the pattern to match")], language: Annotated[str, Field(description="Target programming language for the regex")] = "python", flags: Annotated[str, Field(description="Regex flags like i, m, s")] = "") -> dict:
    """Generate a regex pattern from a plain-English description with examples."""
    return regex_inner(description, language, flags)


@metered_tool("ai")
def mock(description: Annotated[str, Field(description="Description of the mock data to generate")], count: Annotated[int, Field(description="Number of mock records to generate")] = 5, format: Annotated[str, Field(description="Output format: json, csv, or list")] = "json") -> dict:
    """Generate realistic mock data records. format: json | csv | list"""
    return mock_inner(description, min(count, 50), format)


# ── Code Execution ───────────────────────────────────────────────────────────

@metered_tool("standard")
def run_python_code(code: Annotated[str, Field(description="Python code to execute in sandbox")], timeout: Annotated[int, Field(description="Execution timeout in seconds (max 15)")] = 10) -> dict:
    """Execute Python code in a sandboxed subprocess. Returns stdout, stderr, returncode.
    Imports, file I/O, network access, and OS commands are blocked."""
    import subprocess
    import time as _time
    from security import validate_code_safety, SandboxViolation, get_sandbox_env
    if len(code) > 5000:
        return {"error": "code too long (max 5000 chars)"}
    try:
        validate_code_safety(code)
    except SandboxViolation as e:
        return {"error": f"Sandbox violation: {e}"}
    timeout = min(timeout, 15)
    start = _time.time()
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=get_sandbox_env(),
            cwd="/tmp",
        )
        return {
            "stdout": result.stdout[:3000],
            "stderr": result.stderr[:500],
            "returncode": result.returncode,
            "execution_time_ms": int((_time.time() - start) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "message": f"Code exceeded {timeout}s limit"}
