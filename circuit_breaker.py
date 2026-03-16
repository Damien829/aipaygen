"""Circuit breaker and graceful degradation utilities for external dependencies."""
import logging
import os
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

# ── Maintenance Mode ─────────────────────────────────────────────────────────
_maintenance_mode = False
_maintenance_lock = threading.Lock()
_maintenance_retry_after = 300  # seconds


def set_maintenance_mode(enabled: bool, retry_after: int = 300):
    global _maintenance_mode, _maintenance_retry_after
    with _maintenance_lock:
        _maintenance_mode = enabled
        _maintenance_retry_after = retry_after
    logger.info("Maintenance mode %s (retry_after=%ds)", "ENABLED" if enabled else "DISABLED", retry_after)


def is_maintenance_mode() -> bool:
    return _maintenance_mode


def get_maintenance_retry_after() -> int:
    return _maintenance_retry_after


# ── Database Retry with Backoff ──────────────────────────────────────────────
_DB_RETRY_DELAYS = [0.1, 0.5, 2.0]  # seconds


def db_execute_with_retry(db_path: str, sql: str, params=(), fetch: str = "none"):
    """Execute a SQLite query with retry on lock/busy errors.

    fetch: "none" (execute only), "one" (fetchone), "all" (fetchall)
    Returns the result of the fetch, or None for "none".
    """
    last_exc = None
    for attempt, delay in enumerate(_DB_RETRY_DELAYS):
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            if fetch == "one":
                result = cursor.fetchone()
            elif fetch == "all":
                result = cursor.fetchall()
            else:
                conn.commit()
                result = None
            conn.close()
            return result
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
            last_exc = e
            err_str = str(e).lower()
            if "locked" in err_str or "busy" in err_str:
                logger.warning("DB %s locked (attempt %d/%d), retrying in %.1fs",
                               os.path.basename(db_path), attempt + 1, len(_DB_RETRY_DELAYS), delay)
                time.sleep(delay)
                continue
            # Not a lock error — don't retry
            raise
        except Exception:
            raise
    # All retries exhausted
    logger.error("DB %s locked after %d retries", os.path.basename(db_path), len(_DB_RETRY_DELAYS))
    raise last_exc


# ── AI Model Graceful Degradation ────────────────────────────────────────────
_FALLBACK_RESPONSES = {
    "summarize": "The AI summarization service is temporarily unavailable. Please try again in a few minutes.",
    "analyze": "The AI analysis service is temporarily unavailable. Please try again in a few minutes.",
    "write": "The AI writing service is temporarily unavailable. Please try again in a few minutes.",
    "code": "The AI code generation service is temporarily unavailable. Please try again in a few minutes.",
    "translate": "The AI translation service is temporarily unavailable. Please try again in a few minutes.",
    "default": "The AI service is temporarily unavailable. Please try again in a few minutes.",
}


def get_model_fallback_response(operation: str = "default") -> dict:
    """Return a graceful fallback when all AI models are unavailable."""
    msg = _FALLBACK_RESPONSES.get(operation, _FALLBACK_RESPONSES["default"])
    return {
        "text": msg,
        "model": "fallback",
        "provider": "none",
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0,
        "fallback": True,
        "error": "all_models_unavailable",
    }


def all_providers_down() -> bool:
    """Check if all AI model providers have open circuits."""
    try:
        from model_router import _circuit_state, _CIRCUIT_MAX_FAILURES
        providers = ["anthropic", "openai", "google", "deepseek", "together", "xai", "mistral"]
        down_count = 0
        for p in providers:
            state = _circuit_state.get(p)
            if state and state["failures"] >= _CIRCUIT_MAX_FAILURES and state.get("opened_at"):
                down_count += 1
        # Consider "all down" if the major providers (anthropic + openai) are both down
        anthro = _circuit_state.get("anthropic", {})
        openai = _circuit_state.get("openai", {})
        major_down = (
            anthro.get("failures", 0) >= _CIRCUIT_MAX_FAILURES
            and anthro.get("opened_at") is not None
            and openai.get("failures", 0) >= _CIRCUIT_MAX_FAILURES
            and openai.get("opened_at") is not None
        )
        return major_down
    except Exception:
        return False
