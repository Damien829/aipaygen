"""AI Tool endpoints — extracted from app.py into a Flask Blueprint."""

import json
import requests as _requests
from flask import Blueprint, request, jsonify, Response
from model_router import call_model, get_model_config, ModelNotFoundError
from helpers import parse_json_from_claude, agent_response, log_payment
from web import scrape_url, search_web

ai_tools_bp = Blueprint("ai_tools", __name__)


# ── Helper: routed LLM call ────────────────────────────────────────────────────

def _call_llm(messages, system="", max_tokens=1024, endpoint="unknown", model_override=None):
    """Route LLM call through model_router. Reads 'model' from request JSON if not overridden."""
    from discovery_engine import track_cost
    from api_keys import deduct_metered
    model_name = model_override or (request.get_json(silent=True) or {}).get("model", "claude-haiku")
    try:
        result = call_model(model_name, messages, system=system, max_tokens=max_tokens)
    except ModelNotFoundError as e:
        return None, str(e)
    # Track cost via discovery engine
    try:
        track_cost(endpoint, result["model_id"], result["input_tokens"], result["output_tokens"])
    except Exception:
        pass
    # Metered deduction if applicable
    api_key = request.environ.get("X_APIKEY_BYPASS", "")
    pricing_mode = request.environ.get("X_PRICING_MODE", "flat")
    if api_key and pricing_mode == "metered":
        cfg = get_model_config(model_name)
        estimated_cost = (result["input_tokens"] * cfg["input_cost_per_m"] + result["output_tokens"] * cfg["output_cost_per_m"]) / 1_000_000
        if estimated_cost > 1.00:
            result["metered_warning"] = f"Request cost ${estimated_cost:.4f} exceeds $1.00 cap — deduction skipped"
        else:
            deduction = deduct_metered(
                api_key, result["input_tokens"], result["output_tokens"],
                cfg["input_cost_per_m"], cfg["output_cost_per_m"],
            )
            if deduction:
                result["metered_cost"] = deduction["cost"]
                result["balance_remaining"] = deduction["balance_remaining"]
    return result, None


# ── Inner Functions ─────────────────────────────────────────────────────────────

def research_inner(topic, model="claude-haiku"):
    if not topic:
        return {"error": "topic required"}
    r = call_model(model, [{"role": "user", "content": f'Research this topic. Return JSON with keys: "summary" (string), "key_points" (array of 5), "sources_to_check" (array of 3 URLs). Topic: {topic}'}],
        system="You are a research assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"topic": topic, "model": r["model"], **(s if s else {"result": raw})}


def summarize_inner(text, length, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": f"Summarize. Length: {length} (short=2-3 sentences, medium=1 paragraph, detailed=3-4 paragraphs). Return only the summary.\n\n{text}"}],
        max_tokens=512)
    return {"result": r["text"], "length": length, "model": r["model"]}


def analyze_inner(content, question, model="claude-haiku"):
    if not content:
        return {"error": "content required"}
    r = call_model(model, [{"role": "user", "content": f'Analyze this. Focus: {question}\nReturn JSON with: "conclusion" (string), "findings" (array), "sentiment" (string), "confidence" (0-1).\n\nContent:\n{content}'}],
        system="You are an analytical assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"question": question, "model": r["model"], **(s if s else {"result": raw})}


def translate_inner(text, language, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": f"Translate to {language}. Return only the translation.\n\n{text}"}],
        max_tokens=2048)
    return {"result": r["text"], "language": language, "model": r["model"]}


def social_inner(topic, platforms, tone, model="claude-haiku"):
    if not topic:
        return {"error": "topic required"}
    platform_list = ", ".join(platforms) if isinstance(platforms, list) else str(platforms)
    r = call_model(model, [{"role": "user", "content": f'Write {tone} posts for: {platform_list}. Topic: {topic}\nReturn JSON with each platform as key, post text as value.'}],
        system="You are a social media expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"topic": topic, "platforms": platforms, "model": r["model"], **({"posts": s} if s else {"result": raw})}


def write_inner(spec, content_type, model="claude-haiku"):
    if not spec:
        return {"error": "spec required"}
    r = call_model(model, [{"role": "user", "content": f"Write a {content_type}. Return only the content.\n\nSpec: {spec}"}],
        max_tokens=2048)
    return {"result": r["text"], "type": content_type, "model": r["model"]}


def code_inner(description, language, model="claude-haiku"):
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": f"Write {language} code. Return only the code.\n\n{description}"}],
        max_tokens=2048)
    return {"result": r["text"], "language": language, "model": r["model"]}


def extract_inner(text, schema_desc, fields, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    if fields:
        fields_str = ", ".join(f'"{f}"' for f in fields[:20])
        prompt = f'Extract these fields from the text and return as JSON: {fields_str}.\nIf a field is not found, use null.\n\nText:\n{text[:4000]}'
    elif schema_desc:
        prompt = f'Extract data matching this schema and return as JSON: {schema_desc}\n\nText:\n{text[:4000]}'
    else:
        prompt = f'Extract all key entities, facts, dates, names, and values from this text. Return as JSON with descriptive keys.\n\nText:\n{text[:4000]}'
    r = call_model(model, [{"role": "user", "content": prompt}],
        system="You are a data extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"extracted": s if s else raw, "fields_requested": fields or schema_desc or "auto", "model": r["model"]}


def qa_inner(context, question, model="claude-haiku"):
    if not context:
        return {"error": "context required"}
    if not question:
        return {"error": "question required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Answer the question using only the provided context. '
        f'Return JSON with: "answer" (string), "confidence" (0-1), "found_in_context" (boolean), "quote" (relevant excerpt or null).\n\n'
        f'Context:\n{context[:4000]}\n\nQuestion: {question}'
    )}], system="You are a precise question-answering assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"question": question, "model": r["model"], **(s if s else {"answer": raw, "confidence": 0.5, "found_in_context": True, "quote": None})}


def classify_inner(text, categories, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    if not categories or not isinstance(categories, list):
        return {"error": "categories array required", "hint": "e.g. [\"positive\", \"negative\", \"neutral\"]"}
    cats_str = ", ".join(f'"{c}"' for c in categories[:20])
    r = call_model(model, [{"role": "user", "content": (
        f'Classify this text into one of these categories: {cats_str}. '
        f'Return JSON with: "category" (the best match), "confidence" (0-1), "scores" (object with each category and its score 0-1).\n\n'
        f'Text: {text[:2000]}'
    )}], system="You are a text classification assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=256)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"text_preview": text[:100], "categories": categories, "model": r["model"], **(s if s else {"category": raw, "confidence": 0.5, "scores": {}})}


def sentiment_inner(text, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Analyze the sentiment of this text. Return JSON with: '
        f'"polarity" (positive/negative/neutral/mixed), "score" (-1.0 to 1.0), '
        f'"confidence" (0-1), "emotions" (array of detected emotions like joy/anger/fear/sadness/surprise), '
        f'"key_phrases" (array of up to 5 sentiment-driving phrases).\n\nText: {text[:2000]}'
    )}], system="You are a sentiment analysis assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=256)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"text_preview": text[:100], "model": r["model"], **(s if s else {"polarity": raw, "score": 0, "confidence": 0.5})}


def keywords_inner(text, max_keywords=10, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Extract keywords from this text. Return JSON with: '
        f'"keywords" (array of up to {max_keywords} single-word keywords, most important first), '
        f'"topics" (array of up to 5 broader topic phrases), '
        f'"tags" (array of up to 8 hashtag-style tags without #), '
        f'"language" (detected language).\n\nText: {text[:3000]}'
    )}], system="You are a keyword extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"keywords": [], "topics": [], "tags": [], "result": raw}), "model": r["model"]}


def compare_inner(text_a, text_b, focus="", model="claude-haiku"):
    if not text_a or not text_b:
        return {"error": "both text_a and text_b required"}
    focus_str = f" Focus on: {focus}." if focus else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Compare these two texts.{focus_str} Return JSON with: '
        f'"similarities" (array of shared points), "differences" (array of key differences), '
        f'"recommendation" (string — which is better and why, or null if not applicable), '
        f'"similarity_score" (0-1, how similar they are).\n\n'
        f'Text A:\n{text_a[:2000]}\n\nText B:\n{text_b[:2000]}'
    )}], system="You are a comparison assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=768)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"result": raw}), "model": r["model"]}


def transform_inner(text, instruction, model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    if not instruction:
        return {"error": "instruction required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Transform the following text according to this instruction. Return ONLY the transformed text, nothing else.\n\n'
        f'Instruction: {instruction}\n\nText:\n{text[:3000]}'
    )}], max_tokens=2048)
    return {"result": r["text"], "instruction": instruction, "model": r["model"]}


