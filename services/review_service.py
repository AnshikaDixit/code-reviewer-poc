import os
import json
import time
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

def ask_gemini_to_review(diff_text: str, max_retries: int = 3) -> str:
    """
    Queries the Gemini model with a structured analysis prompt to parse
    vulnerabilities, logic traps, and syntax gaps from the diff snippet.
    """
    if not ai_client:
        raise ValueError("Gemini API key is not configured.")

    prompt = f"""
    You are an expert, production-grade python code reviewer. 
    Analyze the following GitHub PR diff for:
    1. Security vulnerabilities and edge cases.
    2. Performance bottlenecks or memory leaks.
    3. Code readability, maintainability, and adherence to SOLID principles.
    4. Potential logic bugs.

    Provide a thorough review. Be concise, objective, and constructive.
    Extract specific issues, including the file path and line number, and provide actionable code suggestions.

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
                    time.sleep(sleep_time)
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

            # 2. Fetch the PR diff
            diff_headers = {
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github.v3.diff"
            }
            diff_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
            diff_response = await httpx_client.get(diff_url, headers=diff_headers)
            pr_diff = diff_response.text

            # 3. Get Gemini review
            try:
                review_json_str = ask_gemini_to_review(pr_diff)
            except Exception as e:
                print(f"Could not retrieve review from Gemini. Aborting. Error: {e}")
                return

            try:
                review_data = json.loads(review_json_str)
            except json.JSONDecodeError:
                print("Failed to parse JSON from Gemini response.")
                return

            # 4. Build inline review comments
            inline_comments = []
            seen_locations = set()
            for c in review_data.get("comments", []):
                file_path = c.get("file_path")
                line_number = c.get("line_number")
                comment_text = c.get("comment", "")
                suggestion = c.get("suggestion", "")
                issue_type = c.get("issue_type", "")

                location_key = (file_path, line_number)
                if location_key in seen_locations:
                    continue
                seen_locations.add(location_key)

                body = f"**[{issue_type}]** {comment_text}"
                if suggestion:
                    body += f"\n\n**Suggestion:**\n```python\n{suggestion}\n```"

                if file_path and line_number:
                    inline_comments.append({
                        "path": file_path,
                        "line": line_number,
                        "side": "RIGHT",
                        "body": body
                    })

            # 5. Post a Pull Request Review
            summary = review_data.get("summary", "")
            review_payload = {
                "commit_id": commit_sha,
                "body": f"### Gemini AI Review Feedback\n\n**Summary:** {summary}\n\n",
                "event": "COMMENT",
                "comments": inline_comments
            }

            res = await httpx_client.post(review_url, headers=comment_headers, json=review_payload)

            # Fixed: GitHub returns 200 OK or 201 Created for a successful review submission
            if res.status_code in [200, 201]:
                print(f"Review with {len(inline_comments)} inline comments posted successfully!")
            elif res.status_code == 422 and "Line could not be resolved" in res.text:
                print("Failed to post inline comments due to unresolved lines. Falling back to general review comment...")
                fallback_body = review_payload["body"] + "\n\n### Detailed Comments\n"
                for ic in inline_comments:
                    fallback_body += f"- **{ic['path']}:{ic['line']}**: {ic['body'].replace(chr(10), ' ')}\n"
                
                review_payload["body"] = fallback_body
                review_payload["comments"] = []
                
                fallback_res = await httpx_client.post(review_url, headers=comment_headers, json=review_payload)
                if fallback_res.status_code in [200, 201]:
                    print("Fallback review posted successfully!")
                else:
                    print(f"Failed to post fallback review. Status: {fallback_res.status_code}, Response: {fallback_res.text}")
            else:
                print(f"Failed to post review. Status: {res.status_code}, Response: {res.text}")

    except Exception as e:
        print(f"Exception during PR analysis: {e}")