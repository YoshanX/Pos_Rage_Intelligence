from config import embed_model, groq_client, SCHEMA_INFO, DB_CONFIG, MAX_TOKEN, FAST_MODEL, LARGE_MODEL
from utils import get_connection
import psycopg2
from sentence_transformers import SentenceTransformer
from utils import system_log
from utils import get_chat_history
from psycopg2.extras import RealDictCursor
import re
from prompts import standalone_Prompt,refine_prompt,rag_system_prompt,sql_insight_system_prompt,both_final_answer_system_prompt




def validate_query(question, max_tokens=MAX_TOKEN):
   
    # 1. Clean the input
    clean_question = question.strip()
    if not clean_question or len(clean_question) < 1:
        return False, "Query rejected: The input is empty or too short to process."

    # 2. Tokenize and check length (Cost & Performance Guardrail)
    tokens = embed_model.tokenizer.tokenize(clean_question)
    token_count = len(tokens)
    
    if token_count > max_tokens:
        system_log(f" Guardrail Triggered: Query is {token_count} tokens (Max: {max_tokens})")
        return False, f"Your question is too long ({token_count} tokens). Please keep it under {max_tokens} tokens."
    
    # 3. Security Check (SQL Injection Guardrail)
    # Checks for forbidden administrative/destructive keywords

    forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "CREATE"]
    # Check if any forbidden word is present as a standalone word (case-insensitive)
    upper_question = clean_question.upper().split()
    for word in forbidden_keywords:
        if word in upper_question:
            system_log(f" Security Alert: Prohibited keyword '{word}' detected.")
            return False, "Security rejection: You are not authorized to perform data modification commands."

    return True, None


def reformulate_question(current_question, session_id):
    """
    Hybrid Reformulator: Uses Keyword Detection + Semantic Context Injection.
    
    """
    history = get_chat_history(session_id, window_size=6)
    if not history:
        return current_question
    
    # 1. EXPANDED KEYWORD HEURISTICS (Fast Check)
    context_keywords = [
       "it", "that", "those", "them", "this", "these", "its","why", "reason", "explain", "cause", "delayed and why", "if so why"
    ]
    
    # Use substring search instead of split for better matching
    needs_context = any(word in current_question.lower() for word in context_keywords)
    
    if not needs_context:
        system_log(f" Fast-Pass: Standalone Query detected.")
        return current_question
    
    # 2. ENTITY EXTRACTION FROM HISTORY (Fixed order - chronological)
    recent_context = "\n".join([f"{m['role']}: {m['content']}" for m in history])
    # 3. INTELLIGENT REWRITE PROMPT (Enhanced)
    
    
    try:
        response = groq_client.chat.completions.create(
            model=LARGE_MODEL,
            messages=[ 
    {
        "role": "system", 
        "content": standalone_Prompt
            },
            {
                "role": "user", 
                "content": f"""RECENT HISTORY:
        {recent_context}

        USER QUESTION: {current_question}

        STANDALONE QUERY:"""
            }
        ],
            temperature=0
        )
        usage = response.usage
        token_metadata = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens
        }

        # 3. Log it for your System Audit
        system_log(f" Tokens Used reformulate_question - Prompt: {usage.prompt_tokens} | Completion: {usage.completion_tokens} | Total: {usage.total_tokens}")
        
        refined_query = response.choices[0].message.content.strip()
        
        # Validation: Check if output is valid
        if not refined_query or len(refined_query) < 3:
            system_log(f" Invalid reformulation output, using original")
            return current_question
        
        # Remove common LLM preambles if present
        preamble_phrases = ["here's the", "the rewritten", "standalone query:", "output:"]
        refined_lower = refined_query.lower()
        for phrase in preamble_phrases:
            if phrase in refined_lower:
                # Extract actual query after preamble
                parts = refined_query.split(':', 1)
                if len(parts) > 1:
                    refined_query = parts[1].strip()
                break
        
        # Log the transformation
        if refined_query != current_question:
            system_log(f" Reformulated: '{current_question}' → '{refined_query}'")
        else:
            system_log(f" No change needed (already standalone)")
        
        return refined_query
        
    except Exception as e:
        system_log(f" Reformulation failed: {e}, using original question")
        return current_question



