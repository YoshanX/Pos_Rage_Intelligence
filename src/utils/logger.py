import time
import datetime
import os

def log_transaction(query, intent, latency, response):
    """
    Logs the user interaction and system performance to a text file.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = (
        f"{'='*50}\n"
        f"TIMESTAMP : {timestamp}\n"
        f"USER QUERY: {query}\n"
        f"INTENT    : {intent}\n"
        f"LATENCY   : {latency:.2f} seconds\n"
        f"AI OUTPUT : {response}\n"
        f"{'='*50}\n\n"
    )
    
    # Save to a local logs folder
    with open("../logs/system_performance.log", "a", encoding="utf-8") as f:
        f.write(log_entry)
    
    # Also print to terminal for real-time monitoring
    print(log_entry)




def system_log(message):
    """
    Utility function to print a message to the console 
    and append it to the audit log file.
    """
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    print(formatted_msg)
    with open("../logs/system_audit.log", "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")   