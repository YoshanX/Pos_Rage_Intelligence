from config import groq_client, FAST_MODEL
from utils import system_log
from prompts import routing_prompt

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
    Refined intent classifier using few-shot examples for 
    Routes to SQL (Data), RAG (Specs/Policy), or BOTH (Data + Reason).
    """
    filled_prompt = routing_prompt.format(question=question)
    

    response = groq_client.chat.completions.create(
        model=FAST_MODEL,
        messages=[{"role": "user", "content": filled_prompt}],
        temperature=0.1  # Lower temperature for more consistent classification
    )
    usage = response.usage
    token_metadata = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens
    }

# 3. Log it for your System Audit
    system_log(f" Tokens Used intent - Prompt: {usage.prompt_tokens} | Completion: {usage.completion_tokens} | Total: {usage.total_tokens}")
    
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
    system_log(f" Identified Intent: {intent}")
    return intent