# --- 4. RAG SEARCH (Vector Search) ---
def ask_rag_ai(question):
    system_log(" Generating embedding for RAG search...")
    #question='What is the reason for Koombiyo courier service delays?'

   
    # FIX 1: Extract clean search terms for keyword search
    
    filler_words = ['give', 'me', 'show', 'tell', 'what', 'is', 'the', 'of', 'specs', 'spec']
    search_terms = ' '.join([w for w in question.lower().split() if w not in filler_words])
    
    # FIX 2: Enhance query for better vector matching
    
    question_vector = embed_model.encode(question).tolist()
    
    conn = get_connection()
    cur = conn.cursor()
    
    # FIX 3: Simplified query - rely more on vector search
    search_query = """
    WITH vector_matches AS (
        SELECT 
            kb_id, 
            1 - (embedding <=> %s::vector) AS v_score
        FROM knowledge_base
        WHERE embedding IS NOT NULL 
          AND (1 - (embedding <=> %s::vector)) >= 0.5  -- Only consider high-similarity vectors
        ORDER BY v_score DESC
        LIMIT 20
    ),
    keyword_matches AS (
        SELECT 
            kb_id, 
            ts_rank_cd(to_tsvector('simple', title || ' ' || content), 
                      plainto_tsquery('simple', %s)) AS k_score
        FROM knowledge_base
        WHERE to_tsvector('simple', title || ' ' || content) @@ plainto_tsquery('simple', %s)
        LIMIT 20
    )
    SELECT 
        '[' || document_type || '] ' || title || ': ' || content AS context,
        COALESCE(v.v_score, 0) AS vector_score,
        COALESCE(k.k_score, 0) AS keyword_score
    FROM knowledge_base kb
    LEFT JOIN vector_matches v ON kb.kb_id = v.kb_id
    LEFT JOIN keyword_matches k ON kb.kb_id = k.kb_id
    WHERE v.v_score >= 0.5 OR k.k_score > 0  -- Ensure we only take high-quality hits
    ORDER BY (COALESCE(v.v_score, 0) * 0.7 + COALESCE(k.k_score, 0) * 0.3) DESC
    LIMIT 6;
    """
    
    try:
        # Pass: enhanced vector, enhanced vector, clean terms, clean terms
        cur.execute(search_query, (question_vector, question_vector, search_terms, search_terms))
        results = cur.fetchall()
        system_log(f" Database returned {len(results)} results")
    
        if not results:
            system_log(" NO RESULTS from vector+keyword search!")
            cur.execute("""
                SELECT '[' || document_type || '] ' || title || E'\n' || content AS context, 0 AS v, 0 AS k
                FROM knowledge_base
                WHERE to_tsvector('simple', title || ' ' || content) @@ plainto_tsquery('simple', %s)
                LIMIT 4;
            """, (search_terms,))
            system_log(f"   Search terms: '{search_terms}'")
            system_log(f"   Enhanced query: '{question_vector[:50]}'")
            return "I couldn't find relevant information..."

        # Log the split scores for transparency
        for r in results:
            system_log(f" Match: {r[0][:30]}... | Vector: {r[1]:.2f} | Keyword: {r[2]:.2f}")

        context = "\n\n".join([r[0] for r in results])
        system_log(f"context {context}")
        response = groq_client.chat.completions.create(
            model=LARGE_MODEL,
            messages=[
                {
                    "role": "system", 
                    "content": rag_system_prompt.format(context=context)
                },
                {"role": "user", "content": f"User is asking about: {question}. Provide only relevant details dont halusinate answers  if not in context say i dont have information."}
            ]
        )

        usage = response.usage
        token_metadata = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens
        }

        # 3. Log it for your System Audit
        system_log(f" Tokens Used ask_rag_ai - Prompt: {usage.prompt_tokens} | Completion: {usage.completion_tokens} | Total: {usage.total_tokens}")
        system_log(f"Model dimension: {len(question_vector)}")
        return response.choices[0].message.content

    except Exception as e:
        return f" Retrieval Error: {e}"
    finally:
        cur.close()
        conn.close()

