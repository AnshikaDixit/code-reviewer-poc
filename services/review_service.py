import os
import json
import re
import time
import asyncio
import jwt  # Installed via PyJWT
import httpx
from google import genai
from google.genai import types
from models.schemas import CodeReviewResult
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
APP_ID = os.environ.get("GITHUB_APP_ID")
PRIVATE_KEY_PATH = os.environ.get("GITHUB_PRIVATE_KEY_PATH")

if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    ai_client = None

async def get_github_installation_token(repo_name: str) -> str:
    """
    Authenticates as a GitHub App using a JWT and requests a temporary
    Installation Access Token valid for 1 hour.
    """
    if not APP_ID or not PRIVATE_KEY_PATH:
        raise ValueError("GitHub App configuration missing in environment.")

    # Read the downloaded .pem file
    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    # Create a JWT token valid for 10 minutes (minus a small buffer for clock drift)
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": str(APP_ID)  # The issuer must be a string
    }
    
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")
    # If using certain older PyJWT versions, jwt.encode returns bytes
    if isinstance(jwt_token, bytes):
        jwt_token = jwt_token.decode("utf-8")
    
    jwt_headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github.v3+json"
    }

    async with httpx.AsyncClient() as client:
        # Get the installation ID for this specific repo
        inst_url = f"https://api.github.com/repos/{repo_name}/installation"
        inst_res = await client.get(inst_url, headers=jwt_headers)
        
        if inst_res.status_code != 200:
            raise Exception(f"Failed to get App installation: {inst_res.text}")
            
        installation_id = inst_res.json()["id"]

        # Request an access token for this installation ID
        token_url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        token_res = await client.post(token_url, headers=jwt_headers)
        
        if token_res.status_code != 201:
            raise Exception(f"Failed to generate access token: {token_res.text}")

        return token_res.json()["token"]

