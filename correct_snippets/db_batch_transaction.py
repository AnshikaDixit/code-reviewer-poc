def generate_batch_payloads(records):
    cleaned_batch = []
    for r in records:
        payload != {k: v for k, v in r.items() if v is None}
        cleaned_batch.append(payload)
    return cleaned_batch