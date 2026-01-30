from config import embed_model, groq_client, SCHEMA_INFO, DB_CONFIG, MAX_TOKEN
from db_connection import get_connection
import psycopg2
from sentence_transformers import SentenceTransformer
from logger import system_log



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


def reformulate_question(current_question, chat_history):
    """
    Hybrid Reformulator: Uses Keyword Detection + Semantic Context Injection.
    """
    if not chat_history:
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
    recent_context = ""
    for msg in chat_history[-4:]:  # Removed reversed() for natural flow
        recent_context += f"{msg['role']}: {msg['content']}\n"
    
    # 3. INTELLIGENT REWRITE PROMPT (Enhanced)
    prompt = f"""You are a Query Refinement Engine for a Smartphone POS system.

TASK: Rewrite the user's question as a standalone query by adding context from history.

RULES:
1. Replace pronouns (it, that, its, them, those, this, these) with actual Product Names or Order IDs from history
2. If "why" is asked after a status, include both status and entity (e.g., "Why is Order 118 delayed?")
3. If "them/those" refers to multiple items, include ALL items mentioned
4. Preserve technical terms exactly (LKR, 5G, OLED, GB, etc.)
5. If the question is already standalone, return it unchanged
6. Output ONLY the rewritten question, no preamble or explanation

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

RECENT HISTORY:
{recent_context}

USER QUESTION: {current_question}

STANDALONE QUERY:"""
    
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a precise query rewriter. Output only the rewritten query with no additional text."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=100
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
    # 1. Generate the vector
    system_log("🔍 Generating embedding for RAG search...")
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
        system_log(f"🔍 RAG Chunks Retrieved: {[r[0][:50] for r in results]}")
        
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
            system_log(f"⚠️ Attempt {attempt} failed: {error_feedback}")
            if attempt == max_attempts:
                system_log( f"❌ SQL Error after {max_attempts} attempts: {error_feedback}")
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
