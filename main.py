import os
from fastapi import FastAPI, Request, Header, HTTPException
import httpx
from github import Github
from google import genai
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Code Reviewer POC")

# Ensure environment variables are loaded
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GITHUB_TOKEN or not GEMINI_API_KEY:
    print("⚠️ WARNING: GITHUB_TOKEN or GEMINI_API_KEY is missing from environment variables!")

# Initialize GitHub and Gemini clients
gh = Github(GITHUB_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

@app.get("/")
def read_root():
    return {"status": "healthy", "service": "PR Reviewer Bot"}

@app.post("/webhook")
async def github_webhook(request: Request, x_github_event: str = Header(None)):
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
    # 1. Pull the cryptographic diff from GitHub's custom media headers
    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3.diff"
        }
        diff_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
        response = await client.get(diff_url, headers=headers)
        pr_diff = response.text

    # 2. Feed the cryptographic diff context straight into Gemini
    review_suggestion = ask_gemini_to_review(pr_diff)

    # 3. Post a comment inline back to the target PR file
    repo = gh.get_repo(repo_name)
    pull_request = repo.get_pull(pr_number)
    
    try:
        # Note: Change 'main.py' to match any file name that is actually modified in your test PR
        # 'position=1' means the first line inside the modified code block (the diff hunk)
        pull_request.create_review_comment(
            body=f"### 🤖 Gemini AI Review Feedback\n\n{review_suggestion}",
            commit_id=repo.get_commit(commit_sha),
            path="main.py", 
            position=1 
        )
        print("✅ Comment successfully posted to GitHub!")
    except Exception as e:
        print(f"❌ Failed to post comment: {e}")

def ask_gemini_to_review(diff_text: str) -> str:
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