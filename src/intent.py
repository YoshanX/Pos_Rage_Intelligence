from config import groq_client
from logger import system_log

def identify_intent(question):

    """
    Categorizes the user's input to decide the execution path.
    """
    # 1. Manual keyword check for extreme speed
    q = question.lower().strip()
    
    if q in ["hi", "hello", "hey", "good morning", "good evening"]:
        return "GREETING"
    
    if any(word in q for word in ["help", "what can you do", "features", "how to use"]):
        return "ABOUT"
        
    if any(word in q for word in ["bye", "thank you", "thanks", "exit"]):
        return "CLOSURE"
    # 2. Use LLM-based classification for more complex queries
    """
    Refined intent classifier using few-shot examples for Avenir IT POS.
    Routes to SQL (Data), RAG (Specs/Policy), or BOTH (Data + Reason).
    """
    
    routing_prompt = f"""You are a high-precision router for a POS AI.
    
    USER QUESTION: "{question}"

    CLASSIFICATION CATEGORIES:

    1. **SQL**: Pure data from tables (Price, Stock, Status, Sales, Dates).
       - Examples: "How much is iPhone 15?", "List orders from Jan 5", "Is order 101 success?", "How many S24 in stock?" ,"What was the previous price of the Sony WH-1000XM5"

    2. **RAG**: Descriptions, specs, or policies from the knowledge base.
       - Examples: "What are the camera specs for Pixel 8?", "What is the 14-day warranty?", "Describe the iPhone 15 features."

    3. **BOTH**: Data lookup followed by an explanation or "Why".
       - Examples: "Is order 118 delayed and why?", "What is the status of order 118 and give the reason for delay?", "How many sales today and why are they low?"

    FEW-SHOT EXAMPLES:
    - Q: "What's the price of Xiaomi 14 Ultra?" -> SQL
    - Q: "Give me the specifications for Xiaomi 14 Ultra." -> RAG
    - Q: "Why is order 118 delayed?" -> BOTH
    - Q: "Is order 55 delayed? If yes, why?" -> BOTH
    - Q: "What is the return policy for smartwatches?" -> RAG
    - Q: "How many iPhones were sold on Jan 5?" -> SQL
    - Q: "Tell me about the Koombiyo delivery issue." -> RAG

    ROUTING RULE:
    - If the user asks "WHY", "REASON", or "EXPLAIN" regarding a database status -> BOTH.
    - If they ask for "SPECS", "FEATURES", or "POLICY" -> RAG.
    - Otherwise, for counts, prices, and statuses -> SQL.

    YOUR ANSWER (Respond with ONLY one word: SQL, RAG, or BOTH):

    DECISION TREE:
    1. Does question ask "why" or "reason" or "explain"? → BOTH
    2. Does question ask for specific numbers/status/data from DB? → SQL
    3. Does question ask for descriptions/comparisons/policies? → RAG

    CRITICAL: 
    - If question mentions BOTH data retrieval AND explanation → choose BOTH
    - "Why" or "reason" questions almost always need BOTH
    - Status questions without "why" are just SQL

    YOUR ANSWER (one word only):"""

    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": routing_prompt}],
        temperature=0.1  # Lower temperature for more consistent classification
    )
    
    intent = response.choices[0].message.content.strip().upper()
    
    # Fallback validation
    valid_intents = ['SQL', 'RAG', 'BOTH']
    if intent not in valid_intents:
        # Extract first valid word found
        for word in intent.split():
            if word in valid_intents:
                return word
        # Default fallback
        return 'SQL'
    system_log(f"🛤️ Identified Intent: {intent}")
    return intent