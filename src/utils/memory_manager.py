import redis
import json
from config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, CHAT_TTL, MAX_MESSAGE_CHARS, MAX_HISTORY_MESSAGES
from utils.logger import system_log

# ============================================================
# IMPROVEMENT 1: Connection Pool instead of bare connection
# - Handles concurrent cashier sessions without blocking
# - Auto-reconnects if Redis drops briefly
# ============================================================
try:
    pool = redis.ConnectionPool(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        max_connections=20,        # Max simultaneous connections
        socket_connect_timeout=3,  # Fail fast if Redis is unreachable
        socket_timeout=3,
        retry_on_timeout=True
    )
    r = redis.Redis(connection_pool=pool)
    r.ping()  # Validate on startup
    system_log(" Redis connected successfully.")
    REDIS_AVAILABLE = True

except Exception as e:
    system_log(f" Redis connection failed: {e}. Memory will degrade to session-only.")
    r = None
    REDIS_AVAILABLE = False


# ============================================================
# Config
# ============================================================



# ============================================================
# IMPROVEMENT 2: Graceful degradation fallback
# If Redis is unavailable, falls back to in-memory dict
# so the app keeps running instead of crashing
# ============================================================
_fallback_store: dict = {}


def _is_redis_up() -> bool:
    """Quick health check before each operation."""
    if not REDIS_AVAILABLE or r is None:
        return False
    try:
        r.ping()
        return True
    except Exception:
        return False


def _truncate(content: str) -> str:
    """
    IMPROVEMENT 3: Message size guard.
    Prevents one large AI response from consuming entire context window.
    """
    if len(content) > MAX_MESSAGE_CHARS:
        return content[:MAX_MESSAGE_CHARS] + "... [truncated]"
    return content


# ============================================================
# Public API
# ============================================================

def save_message(session_id: str, role: str, content: str):
    """
    Appends a message to the session history.
    - Truncates oversized content
    - Caps history at MAX_HISTORY_MESSAGES to prevent memory bloat
    - Falls back to in-memory if Redis is down
    """
    message = json.dumps({"role": role, "content": _truncate(content)})
    key = f"chat:{session_id}"

    if _is_redis_up():
        try:
            pipe = r.pipeline()  # IMPROVEMENT: Use pipeline for atomic multi-step ops
            pipe.rpush(key, message)
            pipe.ltrim(key, -MAX_HISTORY_MESSAGES, -1)  # IMPROVEMENT: Cap history length
            pipe.expire(key, CHAT_TTL)
            pipe.execute()
        except Exception as e:
            system_log(f" Redis save_message failed: {e}. Using fallback.")
            _fallback_save(session_id, message)
    else:
        _fallback_save(session_id, message)


def get_chat_history(session_id: str, window_size: int = 8) -> list:
    """
    Retrieves the last N messages.
    - Default window raised to 8 (4 full exchanges) for better context
    - Falls back to in-memory if Redis is down
    """
    key = f"chat:{session_id}"

    if _is_redis_up():
        try:
            raw_messages = r.lrange(key, -window_size, -1)
            return [json.loads(m) for m in raw_messages]
        except Exception as e:
            system_log(f" Redis get_chat_history failed: {e}. Using fallback.")
            return _fallback_get(session_id, window_size)
    else:
        return _fallback_get(session_id, window_size)


def clear_history(session_id: str):
    """Deletes the session memory from Redis and fallback store."""
    key = f"chat:{session_id}"

    if _is_redis_up():
        try:
            r.delete(key)
        except Exception as e:
            system_log(f" Redis clear_history failed: {e}")

    # Always clear fallback too
    _fallback_store.pop(session_id, None)


def get_session_stats(session_id: str) -> dict:
    """
    IMPROVEMENT 4: New utility — returns session metadata.
    Useful for the Streamlit sidebar to show memory status.
    """
    key = f"chat:{session_id}"
    stats = {"total_messages": 0, "ttl_seconds": 0, "redis_active": _is_redis_up()}

    if _is_redis_up():
        try:
            stats["total_messages"] = r.llen(key)
            stats["ttl_seconds"] = r.ttl(key)
        except Exception:
            pass
    else:
        messages = _fallback_store.get(session_id, [])
        stats["total_messages"] = len(messages)

    return stats


# ============================================================
# Fallback (in-memory) — only used when Redis is down
# ============================================================

def _fallback_save(session_id: str, message: str):
    if session_id not in _fallback_store:
        _fallback_store[session_id] = []
    _fallback_store[session_id].append(message)
    # Keep same cap as Redis
    if len(_fallback_store[session_id]) > MAX_HISTORY_MESSAGES:
        _fallback_store[session_id] = _fallback_store[session_id][-MAX_HISTORY_MESSAGES:]


def _fallback_get(session_id: str, window_size: int) -> list:
    messages = _fallback_store.get(session_id, [])
    recent = messages[-window_size:]
    return [json.loads(m) for m in recent]