def chat_inner(messages, system_prompt="", model="claude-haiku"):
    if not messages or not isinstance(messages, list):
        return {"error": "messages array required"}
    valid = [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
    if not valid:
        return {"error": "messages must be array of {role, content} objects with role=user|assistant"}
    r = call_model(model, valid[-20:], system=system_prompt or "", max_tokens=1024)
    return {"reply": r["text"], "role": "assistant", "turn": len(valid) + 1, "model": r["model"]}


def plan_inner(goal, context="", steps=7, model="claude-haiku"):
    if not goal:
        return {"error": "goal required"}
    ctx = f"\nContext: {context}" if context else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Create a step-by-step action plan for this goal.{ctx}\n'
        f'Return JSON with: "goal" (string), "steps" (array of up to {steps} objects each with "step" number, "action" string, "why" string), '
        f'"estimated_effort" (low/medium/high), "first_action" (the single most important first step).\n\nGoal: {goal}'
    )}], system="You are a strategic planning assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"goal": goal, "result": raw}), "model": r["model"]}


def decide_inner(decision, options=None, criteria="", model="claude-haiku"):
    if not decision:
        return {"error": "decision required"}
    opts_str = f"\nOptions to evaluate: {', '.join(options)}" if options else ""
    crit_str = f"\nCriteria to weigh: {criteria}" if criteria else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Help make this decision.{opts_str}{crit_str}\n'
        f'Return JSON with: "decision" (string), "recommendation" (string — the best choice), '
        f'"reasoning" (string — why), "pros" (array), "cons" (array), "risks" (array), "confidence" (0-1).\n\nDecision: {decision}'
    )}], system="You are a decision analysis assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"decision": decision, "result": raw}), "model": r["model"]}


def proofread_inner(text, style="professional", model="claude-haiku"):
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Proofread this text for grammar, spelling, punctuation, and clarity. Style: {style}.\n'
        f'Return JSON with: "corrected" (the fixed text), "issues" (array of objects with "type", "original", "suggestion"), '
        f'"score" (1-10 writing quality), "summary" (one sentence describing overall quality).\n\nText:\n{text[:3000]}'
    )}], system="You are a proofreading assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=2048)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"corrected": raw, "issues": [], "score": 7, "summary": "Proofread complete"}), "model": r["model"]}


def explain_inner(concept, level="beginner", analogy=True, model="claude-haiku"):
    if not concept:
        return {"error": "concept required"}
    analogy_str = "Include a simple real-world analogy." if analogy else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Explain this concept at a {level} level. {analogy_str}\n'
        f'Return JSON with: "explanation" (clear explanation for {level} level), '
        f'"analogy" (simple real-world comparison or null), "key_points" (array of 3-5 key takeaways), '
        f'"common_misconceptions" (array of 1-2 things people get wrong, or empty array).\n\nConcept: {concept}'
    )}], system="You are an expert educator. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=768)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"explanation": raw, "analogy": None, "key_points": [], "common_misconceptions": []}), "model": r["model"]}


def questions_inner(content, qtype="faq", count=5, model="claude-haiku"):
    if not content:
        return {"error": "content required"}
    type_map = {"faq": "frequently asked questions", "interview": "interview questions", "quiz": "quiz questions with answers", "comprehension": "reading comprehension questions"}
    type_desc = type_map.get(qtype, qtype)
    r = call_model(model, [{"role": "user", "content": (
        f'Generate {count} {type_desc} based on this content.\n'
        f'Return JSON with: "questions" (array of objects with "question" string and "answer" string).\n\nContent:\n{content[:3000]}'
    )}], system="You are a question generation assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"questions": [], "result": raw}), "model": r["model"]}


def outline_inner(topic, depth=2, sections=6, model="claude-haiku"):
    if not topic:
        return {"error": "topic required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Generate a structured outline for this topic with {depth} levels of depth and up to {sections} main sections.\n'
        f'Return JSON with: "title" (string), "sections" (array of objects with "heading", "summary", "subsections" array of strings).\n\nTopic: {topic}'
    )}], system="You are an outline and structure expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"title": topic, "result": raw}), "model": r["model"]}


def email_inner(purpose, tone="professional", context="", recipient="", length="medium", model="claude-haiku"):
    if not purpose:
        return {"error": "purpose required"}
    parts = []
    if recipient: parts.append(f"Recipient: {recipient}")
    if context: parts.append(f"Context: {context}")
    extra = "\n".join(parts)
    r = call_model(model, [{"role": "user", "content": (
        f'Write a {tone} email. Length: {length} (short=3-4 sentences, medium=2-3 paragraphs, long=4+ paragraphs).\n{extra}\n'
        f'Return JSON with: "subject" (string), "body" (full email body text), "tone" (string), "word_count" (number).\n\nPurpose: {purpose}'
    )}], system="You are an email writing assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"subject": purpose, "body": raw, "tone": tone}), "model": r["model"]}


def sql_inner(description, dialect="postgresql", schema="", model="claude-haiku"):
    if not description:
        return {"error": "description required"}
    schema_str = f"\nDatabase schema:\n{schema}" if schema else ""
    r = call_model(model, [{"role": "user", "content": (
        f'Write a {dialect} SQL query for this description.{schema_str}\n'
        f'Return JSON with: "query" (the SQL query), "explanation" (what it does), '
        f'"dialect" (string), "notes" (any assumptions or caveats, or null).\n\nDescription: {description}'
    )}], system="You are a SQL expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"query": raw, "explanation": description, "dialect": dialect, "notes": None}), "model": r["model"]}


def regex_inner(description, language="python", flags="", model="claude-haiku"):
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Generate a regex pattern for {language} that matches: {description}. Flags hint: {flags or "none"}.\n'
        f'Return JSON with: "pattern" (the regex string), "flags" (flags to use, or empty string), '
        f'"explanation" (what it matches and why), "examples" (array of 3 strings that would match), '
        f'"non_examples" (array of 2 strings that would NOT match).'
    )}], system="You are a regex expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"pattern": raw, "flags": "", "explanation": description}), "model": r["model"]}


def mock_inner(description, count=5, fmt="json", model="claude-haiku"):
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": (
        f'Generate {count} realistic mock data records for: {description}. Output format: {fmt}.\n'
        f'Return JSON with: "data" (array of {count} records as objects), "schema" (object describing each field and its type), '
        f'"format" (string: json/csv/list).'
    )}], system="You are a mock data generation expert. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1536)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {**(s if s else {"data": [], "result": raw, "format": fmt}), "model": r["model"]}


def score_inner(content, criteria, scale=10, model="claude-haiku"):
    criteria_str = json.dumps(criteria) if isinstance(criteria, list) else str(criteria)
    r = call_model(model, [{"role": "user", "content": (
        f'Score this content on a scale of 1-{scale}. Criteria: {criteria_str}. '
        f'Return JSON with: "overall_score" (number), "scores" (object with each criterion and its score), '
        f'"strengths" (array), "weaknesses" (array), "recommendation" (string).\n\nContent:\n{content[:3000]}'
    )}], system="You are a content scoring assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"criteria": criteria, "scale": scale, "model": r["model"], **(s if s else {"result": raw})}


def timeline_inner(text, direction="chronological", model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Extract or reconstruct a {direction} timeline from this text. '
        f'Return JSON with: "events" (array of objects with "date", "event", "significance"), '
        f'"span" (string describing total time range), "summary" (string).\n\nText:\n{text[:3000]}'
    )}], system="You are a timeline extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"direction": direction, "model": r["model"], **(s if s else {"result": raw})}


def action_inner(text, model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Extract all action items and tasks from this text. '
        f'Return JSON with: "actions" (array of objects with "task", "owner" (string or null), "due_date" (string or null), "priority" (high/medium/low)), '
        f'"count" (integer), "summary" (string).\n\nText:\n{text[:3000]}'
    )}], system="You are an action item extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"model": r["model"], **(s if s else {"result": raw})}


def pitch_inner(product, audience, length="30s", model="claude-haiku"):
    words = {"15s": 40, "30s": 75, "60s": 150}.get(length, 75)
    r = call_model(model, [{"role": "user", "content": (
        f'Write an elevator pitch (~{words} words) for: {product}. Target audience: {audience or "general"}. '
        f'Return JSON with: "hook" (opening line), "value_prop" (core benefit), "call_to_action" (closing ask), '
        f'"full_pitch" (complete {length} pitch), "word_count" (integer).'
    )}], system="You are a pitch writing assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"product": product, "audience": audience, "length": length, "model": r["model"], **(s if s else {"result": raw})}


def debate_inner(topic, perspective="balanced", model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Generate debate arguments for this topic: {topic}. Perspective: {perspective}. '
        f'Return JSON with: "for" (array of objects with "argument" and "strength": strong/medium/weak), '
        f'"against" (array of objects with "argument" and "strength"), '
        f'"verdict" (string: which side is stronger), "nuance" (string: key considerations).'
    )}], system="You are a debate assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"topic": topic, "perspective": perspective, "model": r["model"], **(s if s else {"result": raw})}


def headline_inner(content, count=5, style="engaging", model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Generate {count} {style} headlines/titles for this content. '
        f'Return JSON with: "headlines" (array of objects with "text" and "type": clickbait/informative/question/how-to/listicle), '
        f'"best" (the single best headline).\n\nContent:\n{content[:2000]}'
    )}], system="You are a headline writing assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=512)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"count": count, "style": style, "model": r["model"], **(s if s else {"result": raw})}


def fact_inner(text, count=10, model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Extract up to {count} factual claims from this text. '
        f'Return JSON with: "facts" (array of objects with "claim" (string), "verifiability": easy/moderate/difficult, '
        f'"source_hint" (string or null), "confidence" (0-1)), "total_claims" (integer).\n\nText:\n{text[:3000]}'
    )}], system="You are a fact extraction assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=1024)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"model": r["model"], **(s if s else {"result": raw})}


