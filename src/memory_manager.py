import redis
import json
from config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD

# Initialize Redis connection
r = redis.Redis(
    host=REDIS_HOST, 
    port=REDIS_PORT, 
    password=REDIS_PASSWORD, 
    decode_responses=True
)

def save_message(session_id, role, content):
    """Appends a message to the Redis list for this session."""
    message = json.dumps({"role": role, "content": content})
    r.rpush(f"chat:{session_id}", message)
    # Set expiration to 24 hours (86400 seconds)
    r.expire(f"chat:{session_id}", 86400)

def get_chat_history(session_id, window_size=5):
    """Retrieves the last N messages from Redis to feed into the reformulator."""
    # Get the last 'window_size' messages
    raw_messages = r.lrange(f"chat:{session_id}", -window_size, -1)
    return [json.loads(m) for m in raw_messages]

def clear_history(session_id):
    """Explicitly deletes the session memory."""
    r.delete(f"chat:{session_id}")