# --- 5. SQL INSIGHTS (Text-to-SQL) ---
def ask_sql_ai(question):
    system_log(" Generating SQL query...")
    
    attempt = 0
    max_attempts = 3
    error_feedback = ""

    conn = get_connection()
    cur = conn.cursor()

    try:
        while attempt < max_attempts:
            attempt += 1

            sql_prompt = f"""
            System: You are a Read-Only PostgreSQL generator. 
            Task: Generate a SELECT query to answer: {question}
            SCHEMA: {SCHEMA_INFO}
            {f"PREVIOUS ERROR: {error_feedback}. Please fix this SQL." if error_feedback else ""}
            
            STRICT RULES:
            1. Respond with ONLY the raw SQL string.
            2. Use ILIKE with %.
            3. Double quote the "order" table.
            4.Date format in 'YYYY-MM-DD' and use single quotes for dates and strings.
                EXAMPLES:
                User: "Show me all orders from January 3rd 2026"
                SQL: SELECT * FROM "order" WHERE order_date::date = '2026-01-03';


             
                            
            """
            if error_feedback:
                sql_prompt += f"""
                 PREVIOUS ATTEMPT FAILED:
                - FAILED SQL: {generated_sql}
                - ERROR RECEIVED: {error_feedback}
                INSTRUCTIONS: Analyze the error and generate a different, corrected SQL query. 
                Check your JOIN logic and table names carefully.
                """

            sql_response = groq_client.chat.completions.create(
                model=LARGE_MODEL,
                messages=[{"role": "user", "content": sql_prompt}]
            )
            usage = sql_response.usage
            token_metadata = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens
            }

        # 3. Log it for your System Audit
            system_log(f" Tokens Used sql_response - Prompt: {usage.prompt_tokens} | Completion: {usage.completion_tokens} | Total: {usage.total_tokens}")
            system_log(f" SQL Generation Attempt {attempt}: {sql_response.choices[0].message.content.strip()}")
            generated_sql = sql_response.choices[0].message.content.strip()
            generated_sql = (generated_sql
                .replace("```sql", "")
                .replace("```", "")
                .replace(";--", "")  
                .strip()
                .split(';')[0])

            try:
                cur.execute(generated_sql)
                db_results = cur.fetchall()
                system_log(f" generated SQL executed successfully: {generated_sql}")
                system_log(f" db_results: {db_results}")

                final_answer = groq_client.chat.completions.create(
                    model=LARGE_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": sql_insight_system_prompt},
                        {"role": "user", "content": f"User asked: {question}\nDB results: {db_results}. ."}
                    ]
                )
                usage = final_answer.usage
                token_metadata = {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens
                }

            # 3. Log it for your System Audit
                system_log(f" Tokens Used sql final_answer - Prompt: {usage.prompt_tokens} | Completion: {usage.completion_tokens} | Total: {usage.total_tokens}")

                return final_answer.choices[0].message.content

            except Exception as e:
                error_feedback = str(e)
                system_log(f" Attempt {attempt} failed: {error_feedback}")

        return "I couldn't process that . Try Again or Please rephrase your question or contact support."

    finally:
        cur.close()
        conn.close()



