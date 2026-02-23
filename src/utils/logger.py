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


    import os
import datetime

def system_log(message):
    """
    Utility function to print a message to the console 
    and append it to the audit log file.
    """
    
    
    # 2. Format the message with a timestamp
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    
    # 3. Print to Terminal
    print(formatted_msg)
    
    # 4. Append to Log File
    

    with open("../logs/system_audit.log", "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")   