from config import embed_model, groq_client, SCHEMA_INFO, DB_CONFIG, MAX_TOKEN
from db_connection import get_connection
import psycopg2
from sentence_transformers import SentenceTransformer



def validate_query(question, max_tokens=MAX_TOKEN):
    """
    Validates user input for length, content, and security risks.
    """
    # 1. Clean the input
    clean_question = question.strip()
    if not clean_question or len(clean_question) < 3:
        return False, "Query rejected: The input is empty or too short to process."

    # 2. Tokenize and check length (Cost & Performance Guardrail)
    tokens = embed_model.tokenizer.tokenize(clean_question)
    token_count = len(tokens)
    
    if token_count > max_tokens:
        print(f"⚠️ Guardrail Triggered: Query is {token_count} tokens (Max: {max_tokens})")
        return False, f"Your question is too long ({token_count} tokens). Please keep it under {max_tokens} tokens."
    
    # 3. Security Check (SQL Injection Guardrail)
    # Checks for forbidden administrative/destructive keywords
    forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "CREATE"]
    # Check if any forbidden word is present as a standalone word (case-insensitive)
    upper_question = clean_question.upper().split()
    for word in forbidden_keywords:
        if word in upper_question:
            print(f"🚨 Security Alert: Prohibited keyword '{word}' detected.")
            return False, "Security rejection: You are not authorized to perform data modification commands."

    return True, None


# --- 4. RAG SEARCH (Vector Search) ---
def ask_rag_ai(question):
    question_vector = embed_model.encode(question).tolist()
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Each subquery is wrapped in () to allow its own ORDER BY and LIMIT
    search_query = """
        (SELECT content FROM knowledge_base
         ORDER BY embedding <=> %s::vector LIMIT 2)
        UNION ALL
        (SELECT name || ': ' || brand FROM product
         ORDER BY embedding <=> %s::vector LIMIT 1);
    """
    
    try:
        cur.execute(search_query, (question_vector, question_vector))
        results = cur.fetchall()
        context = "\n".join([r[0] for r in results])
        
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": f"You are a strict POS assistant. ONLY use this info: {context}. "
                               "If the answer is not in the info, say you do not have that data."
                },
                {"role": "user", "content": question}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Retrieval Error: {e}"
    finally:
        cur.close()
        conn.close()

# --- 5. SQL INSIGHTS (Text-to-SQL) ---
def ask_sql_ai(question):
    # Updated Prompt: Forces the AI to use fuzzy matching (ILIKE and %)
    sql_prompt = f"""
    System: You are a Read-Only PostgreSQL generator. 
    Task: Generate a SELECT query to answer: {question}

    SCHEMA:
    {SCHEMA_INFO}

    STRICT RULES (Violating these will break the system):
    1. Respond with ONLY the raw SQL string. 
    2. NO markdown code blocks (no ```sql).
    3. NO conversational text, explanations, or introductory remarks.
    4. Use 'ILIKE' with wildcards (%) for all text searches to ensure fuzzy matching.
    Example: For 'i phone 15 128gb', use ILIKE '%iPhone%15%128GB%'
    5. ONLY 'SELECT' queries are allowed.
    6. FORBIDDEN COMMANDS: DELETE, DROP, TRUNCATE, UPDATE, INSERT, ALTER, CREATE.

    Query:
    """
    
    sql_response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": sql_prompt}]
    )
    
    # Clean the output to ensure it runs in psycopg2
    generated_sql = sql_response.choices[0].message.content.strip()
    generated_sql = generated_sql.replace("```sql", "").replace("```", "").replace("\n", " ")

    print(f"🚀 Optimized SQL: {generated_sql}")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    try:
        cur.execute(generated_sql)
        db_results = cur.fetchall()
        
        # Let Groq explain the final price to the user
        final_answer = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a helpful POS assistant."},
                {"role": "user", "content": f"User asked: {question} \n Database result: {db_results}"}
            ]
        )
        return final_answer.choices[0].message.content
    except Exception as e:
        return f"❌ SQL Error: {e}"
    finally:
        cur.close()
        conn.close()

def ask_both_ai(question):
    # Step A: Get the factual data from SQL
    # We use a simpler version of the SQL function that just returns raw data
    db_results = ask_sql_ai(question) 
    
    # Step B: Perform a Vector Search using the factual results as context
    # If the DB says "Courier 2", we search the KB for "Courier 2 delays"
    search_context = f"Database Data: {db_results}. Question: {question}"
    kb_context = ask_rag_ai(search_context)
    
    # Step C: Final Synthesis
    # Send everything to Groq to explain the "Delayed because of X" reason
    final_response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Combine the Database results with the Knowledge Base reason."},
            {"role": "user", "content": f"Results: {db_results}\nReasoning Context: {kb_context}\nQuestion: {question}"}
        ]
    )
    return final_response.choices[0].message.content
