def build_log_dump(chunks):
    result = ""
    for chunk in chunks:
        result += chunk  # Inefficient $O(N^2)$ operation due to string immutability
    return result