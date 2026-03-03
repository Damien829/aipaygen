"""
AiPayGent LlamaIndex Tool
=========================
Drop this file into any LlamaIndex project to give your agent access to
80+ paid AI endpoints via x402 micropayments.

Install:
    pip install llama-index-core requests

Usage:
    from aipaygent_llamaindex import AiPayGentToolSpec

    tool_spec = AiPayGentToolSpec(x402_token="your_token")
    tools = tool_spec.to_tool_list()

    from llama_index.core.agent import ReActAgent
    from llama_index.llms.anthropic import Anthropic

    llm = Anthropic(model="claude-haiku-4-5-20251001")
    agent = ReActAgent.from_tools(tools, llm=llm, verbose=True)

    response = agent.chat("Research quantum computing and give me a summary")
"""

import os
import json
import requests
from typing import Optional

BASE_URL = os.getenv("AIPAYGENT_BASE_URL", "https://api.aipaygent.xyz")
DEFAULT_TOKEN = os.getenv("AIPAYGENT_TOKEN", "")


def _call(endpoint: str, payload: dict, token: str = "") -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Payment"] = token
    resp = requests.post(f"{BASE_URL}{endpoint}", json=payload, headers=headers, timeout=60)
    if resp.status_code == 402:
        return {"error": "payment_required", "info": resp.json()}
    resp.raise_for_status()
    return resp.json()


