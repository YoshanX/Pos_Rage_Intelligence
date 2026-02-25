import redis
import json
from config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, CHAT_TTL, MAX_MESSAGE_CHARS, MAX_HISTORY_MESSAGES
from utils.logger import system_log


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
    r.ping()  
    system_log(" Redis connected successfully.")
    REDIS_AVAILABLE = True

except Exception as e:
    system_log(f" Redis connection failed: {e}. Memory will degrade to session-only.")
    r = None
    REDIS_AVAILABLE = False

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
    """Truncates content that exceeds the max character limit."""
    if len(content) > MAX_MESSAGE_CHARS:
        return content[:MAX_MESSAGE_CHARS] + "... [truncated]"
    return content

def save_message(session_id: str, role: str, content: str):
    '''Saves a message to Redis with a TTL. Falls back to in-memory store if Redis is down.'''
    message = json.dumps({"role": role, "content": _truncate(content)})
    key = f"chat:{session_id}"

    if _is_redis_up():
        try:
            pipe = r.pipeline()   
            pipe.rpush(key, message)
            pipe.ltrim(key, -MAX_HISTORY_MESSAGES, -1)  
            pipe.expire(key, CHAT_TTL)
            pipe.execute()
        except Exception as e:
            system_log(f" Redis save_message failed: {e}. Using fallback.")
            _fallback_save(session_id, message)
    else:
        _fallback_save(session_id, message)


def get_chat_history(session_id: str, window_size: int = 8) -> list:
    """Retrieves the most recent messages for a session. Uses Redis if available, otherwise falls back to in-memory store."""
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

# Fallback (in-memory) — only used when Redis is down

def _fallback_save(session_id: str, message: str):
    if session_id not in _fallback_store:
        _fallback_store[session_id] = []
    _fallback_store[session_id].append(message)
    
    if len(_fallback_store[session_id]) > MAX_HISTORY_MESSAGES:
        _fallback_store[session_id] = _fallback_store[session_id][-MAX_HISTORY_MESSAGES:]


def _fallback_get(session_id: str, window_size: int) -> list:
    messages = _fallback_store.get(session_id, [])
    recent = messages[-window_size:]
    return [json.loads(m) for m in recent]