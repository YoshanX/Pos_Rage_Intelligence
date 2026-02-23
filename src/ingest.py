import os
import re
import psycopg2
from sentence_transformers import SentenceTransformer
from utils import get_connection
from config import DB_CONFIG, embed_model
from utils import system_log

def parse_txt_to_chunks(file_path):
    """
    Parses a text file using '________________________________________' as a delimiter
    and extracts metadata based on TYPE, TITLE, CONTENT, and SOURCE tags.
    """
    if not os.path.exists(file_path):
        system_log(f" Error: {file_path} not found.")
        return []

    with open(file_path, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    # Split records by the underscore line
    raw_chunks = re.split(r'_{10,}', raw_text)
    parsed_records = []

    for chunk in raw_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # Extraction Logic using Regex
        # 1. TYPE (Defaults to 'product_spec' if not found)
        doc_type_match = re.search(r'TYPE:\s*(.*?)(?=\s*TITLE:|\s*CONTENT:|$)', chunk, re.IGNORECASE)
        doc_type = doc_type_match.group(1).strip() if doc_type_match else "product_spec"

        # 2. TITLE (Stops before 'CONTENT:')
        title_match = re.search(r'TITLE:\s*(.*?)(?=\s*CONTENT:|$)', chunk, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "Untitled Document"

        # 3. CONTENT (Starts after 'CONTENT:' and stops before 'SOURCE:')
        content_match = re.search(r'CONTENT\s*:\s*(.*?)(?=\s*SOURCE:|$)', chunk, re.IGNORECASE | re.DOTALL)
        content = content_match.group(1).strip() if content_match else chunk

        # 4. SOURCE
        source_match = re.search(r'SOURCE:\s*(.*)', chunk, re.IGNORECASE)
        source = source_match.group(1).strip() if source_match else "Unknown"

        parsed_records.append({
            "document_type": doc_type,
            "title": title,
            "content": content,
            "source": source
        })
    
    return parsed_records

def ingest_to_knowledge_base(file_list):
    """
    Processes a list of files, generates embeddings, and inserts into Postgres.
    """
    conn = get_connection()
    cur = conn.cursor()

    for file_path in file_list:
        system_log(f" Processing: {file_path}...")
        records = parse_txt_to_chunks(file_path)

        for rec in records:
            # Generate vector for the CONTENT
            try:
                
                text_to_embed = f"{rec['title']} {rec['content']}"
                embedding = embed_model.encode(text_to_embed).tolist()
                
                cur.execute("""
                    INSERT INTO knowledge_base (document_type, title, content, source, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                """, (rec['document_type'], rec['title'], rec['content'], rec['source'], embedding))
                
                system_log(f"Ingested: {rec['title']}")
                
            except Exception as e:
                system_log(f" Error inserting '{rec['title']}': {e}")
                conn.rollback()

    conn.commit()
    cur.close()
    conn.close()
    system_log("All knowledge base files have been synchronized.")


    


