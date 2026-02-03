from config import embed_model, groq_client, SCHEMA_INFO, DB_CONFIG, MAX_TOKEN
from db_connection import get_connection
import psycopg2
from sentence_transformers import SentenceTransformer
from logger import system_log
from memory_manager import get_chat_history



def validate_query(question, max_tokens=MAX_TOKEN):
    """
    Validates user input for length, content, and security risks.
    """
    # 1. Clean the input
    clean_question = question.strip()
    if not clean_question or len(clean_question) < 1:
        return False, "Query rejected: The input is empty or too short to process."

    # 2. Tokenize and check length (Cost & Performance Guardrail)
    tokens = embed_model.tokenizer.tokenize(clean_question)
    token_count = len(tokens)
    
    if token_count > max_tokens:
        system_log(f"⚠️ Guardrail Triggered: Query is {token_count} tokens (Max: {max_tokens})")
        return False, f"Your question is too long ({token_count} tokens). Please keep it under {max_tokens} tokens."
    
    # 3. Security Check (SQL Injection Guardrail)
    # Checks for forbidden administrative/destructive keywords
    forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "CREATE"]
    # Check if any forbidden word is present as a standalone word (case-insensitive)
    upper_question = clean_question.upper().split()
    for word in forbidden_keywords:
        if word in upper_question:
            system_log(f"🚨 Security Alert: Prohibited keyword '{word}' detected.")
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
        "it", "that", "those", "them", "this", "these", 
        "the price", "its", "why", "the specs", "status",
        "how much", "when", "where", "what about", "tell me more",
        "compare", "difference", "back to", "again", "also",
        "one", "other", "another"
    ]
    
    # Use substring search instead of split for better matching
    needs_context = any(word in current_question.lower() for word in context_keywords)
    
    if not needs_context:
        system_log(f"⚡ Fast-Pass: Standalone Query detected.")
        return current_question
    
    # 2. ENTITY EXTRACTION FROM HISTORY (Fixed order - chronological)
    recent_context = "\n".join([f"{m['role']}: {m['content']}" for m in history])
    # 3. INTELLIGENT REWRITE PROMPT (Enhanced)
    
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
    {
        "role": "system", 
        "content": """You are a Query Refinement Engine for a Smartphone POS system. 
        Your goal is to rewrite the user's question as a standalone query ONLY if it is a follow-up

        CORE RULES (ALWAYS FOLLOW):
        1. Replace pronouns (it, that, its, them, those, this, these) with actual Product Names or Order IDs from history
        2. If "why" is asked after a status, include both status and entity (e.g., "Why is Order 118 delayed?")
        3. If "them/those" refers to multiple items, include ALL items mentioned
        4. Preserve technical terms exactly (LKR, 5G, OLED, GB, etc.)
        5. If the question is already standalone, return it unchanged
        6. Output ONLY the rewritten question, no preamble or explanation
        7.**TOPIC SHIFT / GLOBAL QUERIES (CRITICAL):** - If the user asks for "all models," "everything," "full list," or "inventory," this is a GLOBAL request.
   - **DO NOT** include specific product names from the history in a Global request. 
   - Incorrect: "Give all smartphone models including Pixel 7a..."
   - Correct: "List all smartphone models and their quantities."
        8.corect spelling mistakes question if any


        EXAMPLES:
        History: "iPhone 15 costs LKR 192,000"
        Question: "What about its warranty?"
        Output: What is the warranty for iPhone 15?

        History: "Order 118 is delayed"
        Question: "Why?"
        Output: Why is Order 118 delayed?

        History: "iPhone 15 and Samsung S24 available"
        Question: "Compare them"
        Output: Compare iPhone 15 and Samsung S24
        Question: "what is the pric of i phone 15"
        Output: what is the price of iPhone 15
        
        
        """
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
        
        refined_query = response.choices[0].message.content.strip()
        
        # Validation: Check if output is valid
        if not refined_query or len(refined_query) < 3:
            system_log(f"⚠️ Invalid reformulation output, using original")
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
            system_log(f"🧠 Reformulated: '{current_question}' → '{refined_query}'")
        else:
            system_log(f"🧠 No change needed (already standalone)")
        
        return refined_query
        
    except Exception as e:
        system_log(f"❌ Reformulation failed: {e}, using original question")
        return current_question



# --- 4. RAG SEARCH (Vector Search) ---
def ask_rag_ai(question):
    system_log("🔍 Generating embedding for RAG search...")
    
    # FIX 1: Extract clean search terms for keyword search
    import re
    filler_words = ['give', 'me', 'show', 'tell', 'what', 'is', 'the', 'of', 'specs', 'spec']
    search_terms = ' '.join([w for w in question.lower().split() if w not in filler_words])
    
    # FIX 2: Enhance query for better vector matching
    enhanced_query = f"{question} specifications features display camera"
    question_vector = embed_model.encode(enhanced_query).tolist()
    
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
          AND (1 - (embedding <=> %s::vector)) >= 0.7  -- Only consider high-similarity vectors
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
    WHERE v.v_score >= 0.7 OR k.k_score > 0  -- Ensure we only take high-quality hits
    ORDER BY (COALESCE(v.v_score, 0) * 0.7 + COALESCE(k.k_score, 0) * 0.3) DESC
    LIMIT 6;
    """
    
    try:
        # Pass: enhanced vector, enhanced vector, clean terms, clean terms
        cur.execute(search_query, (question_vector, question_vector, search_terms, search_terms))
        results = cur.fetchall()

        # Log the split scores for transparency
        for r in results:
            system_log(f"📊 Match: {r[0][:30]}... | Vector: {r[1]:.2f} | Keyword: {r[2]:.2f}")

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
        system_log(f"Model dimension: {len(question_vector)}")
        return response.choices[0].message.content

    except Exception as e:
        return f"❌ Retrieval Error: {e}"
    finally:
        cur.close()
        conn.close()

# --- 5. SQL INSIGHTS (Text-to-SQL) ---
def ask_sql_ai(question):
    system_log("🧠 Generating SQL query...")
    
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
            4. Dates use '::date'.
            """

            sql_response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": sql_prompt}]
            )
            system_log(f"🧠 SQL Generation Attempt {attempt}: {sql_response.choices[0].message.content.strip()}")
            generated_sql = sql_response.choices[0].message.content.strip()
            generated_sql = generated_sql.replace("```sql", "").replace("```", "").replace("\n", " ")

            try:
                cur.execute(generated_sql)
                db_results = cur.fetchall()

                final_answer = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "You are a helpful POS assistant. Use only the DB results provided."},
                        {"role": "user", "content": f"User asked: {question}\nDB results: {db_results}. Prices in LKR."}
                    ]
                )

                return final_answer.choices[0].message.content

            except Exception as e:
                error_feedback = str(e)
                system_log(f"⚠️ Attempt {attempt} failed: {error_feedback}")

        return "I couldn't process that query. Please rephrase your question or contact support."

    finally:
        cur.close()
        conn.close()


def ask_both_ai(question):
    system_log("🔄 Processing BOTH SQL and RAG...")
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
                - dont say youte getting answer from knowledge base or databse just say only answer ."

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
