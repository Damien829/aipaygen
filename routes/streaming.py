import json
from flask import Blueprint, request, jsonify, Response, stream_with_context
from model_router import call_model_stream
from helpers import log_payment

streaming_bp = Blueprint("streaming", __name__)


def _enforce_model(requested_model: str) -> str:
    """Enforce model restrictions based on pricing tier.
    Free tier and flat pricing: haiku only. Metered: user's choice."""
    if request.environ.get("X_FREE_TIER") == "1":
        return "claude-haiku"
    if request.environ.get("X_PRICING_MODE", "") == "flat":
        return "claude-haiku"
    return requested_model


@streaming_bp.route("/stream/research", methods=["POST"])
def stream_research():
    data = request.get_json() or {}
    topic = data.get("topic", "")
    model_name = _enforce_model(data.get("model", "auto"))
    if not topic:
        return jsonify({"error": "topic required"}), 400

    def generate():
        for chunk in call_model_stream(
            model_name,
            [{"role": "user", "content": f"Research: {topic}"}],
            system="You are a research assistant. Stream a concise research summary on the given topic.",
            max_tokens=800,
        ):
            if chunk.get("done"):
                yield f"data: {json.dumps({'done': True, 'endpoint': '/stream/research', 'model': chunk.get('model'), 'cost_usd': chunk.get('cost_usd')})}\n\n"
                log_payment("/stream/research", chunk.get("cost_usd", 0.01), request.remote_addr)
            else:
                yield f"data: {json.dumps({'text': chunk['text']})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@streaming_bp.route("/stream/write", methods=["POST"])
def stream_write():
    data = request.get_json() or {}
    prompt = data.get("prompt", "")
    style = data.get("style", "professional")
    model_name = _enforce_model(data.get("model", "auto"))
    if not prompt:
        return jsonify({"error": "prompt required"}), 400

    def generate():
        for chunk in call_model_stream(
            model_name,
            [{"role": "user", "content": prompt}],
            system=f"You are a skilled writer. Write in a {style} style.",
            max_tokens=1200,
        ):
            if chunk.get("done"):
                yield f"data: {json.dumps({'done': True, 'endpoint': '/stream/write', 'model': chunk.get('model'), 'cost_usd': chunk.get('cost_usd')})}\n\n"
                log_payment("/stream/write", chunk.get("cost_usd", 0.05), request.remote_addr)
            else:
                yield f"data: {json.dumps({'text': chunk['text']})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@streaming_bp.route("/stream/chat", methods=["POST"])
def stream_chat():
    """SSE streaming chat — multi-turn conversation with any model."""
    data = request.get_json() or {}
    messages = data.get("messages", [])
    system_prompt = data.get("system", "")
    model_name = _enforce_model(data.get("model", "claude-haiku"))
    if not messages:
        return jsonify({"error": "messages required", "hint": "POST {\"messages\": [{\"role\": \"user\", \"content\": \"hello\"}], \"stream\": true}"}), 400
    valid = [m for m in messages if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
    if not valid:
        return jsonify({"error": "messages must be array of {role, content} objects"}), 400

    def generate():
        for chunk in call_model_stream(
            model_name,
            valid[-20:],
            system=system_prompt or "You are a helpful AI assistant.",
            max_tokens=int(data.get("max_tokens", 2048)),
        ):
            if chunk.get("done"):
                yield f"data: {json.dumps({'done': True, 'endpoint': '/stream/chat', 'model': chunk.get('model'), 'cost_usd': chunk.get('cost_usd'), 'input_tokens': chunk.get('input_tokens'), 'output_tokens': chunk.get('output_tokens')})}\n\n"
                log_payment("/stream/chat", chunk.get("cost_usd", 0.03), request.remote_addr)
            else:
                yield f"data: {json.dumps({'text': chunk['text']})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@streaming_bp.route("/stream/analyze", methods=["POST"])
def stream_analyze():
    data = request.get_json() or {}
    content = data.get("content", "")
    model_name = _enforce_model(data.get("model", "auto"))
    if not content:
        return jsonify({"error": "content required"}), 400

    def generate():
        for chunk in call_model_stream(
            model_name,
            [{"role": "user", "content": f"Analyze:\n\n{content[:3000]}"}],
            system="You are an analyst. Provide structured analysis with key findings, sentiment, and recommendations.",
            max_tokens=800,
        ):
            if chunk.get("done"):
                yield f"data: {json.dumps({'done': True, 'endpoint': '/stream/analyze', 'model': chunk.get('model'), 'cost_usd': chunk.get('cost_usd')})}\n\n"
                log_payment("/stream/analyze", chunk.get("cost_usd", 0.02), request.remote_addr)
            else:
                yield f"data: {json.dumps({'text': chunk['text']})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
