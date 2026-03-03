"""
AiPayGent LangChain Tool
========================
Drop this file into any LangChain project to give your agent access to
80+ paid AI endpoints via x402 micropayments.

Install:
    pip install langchain-core requests

Usage:
    from langchain_tool import AiPayGentTool, AiPayGentToolkit
    from langchain.agents import AgentExecutor, create_openai_tools_agent

    tools = AiPayGentToolkit(x402_token="your_token").get_tools()
    agent = create_openai_tools_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools)

    result = executor.invoke({"input": "Research quantum computing and summarize it"})
"""

import os
import json
import requests
from typing import Optional, Type, Any

try:
    from langchain_core.tools import BaseTool
    from langchain_core.callbacks import CallbackManagerForToolRun
    from pydantic import BaseModel, Field
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

BASE_URL = os.getenv("AIPAYGENT_BASE_URL", "https://api.aipaygent.xyz")
DEFAULT_TOKEN = os.getenv("AIPAYGENT_TOKEN", "")


def _call(endpoint: str, payload: dict, token: str = "") -> dict:
    """Make an x402-authenticated request to AiPayGent."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Payment"] = token
    resp = requests.post(f"{BASE_URL}{endpoint}", json=payload, headers=headers, timeout=60)
    if resp.status_code == 402:
        return {"error": "payment_required", "payment_info": resp.json()}
    resp.raise_for_status()
    return resp.json()


def _call_get(endpoint: str, params: dict = None) -> dict:
    resp = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


if LANGCHAIN_AVAILABLE:
    class AiPayGentInput(BaseModel):
        query: str = Field(description="The main input query or text")
        extra: Optional[str] = Field(default=None, description="Optional extra parameter")

    class ResearchTool(BaseTool):
        """Research any topic using Claude AI — returns a detailed report."""
        name: str = "aipaygent_research"
        description: str = (
            "Research any topic and get a detailed, structured report. "
            "Use for: factual queries, market research, technology overviews, competitor analysis."
        )
        args_schema: Type[BaseModel] = AiPayGentInput
        token: str = DEFAULT_TOKEN

        def _run(self, query: str, extra: str = None,
                 run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
            result = _call("/research", {"query": query}, self.token)
            return result.get("result") or json.dumps(result)

    class SummarizeTool(BaseTool):
        """Summarize long text into concise bullets or paragraphs."""
        name: str = "aipaygent_summarize"
        description: str = (
            "Summarize long text. Input: the text to summarize. "
            "Returns a concise summary in bullet points."
        )
        args_schema: Type[BaseModel] = AiPayGentInput
        token: str = DEFAULT_TOKEN

        def _run(self, query: str, extra: str = None,
                 run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
            result = _call("/summarize", {"text": query, "format": "bullets"}, self.token)
            return result.get("result") or json.dumps(result)

    class AnalyzeTool(BaseTool):
        """Analyze text or content and answer a specific question about it."""
        name: str = "aipaygent_analyze"
        description: str = (
            "Analyze content and answer a question about it. "
            "Input query format: 'CONTENT ||| QUESTION'. "
            "Example: 'This quarter revenue grew 20% ||| What is the growth driver?'"
        )
        args_schema: Type[BaseModel] = AiPayGentInput
        token: str = DEFAULT_TOKEN

        def _run(self, query: str, extra: str = None,
                 run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
            if "|||" in query:
                content, question = query.split("|||", 1)
            else:
                content, question = query, extra or "Analyze this"
            result = _call("/analyze", {"text": content.strip(), "question": question.strip()}, self.token)
            return result.get("result") or json.dumps(result)

    class SentimentTool(BaseTool):
        """Detect sentiment (positive/negative/neutral) and emotion in text."""
        name: str = "aipaygent_sentiment"
        description: str = "Analyze sentiment of text. Returns positive/negative/neutral score and emotions."
        args_schema: Type[BaseModel] = AiPayGentInput
        token: str = DEFAULT_TOKEN

        def _run(self, query: str, extra: str = None,
                 run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
            result = _call("/sentiment", {"text": query}, self.token)
            return json.dumps(result.get("result") or result)

    class WebScrapeTool(BaseTool):
        """Scrape and extract content from any webpage URL."""
        name: str = "aipaygent_scrape_web"
        description: str = (
            "Scrape any webpage URL and extract clean text content. "
            "Input: a URL like https://example.com"
        )
        args_schema: Type[BaseModel] = AiPayGentInput
        token: str = DEFAULT_TOKEN

        def _run(self, query: str, extra: str = None,
                 run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
            result = _call("/scrape/web", {"url": query.strip()}, self.token)
            return json.dumps(result.get("result") or result)

    class CatalogTool(BaseTool):
        """Browse the AiPayGent API catalog — find APIs for any use case."""
        name: str = "aipaygent_catalog"
        description: str = (
            "Browse 200+ discovered APIs in the AiPayGent catalog. "
            "Input: category name like 'weather', 'finance', 'geo', 'health', or leave blank for all."
        )
        args_schema: Type[BaseModel] = AiPayGentInput

        def _run(self, query: str, extra: str = None,
                 run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
            params = {"min_score": 6, "per_page": 10}
            if query.strip():
                params["category"] = query.strip()
            result = _call_get("/catalog", params)
            apis = result.get("apis", [])
            return json.dumps([{"name": a["name"], "url": a["base_url"], "desc": a["description"][:100]} for a in apis])

    class ChainTool(BaseTool):
        """Chain multiple AI operations in sequence for complex multi-step tasks."""
        name: str = "aipaygent_chain"
        description: str = (
            "Run a sequence of AI operations. Input: JSON array of steps. "
            "Each step: {action: 'research'|'summarize'|'analyze'|..., params: {...}}. "
            "Output of each step feeds into the next via {{prev_result}}."
        )
        args_schema: Type[BaseModel] = AiPayGentInput
        token: str = DEFAULT_TOKEN

        def _run(self, query: str, extra: str = None,
                 run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
            try:
                steps = json.loads(query)
            except Exception:
                return '{"error": "query must be a JSON array of steps"}'
            result = _call("/chain", {"steps": steps}, self.token)
            final = result.get("result", {})
            return json.dumps(final.get("final_result") or final)

    class MemoryTool(BaseTool):
        """Store and retrieve persistent memories across agent sessions."""
        name: str = "aipaygent_memory"
        description: str = (
            "Persistent memory storage across sessions. "
            "To store: 'SET agent_id|key|value'. "
            "To retrieve: 'GET agent_id|key'. "
            "To search: 'SEARCH agent_id|query'."
        )
        args_schema: Type[BaseModel] = AiPayGentInput
        token: str = DEFAULT_TOKEN

        def _run(self, query: str, extra: str = None,
                 run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
            parts = query.split("|", 3)
            op = parts[0].strip().upper()
            if op == "SET" and len(parts) >= 4:
                result = _call("/memory/set", {"agent_id": parts[1], "key": parts[2], "value": parts[3]}, self.token)
            elif op == "GET" and len(parts) >= 3:
                result = _call("/memory/get", {"agent_id": parts[1], "key": parts[2]}, self.token)
            elif op == "SEARCH" and len(parts) >= 3:
                result = _call("/memory/search", {"agent_id": parts[1], "query": parts[2]}, self.token)
            else:
                return '{"error": "Format: SET agent_id|key|value OR GET agent_id|key OR SEARCH agent_id|query"}'
            return json.dumps(result)

    class AiPayGentToolkit:
        """Full toolkit of AiPayGent tools for LangChain agents."""

        def __init__(self, x402_token: str = DEFAULT_TOKEN):
            self.token = x402_token

        def get_tools(self) -> list:
            kwargs = {"token": self.token}
            return [
                ResearchTool(**kwargs),
                SummarizeTool(**kwargs),
                AnalyzeTool(**kwargs),
                SentimentTool(**kwargs),
                WebScrapeTool(**kwargs),
                ChainTool(**kwargs),
                MemoryTool(**kwargs),
                CatalogTool(),
            ]

        def get_free_tools(self) -> list:
            """Tools that don't require x402 payment."""
            return [CatalogTool()]


def demo():
    """Quick test of free endpoints."""
    print("Testing free endpoints...")
    time_result = _call_get("/free/time")
    print(f"Server time: {time_result.get('utc')}")

    catalog = _call_get("/catalog", {"min_score": 8, "per_page": 3})
    apis = catalog.get("apis", [])
    print(f"Top APIs in catalog: {[a['name'] for a in apis]}")
    print("OK — install langchain-core to use LangChain tools")


if __name__ == "__main__":
    demo()
