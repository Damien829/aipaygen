"""
AiPayGen Message Agent — reads queued messages and acts on them.
Runs as a background daemon or via cron.
Processes: skill requests, support queries, agent-to-agent messages.
"""
import json
import time
import logging
import urllib.request
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [msg-agent] %(message)s")
log = logging.getLogger("message_agent")

BASE = "http://127.0.0.1:5001"
AGENT_ID = "aipaygen-system"
POLL_INTERVAL = 30  # seconds


def api_post(endpoint, data):
    try:
        req = urllib.request.Request(
            f"{BASE}/{endpoint}",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def api_get(endpoint):
    try:
        req = urllib.request.Request(f"{BASE}/{endpoint}", headers={"User-Agent": "AiPayGen-MsgAgent/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def process_message(msg):
    """Route a message to the appropriate handler."""
    subject = msg.get("subject", "").lower()
    body = msg.get("body", "")
    from_agent = msg.get("from_agent", "unknown")
    msg_id = msg.get("msg_id", "")

    log.info(f"Processing: [{from_agent}] {subject}")

    # Skill/tool request
    if any(kw in subject for kw in ["skill", "tool", "add", "create", "absorb"]):
        result = api_post("skills/absorb", {"text": body})
        reply = f"Skill absorption result: {json.dumps(result)[:300]}"
        api_post("agent/message/send", {
            "from_agent": AGENT_ID,
            "to_agent": from_agent,
            "subject": f"Re: {msg.get('subject', '')}",
            "body": reply,
            "thread_id": msg.get("thread_id", msg_id)
        })
        return "absorbed"

    # Question / support
    if any(kw in subject for kw in ["help", "question", "how", "support", "?"]):
        result = api_post("ask", {"question": body})
        answer = result.get("answer") or result.get("result", "I couldn't process that request.")
        api_post("agent/message/send", {
            "from_agent": AGENT_ID,
            "to_agent": from_agent,
            "subject": f"Re: {msg.get('subject', '')}",
            "body": str(answer)[:2000],
            "thread_id": msg.get("thread_id", msg_id)
        })
        return "answered"

    # Task submission
    if any(kw in subject for kw in ["task", "job", "do", "execute", "run"]):
        result = api_post("task/submit", {
            "agent_id": from_agent,
            "title": msg.get("subject", "Untitled task"),
            "description": body,
            "reward_usd": 0
        })
        return "task_created"

    # Research request
    if any(kw in subject for kw in ["research", "find", "search", "look up"]):
        result = api_post("research", {"topic": body})
        summary = result.get("summary", result.get("result", "No results found."))
        api_post("agent/message/send", {
            "from_agent": AGENT_ID,
            "to_agent": from_agent,
            "subject": f"Re: {msg.get('subject', '')}",
            "body": str(summary)[:2000],
            "thread_id": msg.get("thread_id", msg_id)
        })
        return "researched"

    # Default: use /think to figure out what to do
    result = api_post("think", {
        "problem": f"An agent sent this message. What should I do?\n\nSubject: {msg.get('subject','')}\nBody: {body[:500]}",
        "context": f"I am the AiPayGen system agent. I can: research, write, code, analyze, create skills, answer questions.",
        "max_steps": 3
    })
    answer = result.get("answer", "Message received and logged.")
    api_post("agent/message/send", {
        "from_agent": AGENT_ID,
        "to_agent": from_agent,
        "subject": f"Re: {msg.get('subject', '')}",
        "body": str(answer)[:2000],
        "thread_id": msg.get("thread_id", msg_id)
    })
    return "auto_handled"


def mark_read(msg_id):
    api_post("message/mark-read", {"agent_id": AGENT_ID, "msg_id": msg_id})


def poll_once():
    """Check inbox and process unread messages."""
    inbox = api_get(f"message/inbox/{AGENT_ID}?unread_only=1")
    messages = inbox.get("messages", [])

    if not messages:
        return 0

    processed = 0
    for msg in messages:
        try:
            action = process_message(msg)
            mark_read(msg.get("msg_id", ""))
            processed += 1
            log.info(f"  -> {action}")
        except Exception as e:
            log.error(f"  Error processing message: {e}")

    return processed


def run_daemon():
    """Run as a continuous daemon."""
    log.info(f"Message agent starting. Polling every {POLL_INTERVAL}s...")
    while True:
        try:
            count = poll_once()
            if count:
                log.info(f"Processed {count} messages")
        except Exception as e:
            log.error(f"Poll error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        count = poll_once()
        print(f"Processed {count} messages")
    else:
        run_daemon()
