from config import groq_client, FAST_MODEL
from utils import system_log
from prompts import routing_prompt

def identify_intent(question):
    # 1. Manual keyword check for extreme speed
    q = question.lower().strip()
    if q in ["hi", "hello", "hey", "good morning", "good evening"]:
        return "GREETING"
    if any(word in q for word in ["help", "what can you do", "features", "how to use"]):
        return "ABOUT"
    if any(word in q for word in ["bye", "thank you", "thanks", "exit"]):
        return "CLOSURE"
    
    # 2. Use LLM-based classification for more complex queries
    filled_prompt = routing_prompt.format(question=question)
    response = groq_client.chat.completions.create(
        model=FAST_MODEL,
        messages=[{"role": "user", "content": filled_prompt}],
        temperature=0.1  
    )
    usage = response.usage
    token_metadata = {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens
    }
    system_log(f" Tokens Used intent - Prompt: {usage.prompt_tokens} | Completion: {usage.completion_tokens} | Total: {usage.total_tokens}")
    
    intent = response.choices[0].message.content.strip().upper()
    
    # Fallback validation
    valid_intents = ['SQL', 'RAG', 'BOTH']
    if intent not in valid_intents:
        for word in intent.split():
            if word in valid_intents:
                return word
        # Default fallback
        return 'SQL'
    system_log(f" Identified Intent: {intent}")
    return intent