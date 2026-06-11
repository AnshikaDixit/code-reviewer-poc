import os
from fastapi import FastAPI, Request, Header
from dotenv import load_dotenv

# Load environment variables from the local .env configuration file
load_dotenv()

# Check credentials on startup
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GITHUB_TOKEN or not GEMINI_API_KEY:
    print("WARNING: GITHUB_TOKEN or GEMINI_API_KEY is missing from environment variables!")

from services.review_service import analyze_pull_request

# Initialize FastAPI application
app = FastAPI(title="Code Reviewer POC")

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
        
        print(f"Processing PR #{pr_number} on {repo_name}...")
        await analyze_pull_request(repo_name, pr_number, commit_sha)
        return {"message": "Analysis triggered successfully"}

    return {"message": f"Action '{action}' ignored"}