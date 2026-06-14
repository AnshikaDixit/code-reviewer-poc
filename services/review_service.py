import os
import json
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

    prompt = f"""
You are a senior software engineer and security-focused code reviewer with 15+ years of experience in production Python systems.

You are reviewing a GitHub Pull Request diff for the file `{filename}`.

## Your Reviewing Mandate
Analyze ONLY the changed lines (lines starting with `+`). Do not comment on unchanged context lines.

## Review Checklist (in order of priority)

### Critical (must flag)
- Hardcoded secrets, API keys, passwords, or tokens
- SQL/command injection vulnerabilities
- Unhandled exceptions that could crash the service
- Authentication/authorization bypasses
- Infinite loops or unbreakable recursive calls
- Data loss risks (destructive operations without validation)

### High (should flag)
- Missing input validation or sanitization
- Race conditions or thread-safety issues
- Insecure use of `eval()`, `exec()`, `pickle`, `subprocess`
- N+1 query problems or missing DB indexes
- Sensitive data exposed in logs or error messages
- Mutable default arguments in function signatures

### Medium (flag if clearly wrong)
- Broad `except Exception` or bare `except:` clauses
- Missing type hints on public functions
- Functions doing more than one thing (SRP violation)
- Magic numbers or strings without named constants
- Dead code or unreachable branches
- Shadowing built-in names (`list`, `id`, `type`, etc.)

### Low / Suggestions (only if significant)
- Naming clarity (variables, functions, classes)
- Missing or outdated docstrings on complex functions
- Opportunities to use stdlib instead of custom implementations

## Rules
- Be surgical. One comment per distinct issue — do not bundle multiple problems.
- If a line looks suspicious but you are not certain it is wrong, skip it.
- Do not praise the code. Do not say "looks good". Only report issues.
- Do not repeat the diff back to the user.
- Provide a concrete code fix for every comment you make, not just a description of the problem.
- Line numbers must correspond exactly to the `+` lines in the diff provided.
- If the file has no issues worth flagging, return an empty comments list and a one-line summary saying so.

FILE: `{filename}`

PR DIFF:
{diff_text}
"""
    
    for attempt in range(max_retries):
        try:
            response = ai_client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
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
            # 1. Check for duplicate review comments
            existing_res = await httpx_client.get(issue_comment_url, headers=comment_headers)
            if existing_res.status_code == 200:
                for comment in existing_res.json():
                    if "### Gemini AI Review Feedback" in comment.get("body", ""):
                        print(f"Skipping. Review already exists on PR #{pr_number}.")
                        return

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
                eligible_files.append(file_obj)

            if not eligible_files:
                print("No eligible files found to review.")
                return

            semaphore = asyncio.Semaphore(5)

            async def review_file(file_obj):
                filename = file_obj.get("filename", "")
                patch = file_obj.get("patch", "")
                async with semaphore:
                    print(f"Analyzing file: {filename}...")
                    try:
                        review_json_str = await ask_gemini_to_review(filename, patch)
                        review_data = json.loads(review_json_str)
                        return (filename, review_data)
                    except Exception as e:
                        print(f"Could not retrieve or parse review for {filename}. Error: {e}")
                        return (filename, None)

            # Run all file reviews concurrently
            results = await asyncio.gather(*[review_file(f) for f in eligible_files])

            inline_comments = []
            seen_locations = set()
            file_summaries = []

            for filename, review_data in results:
                if not review_data:
                    continue
                
                # Aggregate summary
                file_summary = review_data.get("summary", "")
                if file_summary:
                    file_summaries.append(f"**{filename}**: {file_summary}")
                
                # Aggregate inline comments
                for c in review_data.get("comments", []):
                    c_file_path = c.get("file_path", filename) 
                    line_number = c.get("line_number")
                    comment_text = c.get("comment", "")
                    suggestion = c.get("suggestion", "")
                    issue_type = c.get("issue_type", "")

                    location_key = (c_file_path, line_number)
                    if location_key in seen_locations:
                        continue
                    seen_locations.add(location_key)

                    body = f"**[{issue_type}]** {comment_text}"
                    if suggestion:
                        body += f"\n\n**Suggestion:**\n```python\n{suggestion}\n```"

                    if line_number:
                        inline_comments.append({
                            "path": c_file_path,
                            "line": line_number,
                            "side": "RIGHT",
                            "body": body
                        })

            # 5. Post a single Pull Request Review for all files
            combined_summary = "\n\n".join(file_summaries)
            review_payload = {
                "commit_id": commit_sha,
                "body": f"### Gemini AI Review Feedback\n\n**Per-File Summary:**\n\n{combined_summary}\n\n",
                "event": "COMMENT",
                "comments": inline_comments
            }

            res = await httpx_client.post(review_url, headers=comment_headers, json=review_payload)

            # Fixed: GitHub returns 200 OK or 201 Created for a successful review submission
            if res.status_code in [200, 201]:
                print(f"Review with {len(inline_comments)} inline comments posted successfully!")
            elif res.status_code == 422 and "Line could not be resolved" in res.text:
                print(f"Failed to post inline comments due to unresolved lines. Falling back to general review comment...")
                fallback_body = review_payload["body"] + "\n\n### Detailed Comments\n"
                for ic in inline_comments:
                    fallback_body += f"- **{ic['path']}:{ic['line']}**: {ic['body'].replace(chr(10), ' ')}\n"
                
                review_payload["body"] = fallback_body
                review_payload["comments"] = []
                
                fallback_res = await httpx_client.post(review_url, headers=comment_headers, json=review_payload)
                if fallback_res.status_code in [200, 201]:
                    print(f"Fallback review posted successfully!")
                else:
                    print(f"Failed to post fallback review. Status: {fallback_res.status_code}, Response: {fallback_res.text}")
            else:
                print(f"Failed to post review. Status: {res.status_code}, Response: {res.text}")

    except Exception as e:
        print(f"Exception during PR analysis: {e}")