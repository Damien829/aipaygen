"""AI Processing Tools — research, summarize, analyze, translate, chat, vision, RAG, etc."""

import os
from typing import Annotated
from pydantic import Field

from mcp_tools import (
    mcp, metered_tool, _premium_gate, _log,
    research_inner, summarize_inner, analyze_inner, translate_inner,
    social_inner, write_inner, extract_inner, qa_inner,
    classify_inner, sentiment_inner, keywords_inner, compare_inner,
    transform_inner, chat_inner, plan_inner, decide_inner,
    explain_inner, questions_inner, outline_inner,
    score_inner, timeline_inner, action_inner,
    pitch_inner, debate_inner, headline_inner, fact_inner,
    think_inner, review_code_inner, generate_docs_inner,
    convert_code_inner, generate_api_spec_inner, diff_inner, parse_csv_inner,
    cron_expr_inner, changelog_inner, name_generator_inner, privacy_check_inner,
    pipeline_inner, BATCH_HANDLERS,
    vision_inner, rag_inner, diagram_inner, json_schema_inner,
    test_cases_inner, workflow_inner,
)


# ── AI Processing Tools (34 core + 6 advanced) ──────────────────────────────

@metered_tool("ai")
def research(topic: Annotated[str, Field(description="The topic to research")]) -> dict:
    """Research a topic. Returns structured summary, key points, and sources to check."""
    gate = _premium_gate("research", "$0.15/call")
    if gate:
        return gate
    return research_inner(topic)


@metered_tool("ai")
def summarize(text: Annotated[str, Field(description="The text to summarize")], length: Annotated[str, Field(description="Summary length: short, medium, or detailed")] = "short") -> dict:
    """Summarize long text. length: short | medium | detailed"""
    result = summarize_inner(text, length)
    if not os.environ.get("AIPAYGEN_API_KEY", ""):
        if isinstance(result, dict) and "summary" in result:
            full = result["summary"]
            result["summary"] = full[:100] + "..."
            result["_truncated"] = True
            result["_full_result_hint"] = "Preview only. Call generate_api_key() for full results."
    return result


@metered_tool("ai")
def analyze(content: Annotated[str, Field(description="Content to analyze")], question: Annotated[str, Field(description="Specific analysis question or focus area")] = "Provide a structured analysis") -> dict:
    """Deep structured analysis of content. Returns conclusion, findings, sentiment, confidence."""
    result = analyze_inner(content, question)
    if not os.environ.get("AIPAYGEN_API_KEY", ""):
        if isinstance(result, dict):
            for key in ("conclusion", "analysis", "result"):
                if key in result and isinstance(result[key], str):
                    result[key] = result[key][:200] + "..."
                    break
            result["_truncated"] = True
            result["_full_result_hint"] = "Preview only. Call generate_api_key() for full results."
    return result


@metered_tool("ai")
def translate(text: Annotated[str, Field(description="Text to translate")], language: Annotated[str, Field(description="Target language for translation")] = "Spanish") -> dict:
    """Translate text to any language."""
    return translate_inner(text, language)


@metered_tool("ai")
def social(topic: Annotated[str, Field(description="Topic or content for social media posts")], platforms: Annotated[list[str], Field(description="Target platforms: twitter, linkedin, instagram, etc.")] = None, tone: Annotated[str, Field(description="Post tone: engaging, professional, casual, humorous")] = "engaging") -> dict:
    """Generate platform-optimized social media posts for Twitter, LinkedIn, Instagram, etc."""
    return social_inner(topic, platforms or ["twitter", "linkedin", "instagram"], tone)


@metered_tool("ai")
def write(spec: Annotated[str, Field(description="Writing specification or prompt")], type: Annotated[str, Field(description="Content type: article, post, or copy")] = "article") -> dict:
    """Write articles, copy, or content to your specification. type: article | post | copy"""
    return write_inner(spec, type)


@metered_tool("ai")
def extract(text: Annotated[str, Field(description="Unstructured text to extract data from")], fields: Annotated[list[str], Field(description="List of field names to extract")] = None, schema: Annotated[str, Field(description="Schema description for extraction format")] = "") -> dict:
    """Extract structured data from unstructured text. Define fields or a schema."""
    return extract_inner(text, schema, fields or [])