def rewrite_inner(text, audience, tone="neutral", model="claude-haiku"):
    r = call_model(model, [{"role": "user", "content": (
        f'Rewrite this text for: {audience}. Tone: {tone}. '
        f'Return only the rewritten text with no explanation.\n\nOriginal:\n{text[:3000]}'
    )}], max_tokens=2048)
    return {"result": r["text"], "audience": audience, "tone": tone, "model": r["model"]}


def tag_inner(text, taxonomy, max_tags=10, model="claude-haiku"):
    taxonomy_str = f"Use only tags from this taxonomy: {json.dumps(taxonomy)}." if taxonomy else "Generate free-form tags."
    r = call_model(model, [{"role": "user", "content": (
        f'Tag this content with up to {max_tags} tags. {taxonomy_str} '
        f'Return JSON with: "tags" (array of strings), "primary_tag" (most relevant tag), '
        f'"categories" (array of 1-3 broad categories).\n\nContent:\n{text[:2000]}'
    )}], system="You are a content tagging assistant. Always respond with valid JSON only — no markdown, no preamble.", max_tokens=256)
    raw = r["text"]
    s = parse_json_from_claude(raw)
    return {"max_tags": max_tags, "taxonomy": taxonomy, "model": r["model"], **(s if s else {"result": raw})}


def pipeline_inner(steps):
    if len(steps) > 5:
        return {"error": "max 5 steps"}
    results = []
    prev_output = None
    for i, step in enumerate(steps):
        endpoint = step.get("endpoint", "").lstrip("/")
        inp = dict(step.get("input", {}))
        if prev_output is not None:
            prev_text = (prev_output.get("result") or prev_output.get("summary") or str(prev_output))[:3000]
            for k, v in inp.items():
                if v in ("{{prev}}", "{{output}}"):
                    inp[k] = prev_text
        handler = BATCH_HANDLERS.get(endpoint)
        if not handler:
            result = {"error": f"unknown endpoint '{endpoint}'"}
        else:
            try:
                result = handler(inp)
            except Exception as e:
                result = {"error": str(e)}
        results.append({"step": i + 1, "endpoint": endpoint, **result})
        prev_output = result
    return {"results": results, "steps": len(steps), "final_output": prev_output}


def vision_inner(image_url, question="Describe this image in detail", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "url", "url": image_url}},
            {"type": "text", "text": question},
        ],
    }], max_tokens=1024)
    return {"image_url": image_url, "question": question, "analysis": r["text"], "model": r["model"]}


def rag_inner(documents, query, model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Documents:\n{documents}\n\n"
            f"Query: {query}\n\n"
            f'Return JSON: {{"answer": "str", "confidence": 0.0-1.0, '
            f'"citations": ["relevant quotes"], "cannot_answer": false}}'
        ),
    }], system="Answer using ONLY the provided documents. Never hallucinate. Cite specific document sections.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"answer": r["text"]}
    return {**parsed, "model": r["model"]}


def diagram_inner(description, diagram_type="flowchart", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Create a {diagram_type} Mermaid diagram for: {description}\n"
            f'Return JSON: {{"mermaid": "valid mermaid code block", "title": "str", "description": "str"}}'
        ),
    }], system="You generate valid Mermaid diagram syntax. Always respond with valid JSON only.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"mermaid": r["text"]}
    return {**parsed, "model": r["model"]}


def json_schema_inner(description, example="", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": f"Generate JSON Schema for: {description}\nExample data: {example}\nReturn the complete JSON Schema object.",
    }], system="You are a JSON Schema expert. Generate valid JSON Schema draft-07. Always respond with valid JSON only.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"]) or {"schema": r["text"]}
    return {**parsed, "model": r["model"]}


def test_cases_inner(code_or_description, language="python", model="claude-haiku"):
    r = call_model(model, [{
        "role": "user",
        "content": (
            f"Generate comprehensive test cases for:\n{code_or_description}\n"
            f'Return JSON: {{"test_cases": [{{"name": "str", "input": "str", "expected": "str", "edge_case": true}}], '
            f'"coverage_notes": "str", "suggested_framework": "str"}}'
        ),
    }], system=f"You are a {language} testing expert. Always respond with valid JSON only.", max_tokens=1500)
    parsed = parse_json_from_claude(r["text"]) or {"test_cases": r["text"]}
    return {**parsed, "model": r["model"]}


def workflow_inner(goal, available_data="", model="claude-sonnet"):
    r = call_model(model, [{"role": "user", "content": f"Goal: {goal}\n\nAvailable data:\n{available_data}"}],
        system="You are an autonomous agent. Break complex goals into sub-tasks, reason through each, and produce a comprehensive final answer. Show your reasoning, then give a clean result.",
        max_tokens=4096)
    return {"goal": goal, "result": r["text"], "model": r["model"]}


# ── Route Endpoints ─────────────────────────────────────────────────────────────

@ai_tools_bp.route("/scrape", methods=["POST"])
def scrape():
    data = request.get_json() or {}
    url = data.get("url", "")
    if not url:
        return jsonify({"error": "url required", "hint": "POST {\"url\": \"https://example.com\"}"}), 400
    result = scrape_url(url)
    log_payment("/scrape", 0.01, request.remote_addr)
    return jsonify(result)


@ai_tools_bp.route("/search", methods=["POST"])
def search_endpoint():
    data = request.get_json() or {}
    query = data.get("query", "")
    n = min(int(data.get("n", 5)), 10)
    if not query:
        return jsonify({"error": "query required", "hint": "POST {\"query\": \"your search\", \"n\": 5}"}), 400
    result = search_web(query, n=n)
    log_payment("/search", 0.01, request.remote_addr)
    return jsonify(result)


@ai_tools_bp.route("/research", methods=["POST"])
def research():
    data = request.get_json() or {}
    question = data.get("question", "")
    if not question:
        return jsonify({"error": "question required", "hint": "POST {\"question\": \"your research question\"}"}), 400

    search_result = search_web(question, n=5)
    if "error" in search_result:
        return jsonify(search_result), 422
    top_urls = [r["url"] for r in search_result["results"][:3]]

    pages = []
    for url in top_urls:
        scraped = scrape_url(url, timeout=8)
        if "error" not in scraped and scraped.get("word_count", 0) > 50:
            pages.append(scraped)

    if not pages:
        return jsonify({"error": "could not retrieve source pages"}), 422

    context = "\n\n---\n\n".join(
        f"Source: {p['url']}\n\n{p['text'][:2000]}" for p in pages
    )
    result, err = _call_llm(
        [{"role": "user", "content": f"Answer the following question based on the sources below. Include inline citations like [1], [2] etc. Be thorough but concise.\n\nQuestion: {question}\n\nSources:\n{context}"}],
        max_tokens=1500, endpoint="/research",
    )
    if err:
        return jsonify({"error": err}), 400
    sources = [{"title": r["title"], "url": r["url"]} for r in search_result["results"][:3]]
    log_payment("/research", 0.15, request.remote_addr)
    return jsonify({
        "question": question,
        "answer": result["text"],
        "sources": sources,
        "model": result["model"],
    })


@ai_tools_bp.route("/write", methods=["POST"])
def write():
    data = request.get_json() or {}
    spec = data.get("spec", "")
    content_type = data.get("type", "article")
    if not spec:
        return jsonify({"error": "spec required"}), 400

    result, err = _call_llm(
        [{"role": "user", "content": f"Write a {content_type} based on this spec. Return only the written content, no preamble.\n\nSpec: {spec}"}],
        max_tokens=2048, endpoint="/write",
    )
    if err:
        return jsonify({"error": err}), 400
    log_payment("/write", 0.05, request.remote_addr)
    return jsonify(agent_response({"result": result["text"], "type": content_type, "model": result["model"]}, "/write"))


@ai_tools_bp.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json() or {}
    content = data.get("content", "")
    question = data.get("question", "Provide a structured analysis")
    if not content:
        return jsonify({"error": "content required", "hint": "POST {\"content\": \"text to analyze\", \"question\": \"optional focus\"}"}), 400

    result, err = _call_llm(
        [{"role": "user", "content": (
            f'Analyze the following content. Focus: {question}\n\n'
            f'Return a JSON object with keys: '
            f'"conclusion" (string, 1-2 sentences), '
            f'"findings" (array of 4-6 key finding strings), '
            f'"sentiment" (string: positive/negative/neutral/mixed), '
            f'"confidence" (number 0-1).\n\n'
            f'Content:\n{content}'
        )}],
        system="You are an analytical assistant. Always respond with valid JSON only — no markdown, no preamble.",
        max_tokens=1024, endpoint="/analyze",
    )
    if err:
        return jsonify({"error": err}), 400
    raw = result["text"]
    structured = parse_json_from_claude(raw)
    log_payment("/analyze", 0.02, request.remote_addr)
    if structured:
        return jsonify(agent_response({"question": question, "model": result["model"], **structured}, "/analyze"))
    return jsonify(agent_response({"question": question, "result": raw, "model": result["model"]}, "/analyze"))


