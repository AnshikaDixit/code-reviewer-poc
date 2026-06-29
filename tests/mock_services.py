import time
import json
from services.review_service import ask_ollama_to_review, ask_ollama_triage, ask_ollama_summary
from constants.messages import (
    MOCK_SENDING_TO_OLLAMA,
    MOCK_OLLAMA_SUCCESS,
    MOCK_OLLAMA_ERROR,
    MOCK_ADAPTIVE_COMPLETED,
    MOCK_ADAPTIVE_ERROR
)

async def mock_analyze_pull_request():
    """Mock function for load testing."""
    mock_files = [{
        "filename": "src/auth.py",
        "diff_text": "1: + def login(user, pw):\n2: +     return db.execute(f'SELECT * FROM users WHERE u={user} AND p={pw}')"
    }]
    
    try:
        start = time.time()
        print(MOCK_SENDING_TO_OLLAMA)
        review_json_str = await ask_ollama_to_review(mock_files, max_retries=1)
        duration = time.time() - start
        
        # Verify JSON is valid (basic parsing check)
        json.loads(review_json_str)
        print(MOCK_OLLAMA_SUCCESS.format(duration=duration))
        return True
    except Exception as e:
        print(MOCK_OLLAMA_ERROR.format(e=e))
        return False

async def mock_adaptive_analyze_pull_request(file_count: int):
    """Mock function to test adaptive logic queue times."""
    eligible_files = []
    for i in range(file_count):
        eligible_files.append({
            "filename": f"src/file_{i}.py",
            "patch": f"@@ -1,2 +1,2 @@\n- old\n+ new_code_{i}",
            "numbered_patch": f"1: + new_code_{i}",
            "valid_lines": {1},
            "local_score": 1.0
        })

    def get_dir(f):
        return f['filename'].split('/')[0]

    def chunk_files_fn(files_to_chunk):
        chunks = []
        for i in range(0, len(files_to_chunk), 3):
            chunks.append(files_to_chunk[i:i + 3])
        if len(chunks) > 1 and len(chunks[-1]) == 1:
            last = chunks.pop()
            chunks[-1].extend(last)
        return chunks

    async def review_chunk(chunk_files):
        files_data = [{"filename": f["filename"], "diff_text": f["numbered_patch"]} for f in chunk_files]
        await ask_ollama_to_review(files_data, max_retries=1)

    start = time.time()
    try:
        if file_count >= 50:
            print(f"Mock [{file_count} files]: Strategy Summary only")
            await ask_ollama_summary(eligible_files, max_retries=1)
        elif file_count >= 21:
            print(f"Mock [{file_count} files]: Strategy Triage + Chunked Review")
            await ask_ollama_triage(eligible_files, max_retries=1)
            # triage logic takes top 15
            top_files = eligible_files[:15]
            chunks = chunk_files_fn(top_files)
            for chunk in chunks:
                await review_chunk(chunk)
        elif file_count >= 6:
            print(f"Mock [{file_count} files]: Strategy Chunked Review")
            chunks = chunk_files_fn(eligible_files)
            for chunk in chunks:
                await review_chunk(chunk)
        else:
            print(f"Mock [{file_count} files]: Strategy Single Prompt")
            await review_chunk(eligible_files)
        
        duration = time.time() - start
        print(MOCK_ADAPTIVE_COMPLETED.format(file_count=file_count, duration=duration))
        return True
    except Exception as e:
        print(MOCK_ADAPTIVE_ERROR.format(file_count=file_count, e=e))
        return False