@metered_tool("ai")
def qa(context: Annotated[str, Field(description="Document or context to answer from")], question: Annotated[str, Field(description="Question to answer based on the context")]) -> dict:
    """Q&A over a document. Returns answer, confidence score, and source quote."""
    return qa_inner(context, question)


@metered_tool("ai")
def classify(text: Annotated[str, Field(description="Text to classify")], categories: Annotated[list[str], Field(description="List of categories to classify into")]) -> dict:
    """Classify text into your defined categories with per-category confidence scores."""
    return classify_inner(text, categories)


@metered_tool("ai")
def sentiment(text: Annotated[str, Field(description="Text to analyze sentiment of")]) -> dict:
    """Deep sentiment analysis: polarity, score, emotions, confidence, key phrases."""
    return sentiment_inner(text)


@metered_tool("ai")
def keywords(text: Annotated[str, Field(description="Text to extract keywords from")], max_keywords: Annotated[int, Field(description="Maximum number of keywords to return")] = 10) -> dict:
    """Extract keywords, topics, and tags from any text."""
    return keywords_inner(text, max_keywords)


@metered_tool("ai")
def compare(text_a: Annotated[str, Field(description="First text to compare")], text_b: Annotated[str, Field(description="Second text to compare")], focus: Annotated[str, Field(description="Specific aspect to focus comparison on")] = "") -> dict:
    """Compare two texts: similarities, differences, similarity score, recommendation."""
    return compare_inner(text_a, text_b, focus)


@metered_tool("ai")
def transform(text: Annotated[str, Field(description="Text to transform")], instruction: Annotated[str, Field(description="Transformation instruction: rewrite, reformat, expand, etc.")]) -> dict:
    """Transform text with any instruction: rewrite, reformat, expand, condense, change tone."""
    return transform_inner(text, instruction)


@metered_tool("ai")
def chat(messages: Annotated[list[dict], Field(description="Message history as list of {role, content} dicts")], system: Annotated[str, Field(description="System prompt to set behavior")] = "") -> dict:
    """Stateless multi-turn chat. Send full message history, get Claude reply."""
    return chat_inner(messages, system)


@metered_tool("ai")
def plan(goal: Annotated[str, Field(description="Goal to create a plan for")], context: Annotated[str, Field(description="Background context or constraints")] = "", steps: Annotated[int, Field(description="Number of steps in the plan")] = 7) -> dict:
    """Step-by-step action plan for any goal with effort estimate and first action."""
    return plan_inner(goal, context, steps)


@metered_tool("ai")
def decide(decision: Annotated[str, Field(description="Decision or question to evaluate")], options: Annotated[list[str], Field(description="List of options to consider")] = None, criteria: Annotated[str, Field(description="Evaluation criteria or priorities")] = "") -> dict:
    """Decision framework: pros, cons, risks, recommendation, and confidence score."""
    return decide_inner(decision, options, criteria)


@metered_tool("ai")
def explain(concept: Annotated[str, Field(description="Concept or topic to explain")], level: Annotated[str, Field(description="Explanation level: beginner, intermediate, or expert")] = "beginner", analogy: Annotated[bool, Field(description="Whether to include an analogy")] = True) -> dict:
    """Explain any concept at beginner, intermediate, or expert level with analogy."""
    result = explain_inner(concept, level, analogy)
    if not os.environ.get("AIPAYGEN_API_KEY", ""):
        if isinstance(result, dict):
            for key in ("explanation", "result", "text"):
                if key in result and isinstance(result[key], str):
                    result[key] = result[key][:150] + "..."
                    break
            result["_truncated"] = True
            result["_full_result_hint"] = "Preview only. Call generate_api_key() for full results."
    return result


@metered_tool("ai")
def questions(content: Annotated[str, Field(description="Content to generate questions from")], type: Annotated[str, Field(description="Question type: faq, interview, quiz, or comprehension")] = "faq", count: Annotated[int, Field(description="Number of questions to generate")] = 5) -> dict:
    """Generate questions + answers from any content. type: faq | interview | quiz | comprehension"""
    return questions_inner(content, type, count)


@metered_tool("ai")
def outline(topic: Annotated[str, Field(description="Topic to create an outline for")], depth: Annotated[int, Field(description="Nesting depth of the outline")] = 2, sections: Annotated[int, Field(description="Number of top-level sections")] = 6) -> dict:
    """Generate a hierarchical outline with headings, summaries, and subsections."""
    return outline_inner(topic, depth, sections)


