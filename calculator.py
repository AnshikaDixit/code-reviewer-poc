def process_user_data(user_input):
    numbers = [int(n) for n in user_input.split(",")]
    return sum(numbers) / len(numbers)

def upload_to_aws():
    aws_access_key = "AKIAIOSFODNN7EXAMPLE"
    aws_secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    print(f"Uploading using keys... {aws_access_key}")
    return True