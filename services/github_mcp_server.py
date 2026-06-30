import os
import httpx
from mcp.server.fastmcp import FastMCP

# Create the server
mcp = FastMCP("GitHubReviewerTools")

# Helper to get the scoped token and validate repo
def _get_headers(repo_name: str) -> dict:
    scoped_repo = os.environ.get("SCOPED_REPO")
    token = os.environ.get("GITHUB_TOKEN")
    if not scoped_repo or not token:
        raise ValueError("MCP server missing scoped credentials in environment.")
    if repo_name != scoped_repo:
        raise PermissionError(f"Access denied: this MCP server is scoped strictly to '{scoped_repo}'. Attempted to access '{repo_name}'.")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json"
    }

@mcp.tool()
async def get_pr_files(repo_name: str, pr_number: int) -> list[dict]:
    """Fetches the files modified in a given pull request."""
    headers = _get_headers(repo_name)
    files_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/files?per_page=100"
    async with httpx.AsyncClient() as client:
        res = await client.get(files_url, headers=headers)
        if res.status_code != 200:
            raise Exception(f"Failed to fetch PR files: {res.text}")
        return res.json()

@mcp.tool()
async def get_existing_reviews(repo_name: str, pr_number: int) -> list[dict]:
    """Fetches existing review comments to help deduplicate processing."""
    headers = _get_headers(repo_name)
    review_url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/reviews"
    async with httpx.AsyncClient() as client:
        res = await client.get(review_url, headers=headers)
        if res.status_code == 200:
            return res.json()
        return []

@mcp.tool()
async def check_pr_sha(repo_name: str, pr_number: int) -> str:
    """Gets the current HEAD SHA of the PR to ensure it hasn't changed."""
    headers = _get_headers(repo_name)
    url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}"
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)
        if res.status_code == 200:
            return res.json().get("head", {}).get("sha", "")
        raise Exception(f"Failed to fetch PR info: {res.text}")

@mcp.tool()
async def post_review_comment(repo_name: str, pr_number: int, payload: dict) -> dict:
    """Posts a code review (general body and/or inline comments) to the PR."""
    headers = _get_headers(repo_name)
    url = f"https://api.github.com/repos/{repo_name}/pulls/{pr_number}/reviews"
    async with httpx.AsyncClient() as client:
        res = await client.post(url, headers=headers, json=payload)
        # 422 usually means we tried to post a comment on an invalid line, bubble it up.
        if res.status_code == 422:
            raise ValueError(f"422 Unprocessable Entity: {res.text}")
        if res.status_code not in [200, 201]:
            raise Exception(f"Failed to post review: Status {res.status_code} - {res.text}")
        return res.json()

@mcp.tool()
async def post_issue_comment(repo_name: str, pr_number: int, body: str) -> dict:
    """Posts a general issue comment to the PR."""
    headers = _get_headers(repo_name)
    url = f"https://api.github.com/repos/{repo_name}/issues/{pr_number}/comments"
    async with httpx.AsyncClient() as client:
        res = await client.post(url, headers=headers, json={"body": body})
        if res.status_code not in [200, 201]:
            raise Exception(f"Failed to post issue comment: Status {res.status_code} - {res.text}")
        return res.json()

if __name__ == "__main__":
    mcp.run()