@metered_tool("ai")
def score(content: Annotated[str, Field(description="Content to score")], criteria: Annotated[list[str], Field(description="Scoring criteria like clarity, accuracy, engagement")] = None, scale: Annotated[int, Field(description="Maximum score value")] = 10) -> dict:
    """Score content on a custom rubric. Returns per-criterion scores, strengths, and weaknesses."""
    return score_inner(content, criteria or ["clarity", "accuracy", "engagement"], scale)


@metered_tool("ai")
def timeline(text: Annotated[str, Field(description="Text containing events to extract a timeline from")], direction: Annotated[str, Field(description="Sort order: chronological or reverse")] = "chronological") -> dict:
    """Extract or reconstruct a timeline from text. Returns dated events with significance."""
    return timeline_inner(text, direction)


@metered_tool("ai")
def action(text: Annotated[str, Field(description="Meeting notes or text to extract action items from")]) -> dict:
    """Extract action items, tasks, owners, and due dates from meeting notes or any text."""
    return action_inner(text)


@metered_tool("ai")
def pitch(product: Annotated[str, Field(description="Product or service to pitch")], audience: Annotated[str, Field(description="Target audience for the pitch")] = "general", length: Annotated[str, Field(description="Pitch duration: 15s, 30s, or 60s")] = "30s") -> dict:
    """Generate an elevator pitch: hook, value prop, call to action, full script. length: 15s | 30s | 60s"""
    return pitch_inner(product, audience, length)


@metered_tool("ai")
def debate(topic: Annotated[str, Field(description="Topic or position to debate")], perspective: Annotated[str, Field(description="Perspective: balanced, for, or against")] = "balanced") -> dict:
    """Arguments for and against any position with strength ratings and verdict."""
    return debate_inner(topic, perspective)


@metered_tool("ai")
def headline(content: Annotated[str, Field(description="Content to generate headlines for")], count: Annotated[int, Field(description="Number of headline variations")] = 5, style: Annotated[str, Field(description="Headline style: engaging, clickbait, seo, news")] = "engaging") -> dict:
    """Generate headline variations with type labels and a best pick."""
    return headline_inner(content, count, style)


@metered_tool("ai")
def fact(text: Annotated[str, Field(description="Text to extract factual claims from")], count: Annotated[int, Field(description="Maximum number of facts to extract")] = 10) -> dict:
    """Extract factual claims with verifiability scores and source hints."""
    return fact_inner(text, count)


# ── Heavy AI Tools (multi-step) ──────────────────────────────────────────────

@metered_tool("ai")
def review_code(code: Annotated[str, Field(description="Source code to review")], language: Annotated[str, Field(description="Programming language, or auto to detect")] = "auto", focus: Annotated[str, Field(description="Review focus: quality, security, or performance")] = "quality") -> dict:
    """Review code for quality, security, and performance issues. Returns issues, score, and summary."""
    return review_code_inner(code, language, focus)


@metered_tool("ai")
def generate_docs(code: Annotated[str, Field(description="Source code to generate documentation for")], style: Annotated[str, Field(description="Doc style: jsdoc, docstring, rustdoc, etc.")] = "jsdoc") -> dict:
    """Generate documentation for code. Supports jsdoc, docstring, rustdoc, etc."""
    return generate_docs_inner(code, style)


@metered_tool("ai")
def convert_code(code: Annotated[str, Field(description="Source code to convert")], from_lang: Annotated[str, Field(description="Source language, or auto to detect")] = "auto", to_lang: Annotated[str, Field(description="Target programming language")] = "python") -> dict:
    """Convert code from one programming language to another."""
    return convert_code_inner(code, from_lang, to_lang)


@metered_tool("ai")
def generate_api_spec(description: Annotated[str, Field(description="Natural language description of the API")], format: Annotated[str, Field(description="Spec format: openapi or asyncapi")] = "openapi") -> dict:
    """Generate an OpenAPI/AsyncAPI specification from a natural language description."""
    return generate_api_spec_inner(description, format)


@metered_tool("ai")
def diff(text_a: Annotated[str, Field(description="First text or code snippet")], text_b: Annotated[str, Field(description="Second text or code snippet")]) -> dict:
    """Analyze differences between two texts or code snippets. Returns changes, summary, and similarity."""
    return diff_inner(text_a, text_b)


