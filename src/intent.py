from config import groq_client

def identify_intent(question):
    """
    Enhanced intent classification with explicit examples and rules
    Returns: 'SQL', 'RAG', or 'BOTH'
    """
    
    routing_prompt = f"""You are a query intent classifier for a smartphone POS system.

USER QUESTION: "{question}"

TASK: Classify into exactly ONE category. Respond with ONLY: SQL, RAG, or BOTH

CLASSIFICATION RULES:

**SQL** - Questions needing ONLY database facts/numbers:
- Keywords: "what is", "show me", "how many", "list", "get", "find"
- Examples:
  ✓ "What is the price of iPhone 15?"
  ✓ "How many products in stock?"
  ✓ "Show order 118 status"
  ✓ "List all delayed orders"
  ✓ "What is the status_id of order 118?"

**BOTH** - Questions needing database facts AND explanations/reasons:
- Keywords: "why", "reason", "explain", "because", "how come", "what caused"
- Pattern: "Get X and explain/why"
- Examples:
  ✓ "What is order 118 status and why is it delayed?"
  ✓ "Show delayed orders and explain why"
  ✓ "Why did sales drop last week?" (needs sales numbers + context)
  ✓ "Is order 118 delayed and if so why?"
  ✓ "What's the delay reason for order 118?" (needs DB + knowledge)

**RAG** - Questions needing ONLY descriptions/policies/general knowledge:
- Keywords: "describe", "compare", "recommend", "policy", "what are the features"
- Examples:
  ✓ "What are the features of iPhone 15?"
  ✓ "Compare iPhone vs Samsung"
  ✓ "What is the warranty policy?"
  ✓ "Recommend a phone under LKR 50,000"
  ✓ "How do I handle customer complaints?"

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
        model="llama-3.3-70b-versatile",
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
    
    return intent