@ai_tools_bp.route("/code", methods=["POST"])
def code():
    data = request.get_json() or {}
    description = data.get("description", "")
    language = data.get("language", "Python")
    if not description:
        return jsonify({"error": "description required"}), 400

    result, err = _call_llm(
        [{"role": "user", "content": f"Write {language} code for the following. Return only the code, no explanation.\n\n{description}"}],
        max_tokens=2048, endpoint="/code",
    )
    if err:
        return jsonify({"error": err}), 400
    log_payment("/code", 0.05, request.remote_addr)
    return jsonify(agent_response({"result": result["text"], "language": language, "model": result["model"]}, "/code"))


@ai_tools_bp.route("/summarize", methods=["POST"])
def summarize():
    data = request.get_json() or {}
    text = data.get("text", "")
    length = data.get("length", "bullets")
    if not text:
        return jsonify({"error": "text required"}), 400
    result, err = _call_llm(
        [{"role": "user", "content": f"Summarize in {length} form:\n\n{text}"}],
        max_tokens=1024, endpoint="/summarize",
    )
    if err:
        return jsonify({"error": err}), 400
    log_payment("/summarize", 0.01, request.remote_addr)
    return jsonify(agent_response({
        "summary": result["text"], "original_length": len(text),
        "model": result["model"], "tokens": result["input_tokens"] + result["output_tokens"],
    }, "/summarize"))


@ai_tools_bp.route("/translate", methods=["POST"])
def translate():
    data = request.get_json() or {}
    text = data.get("text", "")
    target_language = data.get("language", "Spanish")
    if not text:
        return jsonify({"error": "text required"}), 400

    result, err = _call_llm(
        [{"role": "user", "content": f"Translate the following text to {target_language}. Return only the translation.\n\n{text}"}],
        max_tokens=2048, endpoint="/translate",
    )
    if err:
        return jsonify({"error": err}), 400
    log_payment("/translate", 0.02, request.remote_addr)
    return jsonify(agent_response({"result": result["text"], "language": target_language, "model": result["model"]}, "/translate"))


@ai_tools_bp.route("/social", methods=["POST"])
def social():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    platforms = data.get("platforms", ["twitter", "linkedin", "instagram"])
    tone = data.get("tone", "engaging")
    if not topic:
        return jsonify({"error": "topic required"}), 400

    platform_list = ", ".join(platforms) if isinstance(platforms, list) else str(platforms)
    result, err = _call_llm(
        [{"role": "user", "content": (
            f'Write {tone} social media posts for these platforms: {platform_list}. '
            f'Topic: {topic}\n\n'
            f'Return a JSON object with each platform name as a key and the post text as the value. '
            f'Respect character limits: twitter=280 chars, linkedin=3000 chars, instagram=2200 chars.'
        )}],
        system="You are a social media expert. Always respond with valid JSON only — no markdown, no preamble.",
        max_tokens=1024, endpoint="/social",
    )
    if err:
        return jsonify({"error": err}), 400
    raw = result["text"]
    structured = parse_json_from_claude(raw)
    log_payment("/social", 0.03, request.remote_addr)
    if structured:
        return jsonify(agent_response({"topic": topic, "platforms": platforms, "posts": structured, "model": result["model"]}, "/social"))
    return jsonify(agent_response({"topic": topic, "platforms": platforms, "result": raw, "model": result["model"]}, "/social"))