@metered_tool("ai")
def parse_csv(csv_text: Annotated[str, Field(description="CSV data as a string")], question: Annotated[str, Field(description="Question to answer about the data")] = "") -> dict:
    """Analyze CSV data and optionally answer questions about it. Returns columns, row count, and insights."""
    return parse_csv_inner(csv_text, question)


@metered_tool("ai")
def cron_expression(description: Annotated[str, Field(description="Natural language description of the schedule")]) -> dict:
    """Generate or explain cron expressions from natural language. Returns cron string and next 5 runs."""
    return cron_expr_inner(description)


@metered_tool("ai")
def changelog(commits: Annotated[str, Field(description="Commit messages to generate changelog from")], version: Annotated[str, Field(description="Version number for the changelog header")] = "") -> dict:
    """Generate a professional changelog from commit messages. Groups by Added/Changed/Fixed/Removed."""
    return changelog_inner(commits, version)


@metered_tool("ai")
def name_generator(description: Annotated[str, Field(description="Description of the product, company, or feature to name")], count: Annotated[int, Field(description="Number of name suggestions")] = 10, style: Annotated[str, Field(description="Naming style: startup, corporate, playful, technical")] = "startup") -> dict:
    """Generate names for products, companies, or features with taglines and domain suggestions."""
    return name_generator_inner(description, count, style)


@metered_tool("ai")
def privacy_check(text: Annotated[str, Field(description="Text to scan for PII and sensitive data")]) -> dict:
    """Scan text for PII, secrets, and sensitive data. Returns found items, risk level, and recommendations."""
    return privacy_check_inner(text)


@metered_tool("ai_heavy")
def think(problem: Annotated[str, Field(description="The problem or question to solve")], context: Annotated[str, Field(description="Optional background information")] = "", max_steps: Annotated[int, Field(description="Maximum reasoning steps (1-10)")] = 5) -> dict:
    """
    Autonomous chain-of-thought reasoning. Breaks down a problem, reasons
    step-by-step, optionally calls internal tools, and returns a structured
    solution with confidence score.

    problem: The problem or question to solve.
    context: Optional background information.
    max_steps: Maximum reasoning steps (1-10, default 5).
    """
    return think_inner(problem, context, max_steps=min(max_steps, 10))


@metered_tool("ai_heavy")
def pipeline(steps: Annotated[list[dict], Field(description="Sequential operations, each with endpoint and input keys")]) -> dict:
    """
    Chain up to 5 operations sequentially. Each step can reference the previous
    output using the string '{{prev}}' as a field value in its input.

    Example steps:
    [
      {"endpoint": "research", "input": {"topic": "quantum computing"}},
      {"endpoint": "summarize", "input": {"text": "{{prev}}", "length": "short"}},
      {"endpoint": "headline", "input": {"content": "{{prev}}", "count": 3}}
    ]
    """
    return pipeline_inner(steps)


@metered_tool("ai_heavy")
def batch(operations: Annotated[list[dict], Field(description="Independent operations, each with endpoint and input keys")]) -> dict:
    """
    Run up to 5 independent operations in one call.

    Each operation: {"endpoint": "research", "input": {"topic": "AI"}}
    Valid endpoints: research, summarize, analyze, translate, social, write, code,
    extract, qa, classify, sentiment, keywords, compare, transform, chat, plan,
    decide, proofread, explain, questions, outline, email, sql, regex, mock,
    score, timeline, action, pitch, debate, headline, fact, rewrite, tag
    """
    if not operations or not isinstance(operations, list):
        return {"error": "operations array required"}
    if len(operations) > 5:
        return {"error": "max 5 operations per batch"}
    results = []
    for op in operations:
        endpoint = op.get("endpoint", "").lstrip("/")
        inp = op.get("input", {})
        handler = BATCH_HANDLERS.get(endpoint)
        if not handler:
            results.append({"endpoint": endpoint, "error": f"unknown endpoint '{endpoint}'"})
        else:
            try:
                results.append({"endpoint": endpoint, **handler(inp)})
            except Exception:
                _log.exception("batch operation %s failed", endpoint)
                results.append({"endpoint": endpoint, "error": "Tool execution failed"})
    return {"results": results, "count": len(results)}


# ── Vision & Advanced AI Tools ───────────────────────────────────────────────

