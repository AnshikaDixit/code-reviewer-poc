import os
from fastapi import FastAPI, Request, Header, HTTPException
import httpx
from github import Github
from google import genai
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables from the local .env configuration file
load_dotenv()

# Initialize FastAPI application
app = FastAPI(title="Code Reviewer POC")

# Fetch sensitive access tokens and credentials from the environment
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GITHUB_TOKEN or not GEMINI_API_KEY:
    print("⚠️ WARNING: GITHUB_TOKEN or GEMINI_API_KEY is missing from environment variables!")

# Initialize the official GitHub and Google GenAI SDK clients
gh = Github(GITHUB_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

@app.get("/")
def read_root():
    """Health check endpoint to ensure the backend service is up and running."""
    return {"status": "healthy", "service": "PR Reviewer Bot"}

@app.post("/webhook")
async def github_webhook(request: Request, x_github_event: str = Header(None)):
    """
    Main webhook listener that intercepts incoming event payloads routed from GitHub.
    Filters traffic to execute logic exclusively on critical pull request stages.
    """
    # Only listen to events related to Pull Requests
    if x_github_event != "pull_request":
        return {"message": f"Ignored event type: {x_github_event}"}

    payload = await request.json()
    action = payload.get("action")
    
    # Analyze when a PR is freshly opened, or when new commits are pushed (synchronize)
    if action in ["opened", "synchronize"]:
        repo_name = payload["repository"]["full_name"]
        pr_number = payload["pull_request"]["number"]
        commit_sha = payload["pull_request"]["head"]["sha"]
        
        print(f"🚀 Processing PR #{pr_number} on {repo_name}...")
        await analyze_pull_request(repo_name, pr_number, commit_sha)
        return {"message": "Analysis triggered successfully"}

    return {"message": f"Action '{action}' ignored"}

async def analyze_pull_request(repo_name: str, pr_number: int, commit_sha: str):
    """
    Orchestrates the PR analysis by checking for existing comments to prevent duplicates,
    downloading the structural diff content, querying Gemini, and publishing unique results.
    """
    comment_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/comments"
    
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
            review_suggestion = ask_gemini_to_review(pr_diff)

            # 4. Post the inline comment directly to GitHub since it is confirmed unique
            comment_payload = {
                "body": f"### 🤖 Gemini AI Review Feedback\n\n{review_suggestion}",
                "commit_id": commit_sha,
                "path": "calculator.py",
                "position": 1  # Target the first modified line inside the unified diff hunk
            }
            
            res = await httpx_client.post(comment_url, headers=comment_headers, json=comment_payload)
            
            if res.status_code == 201:
                print("✅ Comment successfully posted to GitHub via REST API!")
            else:
                print(f"❌ Failed to post comment. Status: {res.status_code}, Response: {res.text}")
                
    except Exception as e:
        print(f"❌ Exception occurred during PR analysis lifecycle: {e}")

def ask_gemini_to_review(diff_text: str) -> str:
    """
    Queries the Gemini model with a structured analysis prompt to parse
    vulnerabilities, logic traps, and syntax gaps from the diff snippet.
    """
    prompt = f"""
    You are an expert code reviewer. Review the following GitHub PR diff text.
    Identify any obvious bugs, logic flaws, or performance issues.
    Keep your review incredibly concise (1-2 sentences maximum) and suggest a code fix.

    PR DIFF:
    {diff_text}
    """
    
    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text