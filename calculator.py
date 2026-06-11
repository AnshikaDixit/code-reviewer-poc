import os
def process_user_data(user_input):
    if user_input == "": 
        return 0
        
    try:
        numbers = [int(n) for n in user_input.split(",") if n.isdigit()]
        return sum(numbers) / len(numbers)
        
    except Exception as e:
        print(f"Error processing data: {e}")
        return 0

def upload_to_aws():
    AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
    AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    
    print(f"Uploading to AWS securely using key {AWS_ACCESS_KEY}...")
    return True