@ai_tools_bp.route("/sentiment", methods=["POST"])
def sentiment():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"your text here\"}"}), 400
    result = sentiment_inner(text, model=data.get("model", "claude-haiku"))
    log_payment("/sentiment", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/sentiment"))


@ai_tools_bp.route("/keywords", methods=["POST"])
def keywords():
    data = request.get_json() or {}
    text = data.get("text", "")
    max_kw = min(int(data.get("max_keywords", 10)), 30)
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"your text\", \"max_keywords\": 10}"}), 400
    result = keywords_inner(text, max_kw, model=data.get("model", "claude-haiku"))
    log_payment("/keywords", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/keywords"))


@ai_tools_bp.route("/compare", methods=["POST"])
def compare():
    data = request.get_json() or {}
    text_a = data.get("text_a", "")
    text_b = data.get("text_b", "")
    focus = data.get("focus", "")
    if not text_a or not text_b:
        return jsonify({"error": "text_a and text_b required", "hint": "POST {\"text_a\": \"...\", \"text_b\": \"...\", \"focus\": \"optional\"}"}), 400
    result = compare_inner(text_a, text_b, focus, model=data.get("model", "claude-haiku"))
    log_payment("/compare", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/compare"))


@ai_tools_bp.route("/transform", methods=["POST"])
def transform():
    data = request.get_json() or {}
    text = data.get("text", "")
    instruction = data.get("instruction", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"instruction\": \"make it formal\"}"}), 400
    if not instruction:
        return jsonify({"error": "instruction required", "hint": "e.g. 'make it formal', 'convert to bullet points', 'rewrite for a 5-year-old'"}), 400
    result = transform_inner(text, instruction, model=data.get("model", "claude-haiku"))
    log_payment("/transform", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/transform"))


@ai_tools_bp.route("/chat", methods=["POST"])
def chat():
    data = request.get_json() or {}
    messages = data.get("messages", [])
    system_prompt = data.get("system", "")
    if not messages:
        return jsonify({"error": "messages required", "hint": "POST {\"messages\": [{\"role\": \"user\", \"content\": \"hello\"}], \"system\": \"optional system prompt\"}"}), 400
    result = chat_inner(messages, system_prompt, model=data.get("model", "claude-haiku"))
    log_payment("/chat", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/chat"))


@ai_tools_bp.route("/plan", methods=["POST"])
def plan():
    data = request.get_json() or {}
    goal = data.get("goal", "")
    if not goal:
        return jsonify({"error": "goal required", "hint": "POST {\"goal\": \"launch a product\", \"context\": \"optional\", \"steps\": 7}"}), 400
    result = plan_inner(goal, data.get("context", ""), int(data.get("steps", 7)), model=data.get("model", "claude-haiku"))
    log_payment("/plan", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/plan"))


@ai_tools_bp.route("/decide", methods=["POST"])
def decide():
    data = request.get_json() or {}
    decision = data.get("decision", "")
    if not decision:
        return jsonify({"error": "decision required", "hint": "POST {\"decision\": \"...\", \"options\": [\"A\",\"B\"], \"criteria\": \"cost and speed\"}"}), 400
    result = decide_inner(decision, data.get("options"), data.get("criteria", ""), model=data.get("model", "claude-haiku"))
    log_payment("/decide", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/decide"))


@ai_tools_bp.route("/proofread", methods=["POST"])
def proofread():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"style\": \"professional\"}"}), 400
    result = proofread_inner(text, data.get("style", "professional"), model=data.get("model", "claude-haiku"))
    log_payment("/proofread", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/proofread"))


@ai_tools_bp.route("/explain", methods=["POST"])
def explain():
    data = request.get_json() or {}
    concept = data.get("concept", "")
    if not concept:
        return jsonify({"error": "concept required", "hint": "POST {\"concept\": \"quantum entanglement\", \"level\": \"beginner\"}"}), 400
    result = explain_inner(concept, data.get("level", "beginner"), data.get("analogy", True), model=data.get("model", "claude-haiku"))
    log_payment("/explain", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/explain"))


@ai_tools_bp.route("/questions", methods=["POST"])
def questions():
    data = request.get_json() or {}
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "content required", "hint": "POST {\"content\": \"...\", \"type\": \"faq|interview|quiz|comprehension\", \"count\": 5}"}), 400
    result = questions_inner(content, data.get("type", "faq"), int(data.get("count", 5)), model=data.get("model", "claude-haiku"))
    log_payment("/questions", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/questions"))


@ai_tools_bp.route("/outline", methods=["POST"])
def outline():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required", "hint": "POST {\"topic\": \"machine learning\", \"depth\": 2, \"sections\": 6}"}), 400
    result = outline_inner(topic, int(data.get("depth", 2)), int(data.get("sections", 6)), model=data.get("model", "claude-haiku"))
    log_payment("/outline", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/outline"))


@ai_tools_bp.route("/email", methods=["POST"])
def email():
    data = request.get_json() or {}
    purpose = data.get("purpose", "")
    if not purpose:
        return jsonify({"error": "purpose required", "hint": "POST {\"purpose\": \"follow up on interview\", \"tone\": \"professional\", \"recipient\": \"hiring manager\"}"}), 400
    result = email_inner(purpose, data.get("tone", "professional"), data.get("context", ""), data.get("recipient", ""), data.get("length", "medium"), model=data.get("model", "claude-haiku"))
    log_payment("/email", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/email"))


@ai_tools_bp.route("/sql", methods=["POST"])
def sql():
    data = request.get_json() or {}
    description = data.get("description", "")
    if not description:
        return jsonify({"error": "description required", "hint": "POST {\"description\": \"get all users who signed up last month\", \"dialect\": \"postgresql\", \"schema\": \"optional\"}"}), 400
    result = sql_inner(description, data.get("dialect", "postgresql"), data.get("schema", ""), model=data.get("model", "claude-haiku"))
    log_payment("/sql", 0.05, request.remote_addr)
    return jsonify(agent_response(result, "/sql"))


@ai_tools_bp.route("/regex", methods=["POST"])
def regex():
    data = request.get_json() or {}
    description = data.get("description", "")
    if not description:
        return jsonify({"error": "description required", "hint": "POST {\"description\": \"match email addresses\", \"language\": \"python\"}"}), 400
    result = regex_inner(description, data.get("language", "python"), data.get("flags", ""), model=data.get("model", "claude-haiku"))
    log_payment("/regex", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/regex"))


@ai_tools_bp.route("/mock", methods=["POST"])
def mock():
    data = request.get_json() or {}
    description = data.get("description", "")
    if not description:
        return jsonify({"error": "description required", "hint": "POST {\"description\": \"user profiles with name, email, age\", \"count\": 5, \"format\": \"json\"}"}), 400
    result = mock_inner(description, min(int(data.get("count", 5)), 50), data.get("format", "json"), model=data.get("model", "claude-haiku"))
    log_payment("/mock", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/mock"))


@ai_tools_bp.route("/score", methods=["POST"])
def score():
    data = request.get_json() or {}
    content = data.get("content", "")
    criteria = data.get("criteria", ["clarity", "accuracy", "engagement"])
    if not content:
        return jsonify({"error": "content required", "hint": "POST {\"content\": \"...\", \"criteria\": [\"clarity\", \"accuracy\"], \"scale\": 10}"}), 400
    result = score_inner(content, criteria, int(data.get("scale", 10)), model=data.get("model", "claude-haiku"))
    log_payment("/score", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/score"))


@ai_tools_bp.route("/timeline", methods=["POST"])
def timeline():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"direction\": \"chronological\"}"}), 400
    result = timeline_inner(text, data.get("direction", "chronological"), model=data.get("model", "claude-haiku"))
    log_payment("/timeline", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/timeline"))


@ai_tools_bp.route("/action", methods=["POST"])
def action():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"meeting notes or any text with tasks\"}"}), 400
    result = action_inner(text, model=data.get("model", "claude-haiku"))
    log_payment("/action", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/action"))


@ai_tools_bp.route("/pitch", methods=["POST"])
def pitch():
    data = request.get_json() or {}
    product = data.get("product", "")
    if not product:
        return jsonify({"error": "product required", "hint": "POST {\"product\": \"...\", \"audience\": \"investors\", \"length\": \"30s\"}"}), 400
    result = pitch_inner(product, data.get("audience", ""), data.get("length", "30s"), model=data.get("model", "claude-haiku"))
    log_payment("/pitch", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/pitch"))


@ai_tools_bp.route("/debate", methods=["POST"])
def debate():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    if not topic:
        return jsonify({"error": "topic required", "hint": "POST {\"topic\": \"AI will replace programmers\", \"perspective\": \"balanced\"}"}), 400
    result = debate_inner(topic, data.get("perspective", "balanced"), model=data.get("model", "claude-haiku"))
    log_payment("/debate", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/debate"))


@ai_tools_bp.route("/headline", methods=["POST"])
def headline():
    data = request.get_json() or {}
    content = data.get("content", "")
    if not content:
        return jsonify({"error": "content required", "hint": "POST {\"content\": \"...\", \"count\": 5, \"style\": \"engaging\"}"}), 400
    result = headline_inner(content, int(data.get("count", 5)), data.get("style", "engaging"), model=data.get("model", "claude-haiku"))
    log_payment("/headline", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/headline"))


@ai_tools_bp.route("/fact", methods=["POST"])
def fact():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"count\": 10}"}), 400
    result = fact_inner(text, int(data.get("count", 10)), model=data.get("model", "claude-haiku"))
    log_payment("/fact", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/fact"))


@ai_tools_bp.route("/rewrite", methods=["POST"])
def rewrite():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"audience\": \"5th grader\", \"tone\": \"friendly\"}"}), 400
    result = rewrite_inner(text, data.get("audience", "general audience"), data.get("tone", "neutral"), model=data.get("model", "claude-haiku"))
    log_payment("/rewrite", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/rewrite"))


@ai_tools_bp.route("/tag", methods=["POST"])
def tag():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"taxonomy\": [\"tech\", \"ai\", \"business\"], \"max_tags\": 10}"}), 400
    result = tag_inner(text, data.get("taxonomy"), int(data.get("max_tags", 10)), model=data.get("model", "claude-haiku"))
    log_payment("/tag", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/tag"))


def think_inner(problem, context="", tools=None, max_steps=5, model="claude-haiku"):
    """Autonomous chain-of-thought reasoning. Breaks a problem down, optionally calls internal tools, returns structured solution."""
    if not problem:
        return {"error": "problem required"}

    available_tools = list(BATCH_HANDLERS.keys())
    tool_list = tools if tools else available_tools

    system = (
        "You are an autonomous reasoning agent. Think step-by-step to solve the problem.\n"
        "For each step, output JSON with keys:\n"
        '  "thought": your reasoning for this step,\n'
        '  "action": tool to call (or "none" if pure reasoning),\n'
        '  "action_input": input for the tool (object),\n'
        '  "observation": what you learned (fill after tool call),\n'
        '  "is_final": true if this is your final answer.\n'
        "When is_final is true, also include:\n"
        '  "answer": your final answer,\n'
        '  "confidence": 0.0-1.0 confidence score.\n'
        f"Available tools: {tool_list}\n"
        "Respond with a JSON array of step objects. Do NOT use markdown."
    )
    prompt = f"Problem: {problem}"
    if context:
        prompt += f"\n\nContext: {context}"

    r = call_model(model, [{"role": "user", "content": prompt}],
        system=system, max_tokens=2048)
    raw = r["text"]
    parsed = parse_json_from_claude(raw)

    # If the model suggested tool calls, execute them
    steps_executed = []
    if isinstance(parsed, list):
        for i, step in enumerate(parsed[:max_steps]):
            action = step.get("action", "none")
            if action != "none" and action in BATCH_HANDLERS:
                try:
                    tool_result = BATCH_HANDLERS[action](step.get("action_input", {}))
                    step["observation"] = tool_result.get("result") or tool_result.get("summary") or str(tool_result)[:500]
                except Exception as e:
                    step["observation"] = f"Tool error: {str(e)}"
            steps_executed.append(step)

        # If no final answer yet, do a synthesis pass
        final = next((s for s in steps_executed if s.get("is_final")), None)
        if not final:
            observations = "\n".join(f"Step {i+1}: {s.get('thought','')} → {s.get('observation','')}" for i, s in enumerate(steps_executed))
            synth = call_model(model, [{"role": "user", "content": f"Based on these reasoning steps, give a final answer.\n\n{observations}\n\nOriginal problem: {problem}"}],
                system="Give a clear, direct answer. Respond with JSON: {\"answer\": \"...\", \"confidence\": 0.0-1.0}", max_tokens=1024)
            final_parsed = parse_json_from_claude(synth["text"])
            if final_parsed:
                steps_executed.append({"thought": "synthesis", "is_final": True, **final_parsed})
            else:
                steps_executed.append({"thought": "synthesis", "is_final": True, "answer": synth["text"], "confidence": 0.5})

        return {"problem": problem, "steps": steps_executed, "model": r["model"],
                "answer": next((s.get("answer") for s in reversed(steps_executed) if s.get("is_final")), raw),
                "confidence": next((s.get("confidence") for s in reversed(steps_executed) if s.get("is_final")), None)}
    else:
        return {"problem": problem, "model": r["model"], "steps": [], "answer": parsed or raw, "confidence": 0.5}


# ── New Auto-Added Tools ──────────────────────────────────────────────────────

def review_code_inner(code, language="auto", focus="quality", model="claude-haiku"):
    """Review code for quality, security, and performance issues."""
    if not code:
        return {"error": "code required"}
    r = call_model(model, [{"role": "user", "content": f"Review this {language} code. Focus: {focus}.\n\nReturn JSON with keys: \"issues\" (array of {{severity, line, issue, fix}}), \"score\" (1-10), \"summary\" (string).\n\n```\n{code}\n```"}],
        system="You are a senior code reviewer. Always respond with valid JSON only.", max_tokens=2048)
    parsed = parse_json_from_claude(r["text"])
    return {"language": language, "focus": focus, "model": r["model"], **(parsed if parsed else {"result": r["text"]})}


def generate_docs_inner(code, style="jsdoc", model="claude-haiku"):
    """Generate documentation for code."""
    if not code:
        return {"error": "code required"}
    r = call_model(model, [{"role": "user", "content": f"Generate {style} documentation for this code. Return the fully documented code.\n\n```\n{code}\n```"}],
        system="You are a documentation expert. Return documented code only.", max_tokens=2048)
    return {"style": style, "model": r["model"], "documented_code": r["text"]}


def convert_code_inner(code, from_lang="auto", to_lang="python", model="claude-haiku"):
    """Convert code from one language to another."""
    if not code or not to_lang:
        return {"error": "code and to_lang required"}
    r = call_model(model, [{"role": "user", "content": f"Convert this {from_lang} code to {to_lang}. Return only the converted code.\n\n```\n{code}\n```"}],
        system="You are a polyglot programmer. Return only the converted code, no explanation.", max_tokens=2048)
    return {"from": from_lang, "to": to_lang, "model": r["model"], "converted_code": r["text"]}


def generate_api_spec_inner(description, format="openapi", model="claude-haiku"):
    """Generate API specification from description."""
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": f"Generate a {format} 3.0 specification (YAML) for this API:\n\n{description}"}],
        system="You are an API architect. Return valid OpenAPI YAML only.", max_tokens=4096)
    return {"format": format, "model": r["model"], "spec": r["text"]}


def diff_inner(text_a, text_b, model="claude-haiku"):
    """Analyze differences between two texts or code snippets."""
    if not text_a or not text_b:
        return {"error": "text_a and text_b required"}
    r = call_model(model, [{"role": "user", "content": f"Compare these two texts and explain the differences. Return JSON with keys: \"changes\" (array of {{type, description}}), \"summary\" (string), \"similarity_pct\" (number).\n\nText A:\n{text_a}\n\nText B:\n{text_b}"}],
        system="You are a diff analysis expert. Always respond with valid JSON only.", max_tokens=2048)
    parsed = parse_json_from_claude(r["text"])
    return {"model": r["model"], **(parsed if parsed else {"result": r["text"]})}


def parse_csv_inner(csv_text, question="", model="claude-haiku"):
    """Analyze CSV data and answer questions about it."""
    if not csv_text:
        return {"error": "csv_text required"}
    prompt = f"Analyze this CSV data."
    if question:
        prompt += f" Answer: {question}"
    prompt += f"\n\nReturn JSON with keys: \"columns\" (array), \"row_count\" (int), \"insights\" (array of strings), \"answer\" (string if question asked).\n\n{csv_text[:5000]}"
    r = call_model(model, [{"role": "user", "content": prompt}],
        system="You are a data analyst. Always respond with valid JSON only.", max_tokens=2048)
    parsed = parse_json_from_claude(r["text"])
    return {"model": r["model"], **(parsed if parsed else {"result": r["text"]})}


def cron_expr_inner(description, model="claude-haiku"):
    """Generate or explain cron expressions."""
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": f"Return JSON with keys: \"cron\" (the cron expression), \"explanation\" (human readable), \"next_5_runs\" (array of example timestamps).\n\n{description}"}],
        system="You are a cron/scheduling expert. Always respond with valid JSON only.", max_tokens=512)
    parsed = parse_json_from_claude(r["text"])
    return {"model": r["model"], **(parsed if parsed else {"result": r["text"]})}


def changelog_inner(commits, version="", model="claude-haiku"):
    """Generate a changelog from commit messages."""
    if not commits:
        return {"error": "commits required (string or array)"}
    commit_text = "\n".join(commits) if isinstance(commits, list) else commits
    r = call_model(model, [{"role": "user", "content": f"Generate a professional changelog{' for version ' + version if version else ''}. Group by: Added, Changed, Fixed, Removed. Use markdown format.\n\nCommits:\n{commit_text}"}],
        system="You are a release manager. Generate clean, user-facing changelogs.", max_tokens=2048)
    return {"version": version, "model": r["model"], "changelog": r["text"]}


def name_generator_inner(description, count=10, style="startup", model="claude-haiku"):
    """Generate names for products, companies, features, etc."""
    if not description:
        return {"error": "description required"}
    r = call_model(model, [{"role": "user", "content": f"Generate {count} {style}-style names for: {description}\n\nReturn JSON with keys: \"names\" (array of {{name, tagline, available_domain}})"}],
        system="You are a naming and branding expert. Always respond with valid JSON only.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"])
    return {"style": style, "model": r["model"], **(parsed if parsed else {"result": r["text"]})}


def privacy_check_inner(text, model="claude-haiku"):
    """Scan text for PII, secrets, and sensitive data."""
    if not text:
        return {"error": "text required"}
    r = call_model(model, [{"role": "user", "content": f"Scan this text for PII and sensitive data. Return JSON with keys: \"found\" (array of {{type, value_redacted, location}}), \"risk_level\" (low/medium/high), \"recommendation\" (string).\n\n{text[:5000]}"}],
        system="You are a data privacy expert. Always respond with valid JSON only. Redact actual sensitive values.", max_tokens=1024)
    parsed = parse_json_from_claude(r["text"])
    return {"model": r["model"], **(parsed if parsed else {"result": r["text"]})}


# Routes for new tools

@ai_tools_bp.route("/review-code", methods=["POST"])
def review_code():
    data = request.get_json() or {}
    code = data.get("code", "")
    if not code:
        return jsonify({"error": "code required", "hint": "POST {\"code\": \"...\", \"language\": \"python\", \"focus\": \"security\"}"}), 400
    result = review_code_inner(code, data.get("language", "auto"), data.get("focus", "quality"), model=data.get("model", "claude-haiku"))
    log_payment("/review-code", 0.05, request.remote_addr)
    return jsonify(agent_response(result, "/review-code"))


@ai_tools_bp.route("/generate-docs", methods=["POST"])
def generate_docs():
    data = request.get_json() or {}
    code = data.get("code", "")
    if not code:
        return jsonify({"error": "code required"}), 400
    result = generate_docs_inner(code, data.get("style", "jsdoc"), model=data.get("model", "claude-haiku"))
    log_payment("/generate-docs", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/generate-docs"))


@ai_tools_bp.route("/convert-code", methods=["POST"])
def convert_code():
    data = request.get_json() or {}
    code = data.get("code", "")
    if not code:
        return jsonify({"error": "code required", "hint": "POST {\"code\": \"...\", \"to_lang\": \"python\"}"}), 400
    result = convert_code_inner(code, data.get("from_lang", "auto"), data.get("to_lang", "python"), model=data.get("model", "claude-haiku"))
    log_payment("/convert-code", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/convert-code"))


@ai_tools_bp.route("/generate-api-spec", methods=["POST"])
def generate_api_spec():
    data = request.get_json() or {}
    desc = data.get("description", "")
    if not desc:
        return jsonify({"error": "description required"}), 400
    result = generate_api_spec_inner(desc, data.get("format", "openapi"), model=data.get("model", "claude-haiku"))
    log_payment("/generate-api-spec", 0.05, request.remote_addr)
    return jsonify(agent_response(result, "/generate-api-spec"))


@ai_tools_bp.route("/diff", methods=["POST"])
def diff():
    data = request.get_json() or {}
    if not data.get("text_a") or not data.get("text_b"):
        return jsonify({"error": "text_a and text_b required"}), 400
    result = diff_inner(data["text_a"], data["text_b"], model=data.get("model", "claude-haiku"))
    log_payment("/diff", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/diff"))


@ai_tools_bp.route("/parse-csv", methods=["POST"])
def parse_csv():
    data = request.get_json() or {}
    csv_text = data.get("csv_text", "")
    if not csv_text:
        return jsonify({"error": "csv_text required"}), 400
    result = parse_csv_inner(csv_text, data.get("question", ""), model=data.get("model", "claude-haiku"))
    log_payment("/parse-csv", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/parse-csv"))


@ai_tools_bp.route("/cron", methods=["POST"])
def cron():
    data = request.get_json() or {}
    desc = data.get("description", "")
    if not desc:
        return jsonify({"error": "description required", "hint": "POST {\"description\": \"every weekday at 9am\"}"}), 400
    result = cron_expr_inner(desc, model=data.get("model", "claude-haiku"))
    log_payment("/cron", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/cron"))


@ai_tools_bp.route("/changelog", methods=["POST"])
def changelog():
    data = request.get_json() or {}
    commits = data.get("commits", "")
    if not commits:
        return jsonify({"error": "commits required (string or array)"}), 400
    result = changelog_inner(commits, data.get("version", ""), model=data.get("model", "claude-haiku"))
    log_payment("/changelog", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/changelog"))


@ai_tools_bp.route("/name-generator", methods=["POST"])
def name_generator():
    data = request.get_json() or {}
    desc = data.get("description", "")
    if not desc:
        return jsonify({"error": "description required"}), 400
    result = name_generator_inner(desc, int(data.get("count", 10)), data.get("style", "startup"), model=data.get("model", "claude-haiku"))
    log_payment("/name-generator", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/name-generator"))


@ai_tools_bp.route("/privacy-check", methods=["POST"])
def privacy_check():
    data = request.get_json() or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "text required"}), 400
    result = privacy_check_inner(text, model=data.get("model", "claude-haiku"))
    log_payment("/privacy-check", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/privacy-check"))


@ai_tools_bp.route("/think", methods=["POST"])
def think():
    data = request.get_json() or {}
    problem = data.get("problem", "")
    if not problem:
        return jsonify({"error": "problem required", "hint": "POST {\"problem\": \"How do I...\", \"context\": \"optional\", \"max_steps\": 5}"}), 400
    result = think_inner(problem, data.get("context", ""), data.get("tools"), int(data.get("max_steps", 5)), model=data.get("model", "claude-haiku"))
    log_payment("/think", 0.10, request.remote_addr)
    return jsonify(agent_response(result, "/think"))


@ai_tools_bp.route("/pipeline", methods=["POST"])
def pipeline():
    data = request.get_json() or {}
    steps = data.get("steps", [])
    if not steps:
        return jsonify({"error": "steps array required", "hint": "POST {\"steps\": [{\"endpoint\": \"research\", \"input\": {\"topic\": \"AI\"}}, {\"endpoint\": \"summarize\", \"input\": {\"text\": \"{{prev}}\"}}]}"}), 400
    result = pipeline_inner(steps)
    log_payment("/pipeline", 0.15, request.remote_addr)
    return jsonify(agent_response(result, "/pipeline"))


@ai_tools_bp.route("/extract", methods=["POST"])
def extract():
    data = request.get_json() or {}
    url = data.get("url", "")
    text = data.get("text", "")
    schema_desc = data.get("schema", "")
    fields = data.get("fields", [])

    # URL mode: scrape URL first, then extract
    if url:
        if not schema_desc and not fields:
            return jsonify({"error": "schema or fields required with url", "hint": "POST {\"url\": \"...\", \"schema\": {\"field\": \"description\"}}"}), 400
        scraped = scrape_url(url)
        if "error" in scraped:
            return jsonify(scraped), 422
        text = scraped["text"][:6000]

    if not text:
        return jsonify({"error": "text or url required", "hint": "POST {\"text\": \"...\", \"fields\": [\"name\", \"date\"]} or {\"url\": \"...\", \"schema\": {}}"}), 400
    result = extract_inner(text, schema_desc, fields, model=data.get("model", "claude-haiku"))
    log_payment("/extract", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/extract"))


@ai_tools_bp.route("/qa", methods=["POST"])
def qa():
    data = request.get_json() or {}
    context = data.get("context", "")
    question = data.get("question", "")
    if not context:
        return jsonify({"error": "context required", "hint": "POST {\"context\": \"document text\", \"question\": \"your question\"}"}), 400
    if not question:
        return jsonify({"error": "question required"}), 400
    result = qa_inner(context, question, model=data.get("model", "claude-haiku"))
    log_payment("/qa", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/qa"))


@ai_tools_bp.route("/classify", methods=["POST"])
def classify():
    data = request.get_json() or {}
    text = data.get("text", "")
    categories = data.get("categories", [])
    if not text:
        return jsonify({"error": "text required", "hint": "POST {\"text\": \"...\", \"categories\": [\"positive\", \"negative\"]}"}), 400
    if not categories:
        return jsonify({"error": "categories required", "hint": "Provide an array of category strings"}), 400
    result = classify_inner(text, categories, model=data.get("model", "claude-haiku"))
    log_payment("/classify", 0.01, request.remote_addr)
    return jsonify(agent_response(result, "/classify"))


@ai_tools_bp.route("/batch", methods=["POST"])
def batch():
    """Run up to 5 AI operations in one payment. $0.10 flat."""
    data = request.get_json() or {}
    ops = data.get("operations", [])
    if not ops or not isinstance(ops, list):
        return jsonify({"error": "operations array required", "hint": "POST {\"operations\": [{\"endpoint\": \"research\", \"input\": {\"topic\": \"AI\"}}]}"}), 400
    if len(ops) > 5:
        return jsonify({"error": "max 5 operations per batch"}), 400

    results = []
    for op in ops:
        endpoint = op.get("endpoint", "").lstrip("/")
        inp = op.get("input", {})
        handler = BATCH_HANDLERS.get(endpoint)
        if not handler:
            results.append({"endpoint": endpoint, "error": f"unknown endpoint '{endpoint}'. Valid: {list(BATCH_HANDLERS.keys())}"})
        else:
            try:
                result = handler(inp)
                results.append({"endpoint": endpoint, **result})
            except Exception as e:
                results.append({"endpoint": endpoint, "error": str(e)})

    log_payment("/batch", 0.10, request.remote_addr)
    return jsonify(agent_response({"results": results, "count": len(results)}, "/batch"))


@ai_tools_bp.route("/vision", methods=["POST"])
def vision():
    data = request.get_json() or {}
    image_url = data.get("url") or data.get("image_url")
    question = data.get("question", "Describe this image in detail")
    if not image_url:
        return jsonify({"error": "url required"}), 400
    try:
        from security import validate_url, SSRFError
        validate_url(image_url, allow_http=True)
    except SSRFError:
        return jsonify({"error": "URL blocked by SSRF protection"}), 400
    try:
        result = vision_inner(image_url, question, model=data.get("model", "claude-haiku"))
        log_payment("/vision", 0.05, request.remote_addr)
        return jsonify(agent_response(result, "/vision"))
    except Exception as e:
        return jsonify({"error": "Vision processing failed"}), 502


@ai_tools_bp.route("/rag", methods=["POST"])
def rag():
    data = request.get_json() or {}
    documents = data.get("documents", "")
    query = data.get("query", "")
    if not documents or not query:
        return jsonify({"error": "documents and query required"}), 400
    result = rag_inner(documents, query, model=data.get("model", "claude-haiku"))
    log_payment("/rag", 0.05, request.remote_addr)
    return jsonify(agent_response({"query": query, **result}, "/rag"))


@ai_tools_bp.route("/diagram", methods=["POST"])
def diagram():
    data = request.get_json() or {}
    description = data.get("description", "")
    diagram_type = data.get("type", "flowchart")
    if not description:
        return jsonify({"error": "description required"}), 400
    result = diagram_inner(description, diagram_type, model=data.get("model", "claude-haiku"))
    log_payment("/diagram", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/diagram"))


@ai_tools_bp.route("/json-schema", methods=["POST"])
def json_schema_route():
    data = request.get_json() or {}
    description = data.get("description", "")
    example = data.get("example", "")
    if not description:
        return jsonify({"error": "description required"}), 400
    result = json_schema_inner(description, example, model=data.get("model", "claude-haiku"))
    log_payment("/json-schema", 0.02, request.remote_addr)
    return jsonify(agent_response(result, "/json-schema"))


@ai_tools_bp.route("/test-cases", methods=["POST"])
def test_cases_route():
    data = request.get_json() or {}
    code_or_desc = data.get("code") or data.get("description", "")
    language = data.get("language", "python")
    if not code_or_desc:
        return jsonify({"error": "code or description required"}), 400
    result = test_cases_inner(code_or_desc, language, model=data.get("model", "claude-haiku"))
    log_payment("/test-cases", 0.03, request.remote_addr)
    return jsonify(agent_response(result, "/test-cases"))


@ai_tools_bp.route("/workflow", methods=["POST"])
def workflow_route():
    data = request.get_json() or {}
    goal = data.get("goal", "")
    available_data = data.get("data", data.get("context", ""))
    if not goal:
        return jsonify({"error": "goal required"}), 400
    result = workflow_inner(goal, available_data, model=data.get("model", "claude-sonnet"))
    log_payment("/workflow", 0.20, request.remote_addr)
    return jsonify(agent_response(result, "/workflow"))


@ai_tools_bp.route("/code/run", methods=["POST"])
def code_run():
    import subprocess
    import time as _time
    from security import validate_code_safety, SandboxViolation, get_sandbox_env
    data = request.get_json() or {}
    code = data.get("code", "")
    timeout = min(int(data.get("timeout", 10)), 15)
    if not code:
        return jsonify({"error": "code required"}), 400
    if len(code) > 5000:
        return jsonify({"error": "code too long (max 5000 chars)"}), 400
    # AST-based sandbox validation
    try:
        validate_code_safety(code)
    except SandboxViolation as e:
        return jsonify({"error": f"Sandbox violation: {e}"}), 403
    start = _time.time()
    try:
        result = subprocess.run(
            ["python3", "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=get_sandbox_env(),
            cwd="/tmp",
        )
        elapsed = int((_time.time() - start) * 1000)
        log_payment("/code/run", 0.05, request.remote_addr)
        return jsonify(agent_response({
            "stdout": result.stdout[:3000],
            "stderr": result.stderr[:500],
            "returncode": result.returncode,
            "execution_time_ms": elapsed,
        }, "/code/run"))
    except subprocess.TimeoutExpired:
        return jsonify({"error": "timeout", "message": f"Code exceeded {timeout}s limit"}), 408


@ai_tools_bp.route("/web/search", methods=["GET", "POST"])
def web_search():
    if request.method == "POST":
        body = request.get_json() or {}
        q = body.get("query", body.get("q", ""))
        n = min(int(body.get("n", 10)), 25)
    else:
        q = request.args.get("q", "")
        n = min(int(request.args.get("n", 10)), 25)
    if not q:
        return jsonify({"error": "q (query) required"}), 400
    try:
        resp = _requests.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10,
        )
        data = resp.json()
        results = [
            {
                "title": t.get("Text", ""),
                "url": t.get("FirstURL", ""),
                "snippet": t.get("Result", ""),
            }
            for t in data.get("RelatedTopics", [])[:n]
            if t.get("FirstURL")
        ]
        log_payment("/web/search", 0.02, request.remote_addr)
        return jsonify(agent_response({
            "query": q,
            "instant_answer": data.get("AbstractText", ""),
            "answer_type": data.get("Type", ""),
            "results": results,
            "count": len(results),
        }, "/web/search"))
    except Exception as e:
        return jsonify({"error": "search_failed", "message": str(e)}), 502


@ai_tools_bp.route("/enrich", methods=["POST"])
def enrich():
    data = request.get_json() or {}
    entity = data.get("entity", "")
    entity_type = data.get("type", "").lower()
    if not entity or not entity_type:
        return jsonify({"error": "entity and type required (type: ip|crypto|country|company)"}), 400

    raw = {}
    try:
        if entity_type == "ip":
            raw = _requests.get(f"http://ip-api.com/json/{entity}", timeout=8).json()
        elif entity_type == "crypto":
            resp = _requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": entity, "vs_currencies": "usd,eur,gbp", "include_24hr_change": "true", "include_market_cap": "true"},
                timeout=8,
            ).json()
            raw = {"prices": resp, "symbol": entity}
        elif entity_type == "country":
            resp = _requests.get(
                f"https://restcountries.com/v3.1/name/{entity}",
                params={"fields": "name,capital,currencies,languages,population,flags,region"},
                timeout=8,
            ).json()
            raw = resp[0] if resp else {}
        elif entity_type == "company":
            resp = _requests.get(
                "https://api.duckduckgo.com/",
                params={"q": entity, "format": "json", "no_html": 1},
                timeout=8,
            ).json()
            raw = {"abstract": resp.get("AbstractText", ""), "url": resp.get("AbstractURL", ""), "image": resp.get("Image", "")}
        else:
            return jsonify({"error": f"unknown type '{entity_type}'. Use: ip, crypto, country, company"}), 400
    except Exception as e:
        return jsonify({"error": "data_fetch_failed", "message": str(e)}), 502

    llm_result, llm_err = _call_llm(
        [{"role": "user", "content": (
            f'Synthesize this data about the {entity_type} entity "{entity}" into a structured profile. '
            f'Return JSON with: "summary" (2-3 sentence overview), "key_facts" (array of 5 bullet strings), "risk_level" (low/medium/high, if applicable), "sources" (array of source names used). '
            f'Raw data:\n{json.dumps(raw)[:2000]}'
        )}],
        system="You are a data analyst. Respond with valid JSON only — no markdown, no preamble.",
        max_tokens=512, endpoint="/enrich",
    )
    if llm_err:
        return jsonify({"error": llm_err}), 400
    profile = parse_json_from_claude(llm_result["text"]) or {}
    log_payment("/enrich", 0.05, request.remote_addr)
    return jsonify(agent_response({
        "entity": entity,
        "type": entity_type,
        "raw_data": raw,
        "profile": profile,
    }, "/enrich"))


# ── BATCH_HANDLERS dict ────────────────────────────────────────────────────────

BATCH_HANDLERS = {
    "research": lambda d: research_inner(d.get("topic", ""), model=d.get("model", "claude-haiku")),
    "summarize": lambda d: summarize_inner(d.get("text", ""), d.get("length", "short"), model=d.get("model", "claude-haiku")),
    "analyze": lambda d: analyze_inner(d.get("content", ""), d.get("question", "Provide a structured analysis"), model=d.get("model", "claude-haiku")),
    "translate": lambda d: translate_inner(d.get("text", ""), d.get("language", "Spanish"), model=d.get("model", "claude-haiku")),
    "social": lambda d: social_inner(d.get("topic", ""), d.get("platforms", ["twitter", "linkedin", "instagram"]), d.get("tone", "engaging"), model=d.get("model", "claude-haiku")),
    "write": lambda d: write_inner(d.get("spec", ""), d.get("type", "article"), model=d.get("model", "claude-haiku")),
    "code": lambda d: code_inner(d.get("description", ""), d.get("language", "Python"), model=d.get("model", "claude-haiku")),
    "extract": lambda d: extract_inner(d.get("text", ""), d.get("schema", ""), d.get("fields", []), model=d.get("model", "claude-haiku")),
    "qa": lambda d: qa_inner(d.get("context", ""), d.get("question", ""), model=d.get("model", "claude-haiku")),
    "classify": lambda d: classify_inner(d.get("text", ""), d.get("categories", []), model=d.get("model", "claude-haiku")),
    "sentiment": lambda d: sentiment_inner(d.get("text", ""), model=d.get("model", "claude-haiku")),
    "keywords": lambda d: keywords_inner(d.get("text", ""), d.get("max_keywords", 10), model=d.get("model", "claude-haiku")),
    "compare": lambda d: compare_inner(d.get("text_a", ""), d.get("text_b", ""), d.get("focus", ""), model=d.get("model", "claude-haiku")),
    "transform": lambda d: transform_inner(d.get("text", ""), d.get("instruction", ""), model=d.get("model", "claude-haiku")),
    "chat": lambda d: chat_inner(d.get("messages", []), d.get("system", ""), model=d.get("model", "claude-haiku")),
    "plan": lambda d: plan_inner(d.get("goal", ""), d.get("context", ""), int(d.get("steps", 7)), model=d.get("model", "claude-haiku")),
    "decide": lambda d: decide_inner(d.get("decision", ""), d.get("options"), d.get("criteria", ""), model=d.get("model", "claude-haiku")),
    "proofread": lambda d: proofread_inner(d.get("text", ""), d.get("style", "professional"), model=d.get("model", "claude-haiku")),
    "explain": lambda d: explain_inner(d.get("concept", ""), d.get("level", "beginner"), d.get("analogy", True), model=d.get("model", "claude-haiku")),
    "questions": lambda d: questions_inner(d.get("content", ""), d.get("type", "faq"), int(d.get("count", 5)), model=d.get("model", "claude-haiku")),
    "outline": lambda d: outline_inner(d.get("topic", ""), int(d.get("depth", 2)), int(d.get("sections", 6)), model=d.get("model", "claude-haiku")),
    "email": lambda d: email_inner(d.get("purpose", ""), d.get("tone", "professional"), d.get("context", ""), d.get("recipient", ""), d.get("length", "medium"), model=d.get("model", "claude-haiku")),
    "sql": lambda d: sql_inner(d.get("description", ""), d.get("dialect", "postgresql"), d.get("schema", ""), model=d.get("model", "claude-haiku")),
    "regex": lambda d: regex_inner(d.get("description", ""), d.get("language", "python"), d.get("flags", ""), model=d.get("model", "claude-haiku")),
    "mock": lambda d: mock_inner(d.get("description", ""), int(d.get("count", 5)), d.get("format", "json"), model=d.get("model", "claude-haiku")),
    "score": lambda d: score_inner(d.get("content", ""), d.get("criteria", ["clarity", "accuracy", "engagement"]), int(d.get("scale", 10)), model=d.get("model", "claude-haiku")),
    "timeline": lambda d: timeline_inner(d.get("text", ""), d.get("direction", "chronological"), model=d.get("model", "claude-haiku")),
    "action": lambda d: action_inner(d.get("text", ""), model=d.get("model", "claude-haiku")),
    "pitch": lambda d: pitch_inner(d.get("product", ""), d.get("audience", ""), d.get("length", "30s"), model=d.get("model", "claude-haiku")),
    "debate": lambda d: debate_inner(d.get("topic", ""), d.get("perspective", "balanced"), model=d.get("model", "claude-haiku")),
    "headline": lambda d: headline_inner(d.get("content", ""), int(d.get("count", 5)), d.get("style", "engaging"), model=d.get("model", "claude-haiku")),
    "fact": lambda d: fact_inner(d.get("text", ""), int(d.get("count", 10)), model=d.get("model", "claude-haiku")),
    "rewrite": lambda d: rewrite_inner(d.get("text", ""), d.get("audience", "general audience"), d.get("tone", "neutral"), model=d.get("model", "claude-haiku")),
    "tag": lambda d: tag_inner(d.get("text", ""), d.get("taxonomy"), int(d.get("max_tags", 10)), model=d.get("model", "claude-haiku")),
    "think": lambda d: think_inner(d.get("problem", ""), d.get("context", ""), d.get("tools", []), int(d.get("max_steps", 5)), model=d.get("model", "claude-haiku")),
    "review_code": lambda d: review_code_inner(d.get("code", ""), d.get("language", "auto"), d.get("focus", "quality"), model=d.get("model", "claude-haiku")),
    "generate_docs": lambda d: generate_docs_inner(d.get("code", ""), d.get("style", "jsdoc"), model=d.get("model", "claude-haiku")),
    "convert_code": lambda d: convert_code_inner(d.get("code", ""), d.get("from_lang", "auto"), d.get("to_lang", "python"), model=d.get("model", "claude-haiku")),
    "generate_api_spec": lambda d: generate_api_spec_inner(d.get("description", ""), d.get("format", "openapi"), model=d.get("model", "claude-haiku")),
    "diff": lambda d: diff_inner(d.get("text_a", ""), d.get("text_b", ""), model=d.get("model", "claude-haiku")),
    "parse_csv": lambda d: parse_csv_inner(d.get("csv_text", ""), d.get("question", ""), model=d.get("model", "claude-haiku")),
    "cron": lambda d: cron_expr_inner(d.get("description", ""), model=d.get("model", "claude-haiku")),
    "changelog": lambda d: changelog_inner(d.get("commits", ""), d.get("version", ""), model=d.get("model", "claude-haiku")),
    "name_generator": lambda d: name_generator_inner(d.get("description", ""), int(d.get("count", 10)), d.get("style", "startup"), model=d.get("model", "claude-haiku")),
    "privacy_check": lambda d: privacy_check_inner(d.get("text", ""), model=d.get("model", "claude-haiku")),
}