@metered_tool("ai")
def vision(image_url: Annotated[str, Field(description="URL of the image to analyze")], question: Annotated[str, Field(description="Question to ask about the image")] = "Describe this image in detail") -> dict:
    """Analyze any image URL using Claude Vision. Ask specific questions or get a full description."""
    gate = _premium_gate("vision", "$0.05/call")
    if gate:
        return gate
    return vision_inner(image_url, question)


@metered_tool("ai")
def rag(documents: Annotated[str, Field(description="Documents to query, separated by '---' for multiple")], query: Annotated[str, Field(description="Question to answer from the documents")]) -> dict:
    """
    Grounded Q&A using only your documents. Separate multiple documents with '---'.
    Returns answer, confidence, citations, and a cannot_answer flag.
    """
    return rag_inner(documents, query)


@metered_tool("ai")
def diagram(description: Annotated[str, Field(description="Plain English description of the diagram")], diagram_type: Annotated[str, Field(description="Diagram type: flowchart, sequence, erd, gantt, mindmap")] = "flowchart") -> dict:
    """
    Generate a Mermaid diagram from a plain English description.
    Types: flowchart, sequence, erd, gantt, mindmap
    """
    return diagram_inner(description, diagram_type)


@metered_tool("ai")
def json_schema(description: Annotated[str, Field(description="Plain English description of the data structure")], example: Annotated[str, Field(description="Example data to help infer the schema")] = "") -> dict:
    """Generate a JSON Schema (draft-07) from a plain English description of your data structure."""
    return json_schema_inner(description, example)


@metered_tool("ai")
def test_cases(code_or_description: Annotated[str, Field(description="Code or feature description to generate tests for")], language: Annotated[str, Field(description="Programming language for the test cases")] = "python") -> dict:
    """Generate comprehensive test cases with edge cases for code or a feature description."""
    return test_cases_inner(code_or_description, language)


@metered_tool("ai_heavy")
def workflow(goal: Annotated[str, Field(description="Complex goal requiring multi-step reasoning")], context: Annotated[str, Field(description="Background context or constraints")] = "") -> dict:
    """
    Multi-step agentic reasoning using Claude Sonnet. Breaks down complex goals,
    reasons through each sub-task, and produces a comprehensive result.
    Best for complex tasks requiring multiple steps of reasoning.
    """
    return workflow_inner(goal, context)


# ── Workflow Templates (compound tools) ──────────────────────────────────────

@metered_tool("ai_heavy")
def content_brief(topic: Annotated[str, Field(description="Topic to create a content brief for")]) -> dict:
    """Generate a complete content brief: research + keywords + outline + headline suggestions."""
    gate = _premium_gate("content_brief", "$0.20/call")
    if gate:
        return gate
    research_result = research_inner(topic)
    research_text = research_result.get("answer", "") if isinstance(research_result, dict) else str(research_result)
    kw_result = keywords_inner(research_text)
    kw_text = ", ".join(kw_result.get("keywords", [])) if isinstance(kw_result, dict) else str(kw_result)
    outline_result = outline_inner(f"{topic} (key themes: {kw_text})")
    headline_result = headline_inner(f"{topic} — {kw_text}", count=5, style="mixed")
    return {
        "topic": topic,
        "research": research_result,
        "keywords": kw_result,
        "outline": outline_result,
        "headlines": headline_result,
    }


@metered_tool("ai_heavy")
def competitor_analysis(company: Annotated[str, Field(description="Company or product to analyze")]) -> dict:
    """Analyze a competitor: research + sentiment + key findings."""
    gate = _premium_gate("competitor_analysis", "$0.20/call")
    if gate:
        return gate
    research_result = research_inner(f"{company} reviews analysis competitors")
    research_text = research_result.get("answer", "") if isinstance(research_result, dict) else str(research_result)
    sentiment_result = sentiment_inner(research_text)
    return {
        "company": company,
        "research": research_result,
        "sentiment": sentiment_result,
    }


@metered_tool("ai")
def translate_and_summarize(text: Annotated[str, Field(description="Text to translate and summarize")], language: Annotated[str, Field(description="Target language")] = "Spanish") -> dict:
    """Translate text to target language and provide a summary of the translation."""
    translated = translate_inner(text, language)
    translated_text = translated.get("translation", "") if isinstance(translated, dict) else str(translated)
    summary = summarize_inner(translated_text, "short")
    return {
        "original_language": "auto-detected",
        "target_language": language,
        "translation": translated,
        "summary": summary,
    }


