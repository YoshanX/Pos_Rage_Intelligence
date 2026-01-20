
import os
import psycopg2
from sentence_transformers import SentenceTransformer
from groq import Groq
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Access the API key using the key name defined in the .env file
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if GROQ_API_KEY is not None:
    print(f"API Key successfully loaded. Key starts with: {GROQ_API_KEY[:5]}...")
else:
    print("API Key not found. Please check your .env file and environment setup.")



# --- 1. CONFIGURATION ---
DB_CONFIG = {
    "dbname": "Pos_dbc",
    "user": "postgres",
    "password": "1111",
    "host": "localhost",
    "port": "5432"
}



# Model for local embeddings (384 dimensions)
embed_model = SentenceTransformer('all-MiniLM-L6-v2') 
groq_client = Groq(api_key=GROQ_API_KEY)
MAX_TOKEN=200
# Complete Schema Info for SQL Insights
SCHEMA_INFO = """
The database 'Pos_dbc' has these tables:

1. product (product_id, name, category_id, brand, current_price, policy_id, embedding)
   - Sample: (1, 'iPhone 15 128GB', 1, 'Apple', 192000.00, 1, '[0.12, -0.05, ...]')
2. stock (product_id, quantity, last_updated)
   - Sample: (1, 15, '2026-01-19 10:00:00')
3. "order" (order_id, customer_id, staff_id, courier_id, total_price, order_date, status_id)
   - Sample: (118, 5, 2, 2, 385000.00, '2026-01-05', 2)
4. order_item (order_id, product_id, quantity, price_at_sale)
   - Sample: (118, 2, 1, 385000.00)
5. knowledge_base (kb_id, document_type, title, content, source, embedding)
   - Sample: (1, 'delivery_issue', 'Koombiyo Courier Delays Jan 2026', 'All orders via Koombiyo (ID 2) face delays Jan 4-8...', 'HEAD OFFICE', '[0.11, 0.04, ...]')
   - Sample: (2,'product_spec', 'iPhone 15 Specifications', 'Display: 6.1 inch Super Retina XDR OLED Chip: A16 Bionic Camera: 48MP main',  'manufacturer_website', '[0.09, -0.02, ...]')
6. courier (courier_id, service_name, contact_number)
   - Sample: (2, 'Koombiyo', '0112345678')
7. order_status (status_id, status_name)
   - Sample: (1, 'Success'), (2, 'Delayed')
8. staff (staff_id, name, role)
   - Sample: (2, 'Kasun Perera', 'Cashier')
9. customer (customer_id, name, phone, email, address)
   - Sample: (5, 'Nilanthi Silva', '0771234567', 'nilanthi@email.com', 'Colombo 03')
10. price_change_log (log_id, product_id, previous_price, new_price, change_reason, change_date)
    - Sample: (1, 31, 89980.00, 91779.60, 'Tax increase', '2026-01-07')

CRITICAL SQL RULES:
1. Always use double quotes for the "order" table.
2. To get the human-readable status, JOIN "order" with order_status ON "order".status_id = order_status.status_id.
3. If a status is 'Delayed', use the 'BOTH' path to find the 'why' in the knowledge_base.
4. Prices are in LKR. Dates are YYYY-MM-DD.
"""