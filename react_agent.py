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