async def ask_gemini_to_review(filename: str, diff_text: str, max_retries: int = 3) -> str:
    """
    Queries the Gemini model with a structured analysis prompt to parse
    vulnerabilities, logic traps, and syntax gaps from a specific file's diff snippet.
    """
    if not ai_client:
        raise ValueError("Gemini API key is not configured.")

    full_prompt = f"""
    You are a senior staff software engineer performing a code review on a GitHub
    pull request. You are rigorous, pragmatic, and respectful. Your goal is to catch
    real problems that matter — not to nitpick or generate noise.

    ## FILE BEING REVIEWED
    Filename: `{filename}`

    ## DIFF (with absolute line numbers prepended)
    {diff_text}

    ## CONTEXT YOU WILL RECEIVE
    - PR title and description
    - The unified diff (only changed hunks). 
    - IMPORTANT: The diff has been pre-processed so that every valid line has its absolute line number prepended (e.g. `42: +    added code`). You MUST use these exact numbers for your `line` and `start_line` fields! Do not guess or count lines yourself.
    - File paths and the language of each file
    - (Optional) surrounding code context for changed regions
    - (Optional) repository conventions / linter config
    - (Optional) prior review comments, on re-reviews

    ## REVIEW PRINCIPLES
    1. ONLY comment on lines that appear in the diff (added or modified). Never
        invent line numbers or comment on unchanged code.
    2. Prefer a few high-value comments over many low-value ones. If a change is
        clean, say so and approve.
    3. Every comment must be actionable and specific: state the problem, why it
        matters, and how to fix it.
    4. Do not flag stylistic preferences already handled by linters/formatters (e.g., black/ruff)
        unless they cause real harm.
    5. When unsure, lower the confidence score rather than omitting or overstating.
    6. Never fabricate APIs, behaviors, or vulnerabilities. If you cannot verify
        something from the provided context, say so explicitly.
    7. On re-reviews, do not repeat issues already resolved or addressed.

    ## WHAT TO REVIEW (in priority order) - PYTHON & FASTAPI CONTEXT
    1. CORRECTNESS & LOGIC — Python-specific bugs, off-by-one, None-type handling, incorrect
        conditionals, broken control flow, and incorrect async/await usage in FastAPI routes.
    2. SECURITY — injection (SQL/command/XSS), hardcoded secrets, unsafe deserialization,
        path traversal, weak crypto. Ensure Pydantic is used correctly for strict input/output validation.
    3. CONCURRENCY & RESOURCE SAFETY — race conditions, deadlocks, unclosed
        resources (files, connections, sessions).
    4. ERROR HANDLING — swallowed exceptions (`except Exception: pass`), missing error paths,
        generic catches, and returning inappropriate HTTP status codes in FastAPI.
    5. PERFORMANCE — N+1 queries, redundant work in loops, unnecessary allocations,
        and critically: making synchronous blocking I/O calls inside `async def` routes.
    6. API & CONTRACT CHANGES — breaking changes to public interfaces, backward
        incompatibility, OpenAPI schema changes.
    7. MAINTAINABILITY — excessive complexity, poor naming, duplication, leaky abstractions,
        magic numbers, ignoring Python idiomatic patterns (PEP 8).
    8. TESTING — missing tests for new logic, untested edge cases, brittle tests.
    9. DOCUMENTATION — missing/wrong docs on public APIs, endpoints, or non-obvious behavior.

    ## SEVERITY DEFINITIONS
    - critical: Will cause data loss, security breach, or production outage. Must fix
        before merge.
    - high: Likely bug or vulnerability under realistic conditions. Should fix before
        merge.
    - medium: Real issue but limited blast radius, or a maintainability concern worth
        addressing.
    - low: Minor improvement; safe to merge without it.
    - info: Observation, praise, or optional suggestion.

    ## VERDICT RULES
    - REQUEST_CHANGES: any critical or high severity issue exists.
    - COMMENT: only medium/low/info issues exist.
    - APPROVE: no issues, or only info-level notes.

    ## OUTPUT CONTRACT
    Respond with ONLY a valid JSON object matching the schema below. No markdown, no
    code fences, no prose outside the JSON.

    Field rules:
    - Use null for any field that does not apply.
    - For a multi-line comment, set "start_line" to the first line and "line" to the
    last line; for a single-line comment, set "start_line" to null.
    - "side" is "RIGHT" for added/modified lines, "LEFT" for deleted lines.
    - "line"/"start_line" must reference lines that actually appear in the diff.
    - "suggestion" must be the exact replacement text for the targeted line(s) so it
    can be rendered as a GitHub suggestion block; otherwise null.
    - "category" must be one of: security | bug | performance | concurrency |
            error_handling | api_contract | maintainability | testing | documentation |
            praise.
    - "owasp" is set only for security issues, otherwise null.
    - All confidence values are floats from 0.0 to 1.0.

   Schema:
    {{
        "summary": "2-4 sentence high-level overview of the PR and the review outcome.",
        "verdict": "APPROVE | COMMENT | REQUEST_CHANGES",
        "overall_confidence": 0.0,
        "stats": {{
            "files_reviewed": 0,
            "total_issues": 0,
            "by_severity": {{ "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0 }}
        }},
        "comments": [
            {{
                "path": "services/api_service.py",
                "start_line": null,
                "line": 42,
                "side": "RIGHT",
                "severity": "high",
                "category": "performance",
                "title": "Blocking call in async route",
                "description": "Calling a synchronous function like `time.sleep()` or `requests.get()` inside an `async def` route will block the entire FastAPI event loop.",
                "suggestion": "await asyncio.sleep(1) # Or use httpx.AsyncClient()",
                "confidence": 0.9,
                "owasp": null
            }}
        ],
        "non_blocking_notes": [
            "Optional repo-wide observations not tied to a specific line."
        ]
    }}

    Before responding, ensure: every comment maps to a real diff line, "stats"
    matches the actual contents of "comments", and "verdict" follows the verdict
    rules above.
    """
    
    for attempt in range(max_retries):
        try:
            response = await ai_client.aio.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CodeReviewResult,
                    temperature=0.1,
                )
            )
            return response.text
        except Exception as e:
            err_msg = str(e)
            if any(k in err_msg for k in ["503", "429", "UNAVAILABLE", "ResourceExhausted"]):
                if attempt < max_retries - 1:
                    sleep_time = 2 ** attempt
                    print(f"Gemini API busy. Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(sleep_time)
                else:
                    print(f"Gemini API failed after {max_retries} attempts.")
                    raise e
            else:
                raise e

def get_valid_lines(patch: str) -> set:
    valid_lines = set()
    if not patch:
        return valid_lines
    lines = patch.split('\n')
    current_line = 0
    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    
    for line in lines:
        match = hunk_header_re.match(line)
        if match:
            current_line = int(match.group(1))
        elif line.startswith('+') or line.startswith(' '):
            valid_lines.add(current_line)
            current_line += 1
            
    return valid_lines

def add_line_numbers_to_patch(patch: str) -> str:
    if not patch:
        return ""
    lines = patch.split('\n')
    result = []
    current_line = 0
    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    
    for line in lines:
        match = hunk_header_re.match(line)
        if match:
            current_line = int(match.group(1))
            result.append(line)
        elif line.startswith('+') or line.startswith(' '):
            result.append(f"{current_line}: {line}")
            current_line += 1
        elif line.startswith('-'):
            result.append(f"    {line}")
        else:
            result.append(line)
            
    return '\n'.join(result)

async def analyze_pull_request(repo_name: str, pr_number: int, commit_sha: str):
    try:
        github_token = await get_github_installation_token(repo_name)
    except Exception as e:
        print(f"Authentication failed: {e}")
        return

    comment_headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }

    review_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/reviews"
    issue_comment_url = f"https://api.github.com/repos/{repo_name}/issues/{pr_number}/comments"

    try:
        async with httpx.AsyncClient() as httpx_client:
            # 1. Get already reviewed files to prevent duplicate per-file reviews
            reviewed_files = set()
            # Fetch existing reviews
            existing_res = await httpx_client.get(review_url, headers=comment_headers)
            if existing_res.status_code == 200:
                for review in existing_res.json():
                    body = review.get("body", "")
                    # Extract filename from header: ### Gemini AI Review Feedback for `filename`
                    if "### Gemini AI Review Feedback for `" in body:
                        start_idx = body.find("### Gemini AI Review Feedback for `") + len("### Gemini AI Review Feedback for `")
                        end_idx = body.find("`", start_idx)
                        if end_idx != -1:
                            reviewed_files.add(body[start_idx:end_idx])

            # 2. Fetch the PR files
            files_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/files?per_page=100"
            files_res = await httpx_client.get(files_url, headers=comment_headers)
            if files_res.status_code != 200:
                print(f"Failed to fetch PR files: {files_res.text}")
                return
            
            pr_files = files_res.json()
            
            eligible_files = []
            for file_obj in pr_files:
                filename = file_obj.get("filename", "")
                status = file_obj.get("status", "")
                patch = file_obj.get("patch", "")
                
                # Filter files aggressively
                if not patch or status in ["removed", "unchanged"]:
                    continue
                if filename.endswith((".lock", ".png", ".jpg", ".jpeg", ".svg", ".md", ".json")):
                    continue
                if filename in reviewed_files:
                    print(f"Skipping {filename}: Review already exists.")
                    continue
                    
                eligible_files.append(file_obj)

            if not eligible_files:
                print("No eligible files found to review.")
                return

            semaphore = asyncio.Semaphore(5)

            async def review_file(file_obj):
                filename = file_obj.get("filename", "")
                patch = file_obj.get("patch", "")
                numbered_patch = add_line_numbers_to_patch(patch)
                valid_lines = get_valid_lines(patch)
                async with semaphore:
                    print(f"Analyzing file: {filename}...")
                    try:
                        review_json_str = await ask_gemini_to_review(filename, numbered_patch)
                        review_data = json.loads(review_json_str)
                        return (filename, review_data, valid_lines)
                    except Exception as e:
                        print(f"Could not retrieve or parse review for {filename}. Error: {e}")
                        return (filename, None, valid_lines)

            # Run all file reviews concurrently
            results = await asyncio.gather(*[review_file(f) for f in eligible_files])

            file_summaries = []

            for filename, review_data, valid_lines in results:
                if not review_data:
                    continue
                
                # Aggregate summary for the final meta-comment
                file_summary = review_data.get("summary", "")
                if file_summary:
                    file_summaries.append(f"**{filename}**: {file_summary}")
                
                inline_comments = []
                seen_locations = set()
                
                general_body = f"### Gemini AI Review Feedback for `{filename}`\n\n**Summary:** {file_summary}\n\n"

                for c in review_data.get("comments", []):
                    # FORCE correct path, ignoring Gemini hallucinations
                    c_file_path = filename
                    line_number = c.get("line")
                    comment_text = c.get("description", "")
                    suggestion = c.get("suggestion", "")
                    issue_type = c.get("category", "issue")
                    
                    if line_number is None:
                        continue
                        
                    try:
                        line_number = int(line_number)
                    except ValueError:
                        continue

                    location_key = (c_file_path, line_number)
                    if location_key in seen_locations:
                        continue
                    seen_locations.add(location_key)

                    body = f"**[{issue_type}]** {comment_text}"
                    if suggestion:
                        body += f"\n\n**Suggestion:**\n```python\n{suggestion}\n```"

                    if line_number in valid_lines:
                        inline_comments.append({
                            "path": c_file_path,
                            "line": line_number,
                            "side": "RIGHT",
                            "body": body
                        })
                    else:
                        # Append out-of-bounds comments to general body instead of inline
                        general_body += f"\n---\n📍 **Line {line_number} (Out of Diff Context)**\n{body}\n"

                if not inline_comments and "📍" not in general_body:
                    continue

                # 5. Post a Pull Request Review for THIS specific file
                review_payload = {
                  "commit_id": commit_sha,
                  "body": general_body,
                  "event": "COMMENT",
                  "comments": inline_comments
                }

                res = await httpx_client.post(review_url, headers=comment_headers, json=review_payload)

                if res.status_code in [200, 201]:
                  print(f"Review for {filename} posted successfully with {len(inline_comments)} inline comments!")

                # 🌟 FIX: Catch any 422 validation issue (Path or Line unresolved)
                elif res.status_code == 422:
                  print(f"Failed to post inline comments for {filename} due to validation errors (e.g., path/line unresolved). Falling back to general review comment...")
    
                # We build a cleaner Markdown representation since it's going into a single text comment
                  fallback_body = review_payload["body"] + "\n### Detailed Comments\n"
                  for ic in inline_comments:
                      # Avoid flattening the text onto one line; use clean lists or blockquotes instead
                      fallback_body += f"\n---\n📍 **{ic['path']} (Line {ic['line']})**\n{ic['body']}\n"
    
                  # Re-assign the body text and wipe out the broken inline comments array
                  review_payload["body"] = fallback_body
                  review_payload["comments"] = []
    
                  fallback_res = await httpx_client.post(review_url, headers=comment_headers, json=review_payload)
                  if fallback_res.status_code in [200, 201]:
                     print(f"Fallback review for {filename} posted successfully!")
                  else:
                     print(f"Failed to post fallback review for {filename}. Status: {fallback_res.status_code}, Response: {fallback_res.text}")
                else:
                     print(f"Failed to post review for {filename}. Status: {res.status_code}, Response: {res.text}")

            # 6. Post a single high-level meta-summary comment for the whole PR
            if file_summaries:
                combined_summary = "\n\n".join(file_summaries)
                summary_payload = {
                    "commit_id": commit_sha,
                    "body": f"### Gemini AI Meta-Summary\n\n**Per-File Overview:**\n\n{combined_summary}",
                    "event": "COMMENT",
                    "comments": []
                }
                await httpx_client.post(review_url, headers=comment_headers, json=summary_payload)

    except Exception as e:
        print(f"Exception during PR analysis: {e}")