def get_raw_ai(question):
    system_log(" Generating Raw query...")
    
    attempt = 0
    max_attempts = 3
    error_feedback = ""

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        while attempt < max_attempts:
            attempt += 1

            sql_prompt = f"""
            System: You are a Read-Only PostgreSQL generator. 
            Task: Generate a SELECT query to answer: {question}
            SCHEMA: {SCHEMA_INFO}
            {f"PREVIOUS ERROR: {error_feedback}. Please fix this SQL." if error_feedback else ""}
            
            STRICT RULES:
            1. Respond with ONLY the raw SQL string.
            2. Use ILIKE with %.
            3. Double quote the "order" table.
            4.Date format in 'YYYY-MM-DD' and use single quotes for dates and strings.
                EXAMPLES:
                User: "Show me all orders from January 3rd 2026"
                SQL: SELECT * FROM "order" WHERE order_date::date = '2026-01-03';

            5. if ask delay reson retrieve staff name, curier name and order status from db and give answer
                User: "Why is order 118 delayed?"
             
                            
            """
            if error_feedback:
                sql_prompt += f"""
                 PREVIOUS ATTEMPT FAILED:
                - FAILED SQL: {generated_sql}
                - ERROR RECEIVED: {error_feedback}
                INSTRUCTIONS: Analyze the error and generate a different, corrected SQL query. 
                Check your JOIN logic and table names carefully.
                """

            sql_response = groq_client.chat.completions.create(
                model=LARGE_MODEL,
                messages=[{"role": "user", "content": sql_prompt}]
            )
            usage = sql_response.usage
            token_metadata = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens
            }

        # 3. Log it for your System Audit
            system_log(f" Tokens Used sql_response - Prompt: {usage.prompt_tokens} | Completion: {usage.completion_tokens} | Total: {usage.total_tokens}")
            system_log(f" SQL Generation Attempt {attempt}: {sql_response.choices[0].message.content.strip()}")
            generated_sql = sql_response.choices[0].message.content.strip()
            generated_sql = (generated_sql
                .replace("```sql", "")
                .replace("```", "")
                .replace(";--", "")  # Remove comment attempts
                .strip()
                .split(';')[0])

            try:
                cur.execute(generated_sql)
                db_results = cur.fetchall()
                system_log(f" generated SQL executed successfully: {generated_sql}")
                system_log(f" db_results: {db_results}")
                conn.commit()

                return db_results

            except Exception as e:
                conn.rollback()
                error_feedback = str(e)
                system_log(f" Attempt {attempt} failed: {error_feedback}")

        return "I couldn't process that database request."

    finally:
        cur.close()
        conn.close()


def ask_both_ai(question):
    system_log(" Processing BOTH SQL and RAG...")
    # Step A: Get the factual data from SQL
    # We use a simpler version of the SQL function that just returns raw data
    db_results = get_raw_ai(question) 
    
    

    # Use a fast model for this intermediate step
    refine_response = groq_client.chat.completions.create(
        model=FAST_MODEL,
        messages=[{"role": "user", "content": refine_prompt}],
        temperature=0
    )
    optimized_query = refine_response.choices[0].message.content.strip()
    system_log(f" Optimized RAG Query: {optimized_query}")

    kb_context = ask_rag_ai(optimized_query)
    #kb_context = ask_rag_ai(question)
    system_log(f" RAG Context Retrieved: {kb_context[:200]}...")  # Log the first 200 chars of context
    
    # Step C: Final Synthesis
    # Send everything to Groq to explain the "Delayed because of X" reason
    final_response = groq_client.chat.completions.create(
    model=LARGE_MODEL,
    messages=[
        {
            "role": "system",
            "content": both_final_answer_system_prompt
                    },
                    {
                        "role": "user",
                        "content": f"""Question: {question}

            Data: {db_results}

            Context: {kb_context}

            Answer:"""
                }
        ],
        temperature=0.1,  # Very low temperature to reduce hallucination
        max_tokens=500
    )
    usage = final_response.usage
    token_metadata = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens
    }

# 3. Log it for your System Audit
    system_log(f" Tokens Used both answer - Prompt: {usage.prompt_tokens} | Completion: {usage.completion_tokens} | Total: {usage.total_tokens}")
    
    return final_response.choices[0].message.content



def handle_small_talk(intent, user_name="YoshanX"):
    """
    Returns pre-defined responses for greetings and help.
    """
    responses = {
        "GREETING": f"👋 Hello {user_name}! I'm your POS Intelligent Assistant. How can I help you with inventory or orders today?",
        
        "ABOUT": (
            "🤖 **What I can do for you:**\n"
            "* **Check Stock:** Ask about quantities of models like 'S24 Ultra' or 'iPhone 15'.\n"
            "* **Order Status:** Check if an order (e.g., 'Order 118') is delayed.\n"
            "* **Technical Specs:** Ask about camera, battery, or display details.\n"
            "* **Logistics Info:** Find out why couriers like 'Koombiyo' face delays."
        ),
        
        "CLOSURE": "🙏 You're very welcome! If you need more help with the POS system later, just ask. Have a great day!"
    }
    
    return responses.get(intent, "I'm here to help! Could you please clarify your request?")
