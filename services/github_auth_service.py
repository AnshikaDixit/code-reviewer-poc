import os
import time
import jwt
import httpx
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.environ.get("GITHUB_APP_ID")
PRIVATE_KEY_PATH = os.environ.get("GITHUB_PRIVATE_KEY_PATH")

async def get_github_installation_token(repo_name: str) -> str:
    """Authenticates as GitHub App to get installation token."""
    if not APP_ID or not PRIVATE_KEY_PATH:
        raise ValueError("GitHub App configuration missing in environment.")

    with open(PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": str(APP_ID)
    }

    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")
    if isinstance(jwt_token, bytes):
        jwt_token = jwt_token.decode("utf-8")

    jwt_headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github.v3+json"
    }

    async with httpx.AsyncClient() as client:
        inst_url = f"https://api.github.com/repos/{repo_name}/installation"
        inst_res = await client.get(inst_url, headers=jwt_headers)

        if inst_res.status_code != 200:
            raise Exception(f"Failed to get App installation: {inst_res.text}")

        installation_id = inst_res.json()["id"]

        token_url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        token_res = await client.post(token_url, headers=jwt_headers)

        if token_res.status_code != 201:
            raise Exception(f"Failed to generate access token: {token_res.text}")

        return token_res.json()["token"]
