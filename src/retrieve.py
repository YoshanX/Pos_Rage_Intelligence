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
    # 1. Generate the vector
    question_vector = embed_model.encode(question).tolist()
    conn = get_connection()
    cur = conn.cursor()
    print(len(question_vector))

    
    # 2. INCREASE THE LIMIT (Pull more chunks to ensure the correct one is in the net)
    search_query = """
    SELECT 
        '[' || document_type || '] ' || title || ' (Source: ' || source || '): ' || content AS context,
        1 - (embedding <=> %s::vector) AS similarity_score
    FROM knowledge_base
    ORDER BY embedding <=> %s::vector
    LIMIT 6;
"""
    
    try:
        cur.execute(search_query, (question_vector, question_vector))
        results = cur.fetchall()
        # DEBUG: See what chunks were actually found
        print(f"🔍 RAG Chunks Retrieved: {[r[0][:50] for r in results]}")
        
        # 3. Create a more "Strict" System Prompt
        context = "\n\n".join([r[0] for r in results])
        
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "You are an expert POS Assistant. Below is a list of product specifications "
                        "and policies. Find the specific product the user is asking about in the context. "
                        "If multiple products are listed, ONLY describe the one that exactly matches "
                        "the user's request. If you can't find the exact model, say so.\n\n"
                        f"CONTEXT:\n{context}"
                    )
                },
                {"role": "user", "content": f"User is asking about: {question}. Provide only relevant details dont halusinate answers  if not in context say i dont have information."}
            ]
        )
        print(f"Model dimension: {len(question_vector)}")
        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Retrieval Error: {e}"
    finally:
        cur.close()
        conn.close()

# --- 5. SQL INSIGHTS (Text-to-SQL) ---
def ask_sql_ai(question):
    # Initial setup
    attempt = 0
    max_attempts = 3
    error_feedback = ""

    conn = get_connection()
    cur = conn.cursor()
    
    while attempt < max_attempts:
        attempt += 1
        
        # 1. Generate SQL Prompt with previous error feedback if applicable
        sql_prompt = f"""
        System: You are a Read-Only PostgreSQL generator. 
        Task: Generate a SELECT query to answer: {question}
        SCHEMA: {SCHEMA_INFO}
        {f"PREVIOUS ERROR: {error_feedback}. Please fix this SQL." if error_feedback else ""}
        
        STRICT RULES:
        1. Respond with ONLY the raw SQL string. No markdown, no intro.
        2. Use 'ILIKE' with wildcards (%) for text searches.
        3. Double quote the "order" table.
        4. Dates use '::date' casting.
        Query:
        """
        
        sql_response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": sql_prompt}]
        )
        
        generated_sql = sql_response.choices[0].message.content.strip()
        generated_sql = generated_sql.replace("```sql", "").replace("```", "").replace("\n", " ")

        
        
        try:
            cur.execute(generated_sql)
            db_results = cur.fetchall()
            
            # If successful, break the loop and format the answer
            final_answer = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a helpful POS assistant. Use only the DB results provided."},
                    {"role": "user", "content": f"User asked: {question} \n DB results: {db_results}. all prices are  in LKR. If empty, say no record found."}
                ]
            )
            return final_answer.choices[0].message.content

        except Exception as e:
            error_feedback = str(e)
            print(f"⚠️ Attempt {attempt} failed: {error_feedback}")
            if attempt == max_attempts:
                print( f"❌ SQL Error after {max_attempts} attempts: {error_feedback}")
                return "I couldn't process that query. Please rephrase your question or contact support."
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
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system", 
                "content": """You are a POS assistant that combines database facts with knowledge base context.

                CRITICAL RULES (VIOLATING THESE IS A SERIOUS ERROR):
                1. ONLY state information that is explicitly present in the Database Results or Knowledge Base Context below
                2. DO NOT invent, assume, or fabricate ANY information
                3. If the context doesn't contain specific information, say "I don't have that information"
                4. NEVER make up order IDs, dates, prices, or reasons that aren't in the provided data
                5. Quote facts EXACTLY as they appear in the context
                6. If Database Results show "No data" or similar, acknowledge that clearly
                7. If sql syntax error occurred, state that "I was unable to retrieve data due to a query error."

                YOUR TASK:
                - Start with the DATABASE FACTS (numbers, status, dates)
                - Then add CONTEXT/EXPLANATION from Knowledge Base if available
                - Keep your answer concise and factual
                - Always cite which source you're using: "According to the database..." or "The knowledge base explains..."

                Remember: It's better to say "I don't know" than to guess or hallucinate."""
                            },
                            {
                                "role": "user", 
                                "content": f"""USER QUESTION: {question}

                DATABASE RESULTS:
                {db_results}

                KNOWLEDGE BASE CONTEXT:
                {kb_context}

                Provide a clear answer combining both sources. If either source is missing information, state that clearly."""
            }
        ],
        temperature=0.1,  # Very low temperature to reduce hallucination
        max_tokens=500
    )
    
    return final_response.choices[0].message.content
