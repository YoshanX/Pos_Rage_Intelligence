import psycopg2
from config import DB_CONFIG
from utils.logger import system_log

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def setup_database():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            kb_id SERIAL PRIMARY KEY,
            content TEXT NOT NULL,
            embedding vector(384)
        );
    """)
    
    conn.commit()
    cur.close()
    conn.close()
    system_log(" Database prepared.")