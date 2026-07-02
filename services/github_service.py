import os
import time
import jwt
import httpx
from dotenv import load_dotenv

load_dotenv()

class GithubService:
    def __init__(self, repo_name: str):
        self.app_id = os.environ.get("GITHUB_APP_ID")
        self.private_key_path = os.environ.get("GITHUB_PRIVATE_KEY_PATH")
        self.repo_name = repo_name
        self.github_token = None

    async def get_installation_token(self) -> str:
        """Authenticates as GitHub App to get installation token."""
        if self.github_token:
            return self.github_token

        if not self.app_id or not self.private_key_path:
            raise ValueError("GitHub App configuration missing in environment.")

        with open(self.private_key_path, "r") as f:
            private_key = f.read()

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": str(self.app_id)
        }

        jwt_token = jwt.encode(payload, private_key, algorithm="RS256")
        if isinstance(jwt_token, bytes):
            jwt_token = jwt_token.decode("utf-8")

        jwt_headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json"
        }

        async with httpx.AsyncClient() as client:
            inst_url = f"https://api.github.com/repos/{self.repo_name}/installation"
            inst_res = await client.get(inst_url, headers=jwt_headers)

            if inst_res.status_code != 200:
                raise Exception(f"Failed to get App installation: {inst_res.text}")

            installation_id = inst_res.json()["id"]

            token_url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
            token_res = await client.post(token_url, headers=jwt_headers)

            if token_res.status_code != 201:
                raise Exception(f"Failed to generate access token: {token_res.text}")

            self.github_token = token_res.json()["token"]
            return self.github_token

    async def get_auth_headers(self) -> dict:
        token = await self.get_installation_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }

    async def get_existing_reviews(self, pr_number: int) -> list:
        headers = await self.get_auth_headers()
        url = f"https://api.github.com/repos/{self.repo_name}/pulls/{pr_number}/reviews"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                return res.json()
            return []

    async def get_pr_files(self, pr_number: int) -> list:
        headers = await self.get_auth_headers()
        url = f"https://api.github.com/repos/{self.repo_name}/pulls/{pr_number}/files?per_page=100"
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                return res.json()
            print(f"Failed to fetch PR files: {res.text}")
            return []

    async def post_review(self, pr_number: int, review_payload: dict) -> httpx.Response:
        headers = await self.get_auth_headers()
        url = f"https://api.github.com/repos/{self.repo_name}/pulls/{pr_number}/reviews"
        async with httpx.AsyncClient() as client:
            return await client.post(url, headers=headers, json=review_payload)
            
    async def post_issue_comment(self, pr_number: int, comment_payload: dict) -> httpx.Response:
        headers = await self.get_auth_headers()
        url = f"https://api.github.com/repos/{self.repo_name}/issues/{pr_number}/comments"
        async with httpx.AsyncClient() as client:
            return await client.post(url, headers=headers, json=comment_payload)
