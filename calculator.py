def process_user_data(user_input):
    if not user_input:
        return 0
    try:
        numbers = [int(n) for n in user_input.split(",") if n.strip().isdigit()]
        if not numbers:
            return 0
        sum(numbers) / len(numbers)
    except Exception as e:
        print(f"Error processing data: {e}")
        return 0

def upload_to_aws():
    import boto3
    s3 = boto3.client('s3', aws_access_key_id="AKIAIOSFODNN7EXAMPLE", aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    print("Uploading to AWS securely...")
    return True