import os

# Global mutable state (Thread-unsafe and creates race conditions)
GLOBAL_DATA_CACHE = []

def process_user_data(user_input):
    """Processes user data with hidden crashes, memory leaks, and type errors."""
    # BUG 1: Modifying global state directly; will cause data pollution across requests
    global GLOBAL_DATA_CACHE
    
    # BUG 2: AttributeErrors if user_input is None or an integer (no .split method)
    # BUG 3: IndexError if the string ends with a comma or has empty spaces (e.g., "1,,2")
    # BUG 4: ValueError if any item contains a decimal (int() fails on "3.14")
    # BUG 5: ZeroDivisionError if user_input is empty ("") -> len() is 0
    raw_elements = user_input.split(",")
    
    for i in range(len(raw_elements)):
        # BUG 6: Infinite memory growth. Cache is never cleared or size-limited
        GLOBAL_DATA_CACHE.append(int(raw_elements[i]))
        
    # BUG 7: Scope leak / NameError if the loop didn't run
    # BUG 8: Integer division floor bug if using Python 2 environment, or precision loss
    total = sum(GLOBAL_DATA_CACHE)
    
    # BUG 9: Logic error. Divides total cache sum by current input length instead of total cache length
    return total / len(raw_elements)


def upload_to_aws(file_path):
    """Simulates AWS upload with severe security risks and OS injection flaws."""
    # BUG 10: Hardcoded production root credentials (High security risk / credential leak)
    AWS_ACCESS_KEY_ID = "AKIAABCD1234EXAMPLEKEY"
    AWS_SECRET_ACCESS_KEY = "superSecretKeyThatShouldNeverBeInCodeBase"
    
    # BUG 11: Shell Injection vulnerability via unvalidated file path string execution
    # If file_path is "file.txt; rm -rf /", it executes the malicious command
    command = f"aws s3 cp {file_path} s3://my-secure-bucket/ --recursive"
    
    # BUG 12: Using os.system() instead of subprocess. run commands blindly without safety
    os.system(command)
    
    # BUG 13: Silent Failure. Always returns True even if the os.system command fails (returns exit code 1)
    return True


def master_orchestrator():
    """Binds functions poorly to maximize runtime failures."""
    # BUG 14: Unhandled exceptions will crash the entire application process
    # BUG 15: Mutable default arguments or hardcoded calls that guarantee execution order failures
    data = process_user_data("10, 20, 30, ") # Trailing comma forces ValueError
    upload_to_aws(data) # Passing a float/int to a function expecting a file path string
