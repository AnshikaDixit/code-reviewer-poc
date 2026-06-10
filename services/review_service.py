import os
import json
import httpx
from google import genai
from google.genai import types
from models.schemas import CodeReviewResult
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    ai_client = None

def ask_gemini_to_review(diff_text: str, max_retries: int = 3) -> str:
    """
    Queries the Gemini model with a structured analysis prompt to parse
    vulnerabilities, logic traps, and syntax gaps from the diff snippet.
    Includes a retry mechanism for transient API errors (e.g. 503, 429).
    """
    import time
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
            if "503" in err_msg or "429" in err_msg or "UNAVAILABLE" in err_msg or "ResourceExhausted" in err_msg:
                if attempt < max_retries - 1:
                    sleep_time = 2 ** attempt
                    print(f"⚠️ Gemini API busy (503/429). Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(sleep_time)
                else:
                    print(f"❌ Gemini API failed after {max_retries} attempts.")
                    raise e
            else:
                raise e

async def analyze_pull_request(repo_name: str, pr_number: int, commit_sha: str):
    """
    Orchestrates the PR analysis by checking for existing comments to prevent duplicates,
    downloading the structural diff content, querying Gemini, and publishing unique results.
    """
    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN is missing. Cannot proceed with analysis.")
        return

    # Use the issues endpoint to post a general PR comment rather than a diff-specific inline comment
    comment_url = f"https://api.github.com/repos/{repo_name}/issues/{pr_number}/comments"
    
    comment_headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        async with httpx.AsyncClient() as httpx_client:
            # 1. Fetch existing review comments on the PR to prevent duplicate entries
            existing_comments_res = await httpx_client.get(comment_url, headers=comment_headers)
            
            if existing_comments_res.status_code == 200:
                comments_list = existing_comments_res.json()
                # Check if our specific bot signature signature already exists in any comment body
                for comment in comments_list:
                    if "### 🤖 Gemini AI Review Feedback" in comment.get("body", ""):
                        print(f"⏭️ Skipping comment generation. Review comment already exists on PR #{pr_number}.")
                        return
            else:
                print(f"⚠️ Could not verify existing comments. Status: {existing_comments_res.status_code}")

            # 2. Pull the raw unified diff text using native GitHub API media headers
            diff_headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3.diff"
            }
            diff_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
            diff_response = await httpx_client.get(diff_url, headers=diff_headers)
            pr_diff = diff_response.text

            # 3. Process the cryptographic diff context using the Gemini reasoning engine
            try:
                review_json_str = ask_gemini_to_review(pr_diff)
            except Exception as e:
                print(f"❌ Could not retrieve review from Gemini. Aborting PR analysis. Error: {e}")
                return

            try:
                review_data = json.loads(review_json_str)
            except json.JSONDecodeError:
                print("❌ Failed to parse JSON from Gemini response.")
                return

            # Format the output nicely for GitHub, and include the JSON for FE
            markdown_body = "### 🤖 Gemini AI Review Feedback\n\n"
            markdown_body += f"**Summary**: {review_data.get('summary', '')}\n\n"
            
            markdown_body += "#### Detailed Comments:\n"
            for c in review_data.get('comments', []):
                markdown_body += f"- **`{c.get('file_path')}:{c.get('line_number')}`** [{c.get('issue_type')}]: {c.get('comment')}\n"
                if c.get('suggestion'):
                    markdown_body += f"  - *Suggestion*: `{c.get('suggestion')}`\n"
            
            # Embed JSON for frontend parsers inside a hidden block
            markdown_body += "\n\n<!-- FE_DATA_START\n"
            markdown_body += json.dumps(review_data, indent=2)
            markdown_body += "\nFE_DATA_END -->\n"

            # 4. Post the general comment directly to GitHub since it is confirmed unique
            comment_payload = {
                "body": markdown_body
            }
            
            res = await httpx_client.post(comment_url, headers=comment_headers, json=comment_payload)
            
            if res.status_code == 201:
                print("✅ Comment successfully posted to GitHub via REST API!")
            else:
                print(f"❌ Failed to post comment. Status: {res.status_code}, Response: {res.text}")
                
    except Exception as e:
        print(f"❌ Exception occurred during PR analysis lifecycle: {e}")
