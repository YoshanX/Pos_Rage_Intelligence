
import os
import psycopg2
from sentence_transformers import SentenceTransformer
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if GROQ_API_KEY is not None:
    print(f"API Key successfully loaded. Key starts with: {GROQ_API_KEY[:5]}...")
else:
    print("API Key not found. Please check your .env file and environment setup.")

# Roles-based Model Mapping
LARGE_MODEL = "llama-3.3-70b-versatile"  # High-reasoning (SQL, Synthesis)
FAST_MODEL = "llama-3.1-8b-instant"     # Low-latency (Intent, Refinement)    

REDIS_HOST='localhost'
REDIS_PORT=6379
REDIS_PASSWORD=None

CHAT_TTL = 86400          # 24 hours session expiry
MAX_MESSAGE_CHARS = 1500  # Truncate long AI responses before storing
MAX_HISTORY_MESSAGES = 20 # Hard cap on stored messages per session

# --- 1. CONFIGURATION ---
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"), 
    "host": os.getenv("DB_HOST"),
    "port": "5432"
}

# Model for local embeddings (384 dimensions)
embed_model = SentenceTransformer('all-MiniLM-L6-v2') 
groq_client = Groq(api_key=GROQ_API_KEY)

MAX_TOKEN=1000
# Complete Schema Info for SQL Insights
SCHEMA_INFO = """
Tables: product(product_id, name, brand, current_price, category_id, policy_id), stock(product_id, quantity,last_updated), "order"(order_id, customer_id, status_id, total_price, order_date, courier_id,staff_id), order_item(order_id, product_id, quantity, price_at_sale), order_status(status_id, status_name), customer(customer_id, name, phone,address), price_change_log(log_id, product_id, previous_price, new_price, change_reason ,change_date), category(category_id, name,description), warranty_policy(policy_id, policy_name, return_days), courier(courier_id, service_name), staff(staff_id, name, role)

Key Rules:
- Quote "order" table: SELECT * FROM "order"
- Use ILIKE for product search: name ILIKE '%term%'
- Status: JOIN order_status for readable names
- Prices in LKR
-
"""