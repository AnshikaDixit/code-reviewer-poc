import os
from fastapi import FastAPI, Request, Header, HTTPException
import hmac
import hashlib
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables from the local .env configuration file
load_dotenv()

# Check credentials on startup
APP_ID = os.environ.get("GITHUB_APP_ID")
PRIVATE_KEY_PATH = os.environ.get("GITHUB_PRIVATE_KEY_PATH")
# GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Fixed the conditional check to use the correct variable names
# And remove GEMINI_API_KEY from this check:
if not APP_ID or not PRIVATE_KEY_PATH:
    print("WARNING: GitHub App config missing!")

from services.queue_service import start_workers, review_queue, ReviewTask

GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start workers
    concurrency = int(os.environ.get("MAX_CONCURRENT_REVIEWS", "2"))
    workers = await start_workers(concurrency=concurrency)
    yield
    # Cancel workers on shutdown
    for w in workers:
        w.cancel()

# Initialize FastAPI application
app = FastAPI(title="Code Reviewer POC", lifespan=lifespan)

async def verify_github_signature(request: Request):
    if not GITHUB_WEBHOOK_SECRET:
        print("WARNING: GITHUB_WEBHOOK_SECRET not set, bypassing signature verification.")
        return
    
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")
        
    payload = await request.body()
    expected_signature = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature")

@app.get("/")
def read_root():
    """Health check endpoint to ensure the backend service is up and running."""
    return {"status": "healthy", "service": "PR Reviewer Bot"}

from tests.test_routes import router as test_router
app.include_router(test_router)

@app.post("/webhook")
async def github_webhook(request: Request, x_github_event: str = Header(None)):
    """Main webhook listener that intercepts incoming event payloads routed from GitHub."""
    # Only listen to events related to Pull Requests
    if x_github_event != "pull_request":
        return {"message": f"Ignored event type: {x_github_event}"}

    await verify_github_signature(request)

    payload = await request.json()
    action = payload.get("action")
    
    # Analyze when a PR is freshly opened, or when new commits are pushed (synchronize)
    if action in ["opened", "synchronize"]:
        repo_name = payload["repository"]["full_name"]
        pr_number = payload["pull_request"]["number"]
        commit_sha = payload["pull_request"]["head"]["sha"]
        changed_files = payload.get("pull_request", {}).get("changed_files", 0)
        
        print(f"Enqueuing PR #{pr_number} on {repo_name} (Priority: {changed_files})...")
        task = ReviewTask(
            priority=changed_files,
            repo_name=repo_name,
            pr_number=pr_number,
            commit_sha=commit_sha
        )
        review_queue.put_nowait(task)
        return {"status": "enqueued"}

    return {"message": f"Action '{action}' ignored"}