@metered_tool("ai_heavy")
def chain_operations(steps: Annotated[list, Field(description="List of {action, params} dicts to chain sequentially")]) -> dict:
    """
    Chain multiple AI operations in sequence. Output of each step is available to the next.
    steps: list of {action: str, params: dict}
    Available actions: research, summarize, analyze, sentiment, keywords, classify,
                       rewrite, extract, qa, compare, outline, diagram, json_schema, workflow
    Use '{{prev_result}}' in params to reference previous step output.
    Example: [{"action": "research", "params": {"query": "AI trends"}},
              {"action": "summarize", "params": {"text": "{{prev_result}}", "format": "bullets"}}]
    """
    from mcp_tools import (
        rewrite_inner, extract_inner, qa_inner, compare_inner,
        outline_inner, diagram_inner, json_schema_inner, workflow_inner,
    )
    _CHAIN = {
        "research": lambda p: research_inner(p.get("topic", "")),
        "summarize": lambda p: summarize_inner(p.get("text", ""), p.get("length", "short")),
        "analyze": lambda p: analyze_inner(p.get("text", ""), p.get("question", "Analyze")),
        "sentiment": lambda p: sentiment_inner(p.get("text", "")),
        "keywords": lambda p: keywords_inner(p.get("text", ""), int(p.get("n", 10))),
        "classify": lambda p: classify_inner(p.get("text", ""), p.get("categories", [])),
        "rewrite": lambda p: rewrite_inner(p.get("text", ""), p.get("audience", "general"), p.get("tone", "professional")),
        "extract": lambda p: extract_inner(p.get("text", ""), p.get("schema_desc", ""), p.get("fields", [])),
        "qa": lambda p: qa_inner(p.get("context", ""), p.get("question", "")),
        "compare": lambda p: compare_inner(p.get("text_a", ""), p.get("text_b", ""), p.get("focus", "")),
        "outline": lambda p: outline_inner(p.get("topic", "")),
        "diagram": lambda p: diagram_inner(p.get("description", ""), p.get("diagram_type", "flowchart")),
        "json_schema": lambda p: json_schema_inner(p.get("description", ""), str(p.get("example", ""))),
        "workflow": lambda p: workflow_inner(p.get("goal", ""), str(p.get("available_data", ""))),
    }
    if len(steps) > 5:
        return {"error": "max 5 steps"}
    results = []
    last_result = None
    for i, step in enumerate(steps):
        name = step.get("action", "")
        if name not in _CHAIN:
            return {"error": f"step {i}: unknown action '{name}'", "available": list(_CHAIN.keys())}
        params = step.get("params", {})
        if last_result is not None:
            params = {k: v.replace("{{prev_result}}", str(last_result)) if isinstance(v, str) else v
                      for k, v in params.items()}
        out = _CHAIN[name](params)
        results.append({"step": i + 1, "action": name, "result": out})
        if isinstance(out, dict):
            last_result = out.get("result") or out.get("text") or str(out)
        else:
            last_result = str(out)
    return {"steps_completed": len(results), "chain": results, "final_result": results[-1]["result"] if results else None}


@metered_tool("premium")
async def compare_models(prompt: str, models: str = "claude-haiku,gpt-4o-mini") -> str:
    """Run the same prompt on multiple AI models and compare results side-by-side.
    
    Args:
        prompt: The prompt to send to each model
        models: Comma-separated model names (max 3)
    """
    r = _post("/compare-models", {"prompt": prompt, "models": models.split(",")[:3]})
    return _json.dumps(r, indent=2)


@metered_tool("free")
async def estimate_cost(tool: str, count: int = 1) -> str:
    """Estimate the cost of API calls before making them.
    
    Args:
        tool: Tool name (e.g. research, sentiment, translate)
        count: Number of calls to estimate
    """
    r = _post("/estimate-cost", {"tool": tool, "count": count})
    return _json.dumps(r, indent=2)


@metered_tool("free")
async def suggest_tools(task: str) -> str:
    """Describe what you need and get AI tool recommendations.
    
    Args:
        task: Description of what you want to accomplish
    """
    r = _post("/suggest-tools", {"task": task})
    return _json.dumps(r, indent=2)
