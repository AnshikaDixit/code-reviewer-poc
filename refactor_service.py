import re

with open("services/review_service.py", "r") as f:
    content = f.read()

# 1. Add imports
imports_to_add = """from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
import sys
"""
content = content.replace("from models.schemas import CodeReviewResult, TriageResult, SummaryReviewResult", imports_to_add + "\nfrom models.schemas import CodeReviewResult, TriageResult, SummaryReviewResult")

# 2. Extract analyze_pull_request
start_idx = content.find("async def analyze_pull_request(repo_name: str, pr_number: int, commit_sha: str):")
before = content[:start_idx]

# 3. Define the new analyze_pull_request and _perform_review
new_analyze = """async def analyze_pull_request(repo_name: str, pr_number: int, commit_sha: str):
    \"\"\"Main orchestration function for evaluating pull requests based on size.\"\"\"
    try:
        await init_db()
        github_token = await get_github_installation_token(repo_name)
    except Exception as e:
        print(f"Init failed: {e}")
        return

    server_env = os.environ.copy()
    server_env["GITHUB_TOKEN"] = github_token
    server_env["SCOPED_REPO"] = repo_name

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "services.github_mcp_server"],
        env=server_env
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()
                await _perform_review(repo_name, pr_number, commit_sha, mcp_session)
    except Exception as e:
        print(f"Exception during PR analysis via MCP: {e}")

async def _perform_review(repo_name: str, pr_number: int, commit_sha: str, mcp_session: ClientSession):
"""

old_func_body = content[start_idx:]
# Find the start of the try block inside analyze_pull_request
try_block_start = old_func_body.find("    try:\n        async with httpx.AsyncClient() as httpx_client:")

if try_block_start == -1:
    print("Could not find httpx.AsyncClient try block!")
    exit(1)

# Extract everything from the httpx_client block onwards
rest_of_body = old_func_body[try_block_start:]
rest_of_body = rest_of_body.replace("    try:\n        async with httpx.AsyncClient() as httpx_client:\n", "    try:\n")

# Now we need to replace all httpx calls
rest_of_body = re.sub(
    r'existing_res = await httpx_client\.get\(review_url, headers=comment_headers\)\n\s+if existing_res\.status_code == 200:\n\s+for review in existing_res\.json\(\):',
    r'''res = await mcp_session.call_tool("get_existing_reviews", {"repo_name": repo_name, "pr_number": pr_number})
            existing_reviews = json.loads(res.content[0].text)
            for review in existing_reviews:''',
    rest_of_body
)

rest_of_body = re.sub(
    r'files_res = await httpx_client\.get\(files_url, headers=comment_headers\)\n\s+if files_res\.status_code != 200:\n\s+print\(f"Failed to fetch PR files: \{files_res\.text\}"\)\n\s+return\n\n\s+pr_files = files_res\.json\(\)',
    r'''res = await mcp_session.call_tool("get_pr_files", {"repo_name": repo_name, "pr_number": pr_number})
            pr_files = json.loads(res.content[0].text)''',
    rest_of_body
)

rest_of_body = re.sub(
    r'res = await httpx_client\.post\(review_url, headers=comment_headers, json=review_payload\)\n\n\s+if res\.status_code in \[200, 201\]:\n\s+print\(f"Review for chunk posted successfully with \{len\(inline_comments\)\} inline comments!"\)\n\s+elif res\.status_code == 422:',
    r'''try:
                    await mcp_session.call_tool("post_review_comment", {"repo_name": repo_name, "pr_number": pr_number, "payload": review_payload})
                    print(f"Review for chunk posted successfully with {len(inline_comments)} inline comments!")
                except Exception as e:
                    if "422 Unprocessable Entity" in str(e):''',
    rest_of_body
)

rest_of_body = re.sub(
    r'fallback_res = await httpx_client\.post\(review_url, headers=comment_headers, json=review_payload\)\n\s+if fallback_res\.status_code not in \[200, 201\]:\n\s+print\(f"Failed to post fallback review. Status: \{fallback_res\.status_code\}, Response: \{fallback_res\.text\}"\)\n\s+else:\n\s+print\(f"Failed to post review for chunk. Status: \{res\.status_code\}, Response: \{res\.text\}"\)',
    r'''    try:
                            await mcp_session.call_tool("post_review_comment", {"repo_name": repo_name, "pr_number": pr_number, "payload": review_payload})
                        except Exception as inner_e:
                            print(f"Failed to post fallback review: {inner_e}")
                    else:
                        print(f"Failed to post review for chunk: {e}")''',
    rest_of_body
)

rest_of_body = re.sub(
    r'await httpx_client\.post\(review_url, headers=comment_headers, json=\{\n\s+"commit_id": commit_sha,\n\s+"body": body_text,\n\s+"event": "COMMENT",\n\s+"comments": \[\]\n\s+\}\)',
    r'await mcp_session.call_tool("post_review_comment", {"repo_name": repo_name, "pr_number": pr_number, "payload": {"commit_id": commit_sha, "body": body_text, "event": "COMMENT", "comments": []}})',
    rest_of_body
)

rest_of_body = re.sub(
    r'await httpx_client\.post\(issue_comment_url, headers=comment_headers, json=\{"body": triage_msg\}\)',
    r'await mcp_session.call_tool("post_issue_comment", {"repo_name": repo_name, "pr_number": pr_number, "body": triage_msg})',
    rest_of_body
)

rest_of_body = re.sub(
    r'pr_info_res = await httpx_client\.get\(f"https://api.github.com/repos/\{repo_name\}/pulls/\{pr_number\}", headers=comment_headers\)\n\s+if pr_info_res\.status_code == 200:\n\s+current_sha = pr_info_res\.json\(\)\.get\("head", \{\}\)\.get\("sha", ""\)',
    r'''res = await mcp_session.call_tool("check_pr_sha", {"repo_name": repo_name, "pr_number": pr_number})
            current_sha = json.loads(res.content[0].text)''',
    rest_of_body
)

rest_of_body = re.sub(
    r'await httpx_client\.post\(review_url, headers=comment_headers, json=summary_payload\)',
    r'await mcp_session.call_tool("post_review_comment", {"repo_name": repo_name, "pr_number": pr_number, "payload": summary_payload})',
    rest_of_body
)


final_content = before + new_analyze + rest_of_body

with open("services/review_service.py", "w") as f:
    f.write(final_content)

print("Refactored review_service.py successfully!")