def _call_get(endpoint: str, params: dict = None) -> dict:
    resp = requests.get(f"{BASE_URL}{endpoint}", params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


try:
    from llama_index.core.tools import FunctionTool
    from llama_index.core.tools.tool_spec.base import BaseToolSpec
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False
    BaseToolSpec = object


class AiPayGentToolSpec(BaseToolSpec):
    """LlamaIndex ToolSpec for AiPayGent — 80+ AI endpoints via x402."""

    spec_functions = [
        "research", "summarize", "analyze", "sentiment",
        "translate", "extract_keywords", "classify",
        "scrape_web", "scrape_tweets", "scrape_google_maps",
        "get_catalog", "memory_set", "memory_get", "memory_search",
        "chain_operations", "generate_diagram", "get_time",
    ]

    def __init__(self, x402_token: str = DEFAULT_TOKEN):
        self.token = x402_token

    def research(self, query: str) -> str:
        """
        Research any topic using Claude AI.
        Returns a detailed, structured report.
        Args:
            query: The topic or question to research
        """
        result = _call("/research", {"query": query}, self.token)
        return result.get("result", json.dumps(result))

    def summarize(self, text: str, format: str = "bullets") -> str:
        """
        Summarize long text into a concise format.
        Args:
            text: The text to summarize (can be very long)
            format: Output format — 'bullets', 'paragraph', or 'tldr'
        """
        result = _call("/summarize", {"text": text, "format": format}, self.token)
        return result.get("result", json.dumps(result))

    def analyze(self, text: str, question: str) -> str:
        """
        Analyze content and answer a specific question about it.
        Args:
            text: The content to analyze
            question: The specific question to answer about the content
        """
        result = _call("/analyze", {"text": text, "question": question}, self.token)
        return result.get("result", json.dumps(result))

    def sentiment(self, text: str) -> str:
        """
        Detect sentiment and emotions in text.
        Args:
            text: The text to analyze for sentiment
        Returns JSON with score, label (positive/negative/neutral), and emotions.
        """
        result = _call("/sentiment", {"text": text}, self.token)
        return json.dumps(result.get("result", result))

    def translate(self, text: str, language: str) -> str:
        """
        Translate text to any language.
        Args:
            text: The text to translate
            language: Target language name (e.g., 'Spanish', 'French', 'Japanese')
        """
        result = _call("/translate", {"text": text, "language": language}, self.token)
        return result.get("result", json.dumps(result))

    def extract_keywords(self, text: str, n: int = 10) -> str:
        """
        Extract top keywords and key phrases from text.
        Args:
            text: The text to extract keywords from
            n: Number of keywords to return (default 10)
        """
        result = _call("/keywords", {"text": text, "n": n}, self.token)
        keywords = result.get("result", {})
        if isinstance(keywords, dict):
            return json.dumps(keywords.get("keywords", keywords))
        return json.dumps(keywords)

    def classify(self, text: str, categories: list) -> str:
        """
        Classify text into one of the provided categories.
        Args:
            text: The text to classify
            categories: List of possible category strings
        """
        result = _call("/classify", {"text": text, "categories": categories}, self.token)
        return json.dumps(result.get("result", result))

    def scrape_web(self, url: str) -> str:
        """
        Scrape and extract clean text content from any webpage.
        Args:
            url: Full URL to scrape (e.g., https://example.com)
        """
        result = _call("/scrape/web", {"url": url}, self.token)
        return json.dumps(result.get("result", result))

    def scrape_tweets(self, query: str, max_items: int = 25) -> str:
        """
        Search and scrape tweets matching a query.
        Args:
            query: Search query or hashtag
            max_items: Maximum number of tweets to return (max 25)
        """
        result = _call("/scrape/tweets", {"query": query, "max_items": max_items}, self.token)
        return json.dumps(result.get("result", result))

    def scrape_google_maps(self, query: str, max_items: int = 5) -> str:
        """
        Search Google Maps and return business listings.
        Args:
            query: Search query (e.g., 'coffee shops in NYC', 'dentists near Brooklyn')
            max_items: Maximum number of places to return (max 10)
        """
        result = _call("/scrape/google-maps", {"query": query, "max_items": max_items}, self.token)
        return json.dumps(result.get("result", result))

    def get_catalog(self, category: str = None, min_score: float = 6.0) -> str:
        """
        Browse 200+ discovered APIs in the AiPayGent catalog.
        Args:
            category: Filter by category (weather, finance, geo, health, etc.) or None for all
            min_score: Minimum quality score 0-10 (default 6.0)
        Returns a list of APIs with name, URL, and description.
        """
        params = {"min_score": min_score, "per_page": 20}
        if category:
            params["category"] = category
        result = _call_get("/catalog", params)
        apis = result.get("apis", [])
        return json.dumps([{
            "name": a["name"],
            "url": a["base_url"],
            "description": a.get("description", "")[:150],
            "auth_required": a.get("auth_required", False),
            "category": a.get("category"),
        } for a in apis])

    def memory_set(self, agent_id: str, key: str, value: str) -> str:
        """
        Store a persistent memory value for an agent (survives across sessions).
        Args:
            agent_id: Unique identifier for this agent
            key: Memory key (like a variable name)
            value: Value to store (string, will be preserved exactly)
        """
        result = _call("/memory/set", {"agent_id": agent_id, "key": key, "value": value}, self.token)
        return json.dumps(result)

    def memory_get(self, agent_id: str, key: str) -> str:
        """
        Retrieve a stored memory value.
        Args:
            agent_id: Agent identifier used when storing
            key: The memory key to retrieve
        """
        result = _call("/memory/get", {"agent_id": agent_id, "key": key}, self.token)
        if result:
            return json.dumps(result.get("value", result))
        return "null"

    def memory_search(self, agent_id: str, query: str) -> str:
        """
        Search all memories for an agent by keyword.
        Args:
            agent_id: Agent identifier
            query: Search query to match against keys and values
        """
        result = _call("/memory/search", {"agent_id": agent_id, "query": query}, self.token)
        return json.dumps(result.get("result", result))

    def chain_operations(self, steps_json: str) -> str:
        """
        Chain multiple AI operations in sequence. Output of each step is available to next.
        Args:
            steps_json: JSON array of steps, each with 'action' and 'params'.
            Available actions: research, summarize, analyze, sentiment, keywords, classify,
                              rewrite, extract, qa, compare, outline, diagram, json_schema, workflow.
            Use {{prev_result}} in params to reference previous step's output.
            Example: '[{"action":"research","params":{"query":"AI trends"}},
                       {"action":"summarize","params":{"text":"{{prev_result}}"}}]'
        """
        try:
            steps = json.loads(steps_json)
        except Exception:
            return '{"error": "steps_json must be valid JSON array"}'
        result = _call("/chain", {"steps": steps}, self.token)
        return json.dumps(result.get("result", {}).get("final_result") or result)

    def generate_diagram(self, description: str, diagram_type: str = "flowchart") -> str:
        """
        Generate a Mermaid diagram from a text description.
        Args:
            description: What the diagram should show
            diagram_type: One of: flowchart, sequence, erd, gantt, mindmap, classDiagram
        Returns Mermaid diagram syntax ready to render.
        """
        result = _call("/diagram", {"description": description, "diagram_type": diagram_type}, self.token)
        return result.get("result", json.dumps(result))

    def get_time(self) -> str:
        """Get current UTC time, Unix timestamp, and date. Free, no payment needed."""
        result = _call_get("/free/time")
        return json.dumps(result)


def demo():
    """Quick test without LlamaIndex installed."""
    print("Testing AiPayGentToolSpec free methods...")
    spec = AiPayGentToolSpec()
    print(spec.get_time())
    print(spec.get_catalog("weather", min_score=7.0))
    print("OK")


if __name__ == "__main__":
    demo()
