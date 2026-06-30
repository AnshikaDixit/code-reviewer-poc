import os
import json
import re
import time
import asyncio
import jwt  # Installed via PyJWT
import jwt
import httpx
import urllib.parse
from pydantic import ValidationError
import asyncpg
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
import sys

from models.schemas import CodeReviewResult, TriageResult, SummaryReviewResult
from dotenv import load_dotenv
from constants.prompts import REVIEW_PROMPT_TEMPLATE, TRIAGE_PROMPT_TEMPLATE, SUMMARY_PROMPT_TEMPLATE

load_dotenv()

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

APP_ID = os.environ.get("GITHUB_APP_ID")
PRIVATE_KEY_PATH = os.environ.get("GITHUB_PRIVATE_KEY_PATH")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")

async def init_db():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS review_state (
                id SERIAL PRIMARY KEY,
                repo_name VARCHAR(255) NOT NULL,
                pr_number INT NOT NULL,
                commit_sha VARCHAR(255) NOT NULL,
                filename TEXT NOT NULL,
                UNIQUE(repo_name, pr_number, commit_sha, filename)
            )
        ''')
        await conn.close()
    except Exception as e:
        print(f"Failed to init DB: {e}")



async def _call_ollama(prompt: str, max_retries: int = 3) -> str:
    """Core function to send an HTTP POST request to the local Ollama instance."""
    url = "http://localhost:11434/api/chat"
    
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 8192,
        }
    }

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                return data["message"]["content"]
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if attempt < max_retries - 1:
                sleep_time = 2 ** attempt
                print(f"Ollama connection error. Retrying in {sleep_time}s... (Attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(sleep_time)
            else:
                raise RuntimeError(f"Ollama unreachable after {max_retries} attempts: {e}")
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                raise e


def _extract_json(text: str) -> str:
    """Extracts JSON object from model output using brace counting."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)

    start = text.find("{")
    if start == -1:
        return text

    brace_count = 0
    end = start
    for i, char in enumerate(text[start:], start=start):
        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
        
        if brace_count == 0:
            end = i
            break

    if end > start:
        return text[start:end + 1]

    return text


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


async def ask_ollama_to_review(files_data: list[dict], max_retries: int = 3) -> str:
    """Queries local Ollama to review parsed code vulnerabilities."""
    diff_context = ""
    for fd in files_data:
        diff_context += f"\n\n### Filename: `{fd['filename']}`\n{fd['diff_text']}"

    full_prompt = REVIEW_PROMPT_TEMPLATE.format(diff_context=diff_context)
    raw = await _call_ollama(full_prompt, max_retries)
    return _extract_json(raw)


async def ask_ollama_triage(files_metadata: list[dict], max_retries: int = 3) -> str:
    """Asks Ollama to re-rank and flag risky files heuristically."""
    context_str = ""
    for f in files_metadata:
        context_str += f"- `{f['filename']}` | Added: {f.get('additions', 0)} | Deleted: {f.get('deletions', 0)} | Local Score: {f.get('local_score', 0)}\n"

    full_prompt = TRIAGE_PROMPT_TEMPLATE.format(context_str=context_str)
    raw = await _call_ollama(full_prompt, max_retries)
    return _extract_json(raw)


async def ask_ollama_summary(files_metadata: list[dict], max_retries: int = 3) -> str:
    """Provides a high-level module risk summary for large PRs (50+ files)."""
    context_str = ""
    for f in files_metadata:
        context_str += f"- `{f['filename']}` | Added: {f.get('additions', 0)} | Local Score: {f.get('local_score', 0)}\n"

    full_prompt = SUMMARY_PROMPT_TEMPLATE.format(context_str=context_str)
    raw = await _call_ollama(full_prompt, max_retries)
    return _extract_json(raw)


def get_valid_lines(patch: str) -> set:
    valid_lines = set()
    if not patch:
        return valid_lines
    lines = patch.split('\n')
    current_line = 0
    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for line in lines:
        match = hunk_header_re.match(line)
        if match:
            current_line = int(match.group(1))
        elif line.startswith('+') or line.startswith(' '):
            valid_lines.add(current_line)
            current_line += 1

    return valid_lines


def add_line_numbers_to_patch(patch: str) -> str:
    if not patch:
        return ""
    lines = patch.split('\n')
    result = []
    current_line = 0
    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for line in lines:
        match = hunk_header_re.match(line)
        if match:
            current_line = int(match.group(1))
            result.append(line)
        elif line.startswith('+') or line.startswith(' '):
            result.append(f"{current_line}: {line}")
            current_line += 1
        elif line.startswith('-'):
            result.append(f"    {line}")
        else:
            result.append(line)

    return '\n'.join(result)


def calculate_local_risk_score(filename: str, patch: str) -> float:
    if any(x in filename.lower() for x in ['generated', 'migrations/', 'alembic/versions/', 'package-lock.json', 'yarn.lock']):
        return 0.0

    base_score = 1.0
    if patch:
        base_score += sum(1 for line in patch.split('\n') if line.startswith('+') and not line.startswith('+++'))

    if any(x in filename.lower() for x in ['auth/', 'payment/', 'crypto/', 'security/']):
        base_score *= 3.0

    if any(x in filename.lower() for x in ['test', 'tests/', 'spec.py']):
        base_score *= 0.5

    return base_score


async def analyze_pull_request(repo_name: str, pr_number: int, commit_sha: str):
    """Main orchestration function for evaluating pull requests based on size."""
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
    try:
            # 1. Get already reviewed files from DB
            reviewed_files = set()
            try:
                conn = await asyncpg.connect(DATABASE_URL)
                rows = await conn.fetch('''
                    SELECT filename FROM review_state
                    WHERE repo_name = $1 AND pr_number = $2 AND commit_sha = $3
                ''', repo_name, pr_number, commit_sha)
                for row in rows:
                    reviewed_files.add(row['filename'])
                await conn.close()
            except Exception as e:
                print(f"Failed to fetch reviewed files from DB: {e}")

            # 2. Fetch the PR files
            res = await mcp_session.call_tool("get_pr_files", {"repo_name": repo_name, "pr_number": pr_number})
            if res.isError:
                print(f"MCP Tool Error (get_pr_files): {res.content[0].text}")
                return
            try:
                pr_files = json.loads(res.content[0].text)
                if isinstance(pr_files, str):
                    pr_files = json.loads(pr_files)
            except Exception as e:
                print(f"Failed to parse get_pr_files response: {e}")
                return
                
            if isinstance(pr_files, dict):
                if "filename" in pr_files:
                    pr_files = [pr_files]
                else:
                    print(f"Expected list for pr_files, got dict: {pr_files}")
                    return
            if not isinstance(pr_files, list):
                print(f"Expected list for pr_files, got {type(pr_files)}: {pr_files}")
                return

            eligible_files = []
            for file_obj in pr_files:
                filename = file_obj.get("filename", "")
                status = file_obj.get("status", "")
                patch = file_obj.get("patch", "")

                if not patch or status in ["removed", "unchanged"]:
                    continue
                if filename.endswith((".lock", ".png", ".jpg", ".jpeg", ".svg", ".md", ".json")):
                    continue
                if filename in reviewed_files:
                    print(f"Skipping {filename}: Review already exists.")
                    continue

                eligible_files.append(file_obj)

            if not eligible_files:
                print("No eligible files found to review.")
                return

            for f in eligible_files:
                f['local_score'] = calculate_local_risk_score(f.get('filename', ''), f.get('patch', ''))
                f['valid_lines'] = get_valid_lines(f.get('patch', ''))
                f['numbered_patch'] = add_line_numbers_to_patch(f.get('patch', ''))

            file_count = len(eligible_files)
            print(f"Total eligible files: {file_count}")

            overall_verdicts = []

            async def review_chunk(chunk_files: list[dict]):
                files_data = []
                for f in chunk_files:
                    files_data.append({
                        "filename": f.get("filename", ""),
                        "diff_text": f.get("numbered_patch", "")
                    })

                print(f"Analyzing chunk of {len(files_data)} files with Ollama ({OLLAMA_MODEL})...")
                for attempt in range(2):
                    try:
                        review_json_str = await ask_ollama_to_review(files_data)
                        review_data = CodeReviewResult.model_validate_json(review_json_str)
                        
                        # Mark these files as reviewed in DB
                        try:
                            conn = await asyncpg.connect(DATABASE_URL)
                            for f in chunk_files:
                                await conn.execute('''
                                    INSERT INTO review_state (repo_name, pr_number, commit_sha, filename)
                                    VALUES ($1, $2, $3, $4)
                                    ON CONFLICT DO NOTHING
                                ''', repo_name, pr_number, commit_sha, f.get("filename"))
                            await conn.close()
                        except Exception as e:
                            print(f"DB Error marking files as reviewed: {e}")

                        return review_data.model_dump(), chunk_files
                    except ValidationError as e:
                        print(f"Pydantic Validation Error on attempt {attempt+1}: {e}")
                        if attempt == 1:
                            return None, chunk_files
                    except Exception as e:
                        print(f"Could not retrieve or parse review for chunk. Error: {e}")
                        return None, chunk_files
                return None, chunk_files

            async def process_and_post_chunk(chunk_files: list[dict]):
                review_data, _ = await review_chunk(chunk_files)
                if not review_data:
                    return

                verdict = review_data.get("verdict", "COMMENT")
                overall_verdicts.append(verdict)

                general_body_parts = []
                chunk_summary = review_data.get("summary", "")
                if chunk_summary:
                    general_body_parts.append(f"### Chunk Summary\n{chunk_summary}")

                valid_lines_map = {f['filename']: f['valid_lines'] for f in chunk_files}
                inline_comments = []
                seen_locations = set()

                for c in review_data.get("comments", []):
                    c_file_path = c.get("path")
                    if not c_file_path or c_file_path not in valid_lines_map:
                        continue

                    line_number = c.get("line")
                    comment_text = c.get("description", "")
                    suggestion = c.get("suggestion", "")
                    severity = c.get("severity", "info")
                    issue_type = c.get("category", "issue")

                    if line_number is None:
                        continue

                    try:
                        line_number = int(line_number)
                    except ValueError:
                        continue

                    location_key = (c_file_path, line_number)
                    if location_key in seen_locations:
                        continue
                    seen_locations.add(location_key)

                    body = f"**[{issue_type}]** {comment_text}"
                    if suggestion:
                        body += f"\n\n**Suggestion:**\n```python\n{suggestion}\n```"

                    if severity in ["low", "info"]:
                        general_body_parts.append(f"---\n📍 **{c_file_path} Line {line_number} ({severity})**\n{body}")
                    else:
                        if line_number in valid_lines_map[c_file_path]:
                            inline_comments.append({
                                "path": c_file_path,
                                "line": line_number,
                                "side": "RIGHT",
                                "body": body
                            })
                        else:
                            general_body_parts.append(f"---\n📍 **{c_file_path} Line {line_number} (Out of Diff Context)**\n{body}")

                if not inline_comments and len(general_body_parts) <= 1:
                    return

                general_body = "\n\n".join(general_body_parts)

                review_payload = {
                    "commit_id": commit_sha,
                    "body": general_body,
                    "event": "COMMENT",
                    "comments": inline_comments
                }

                try:
                    await mcp_session.call_tool("post_review_comment", {"repo_name": repo_name, "pr_number": pr_number, "payload": review_payload})
                    print(f"Review for chunk posted successfully with {len(inline_comments)} inline comments!")
                except Exception as e:
                    if "422 Unprocessable Entity" in str(e):
                        print(f"Failed to post inline comments for chunk. Falling back to general review comment...")
                        fallback_body = review_payload["body"] + "\n\n### Detailed Comments\n"
                        for ic in inline_comments:
                            fallback_body += f"\n---\n📍 **{ic['path']} (Line {ic['line']})**\n{ic['body']}\n"
                        review_payload["body"] = fallback_body
                        review_payload["comments"] = []

                        try:
                            await mcp_session.call_tool("post_review_comment", {"repo_name": repo_name, "pr_number": pr_number, "payload": review_payload})
                        except Exception as inner_e:
                            print(f"Failed to post fallback review: {inner_e}")
                    else:
                        print(f"Failed to post review for chunk: {e}")

            def get_dir(f):
                parts = f['filename'].split('/')
                return parts[0] if len(parts) > 1 else ''

            def chunk_files_fn(files_to_chunk):
                files_to_chunk.sort(key=lambda f: (-f.get('local_score', 0), get_dir(f)))
                chunks = []
                for i in range(0, len(files_to_chunk), 3):
                    chunks.append(files_to_chunk[i:i + 3])
                if len(chunks) > 1 and len(chunks[-1]) == 1:
                    last = chunks.pop()
                    chunks[-1].extend(last)
                return chunks

            # --- Adaptive Strategy Logic ---
            if file_count >= 50:
                print("Strategy: Summary only (50+ files)")
                try:
                    summary_json_str = await ask_ollama_summary(eligible_files)
                    summary_data = SummaryReviewResult.model_validate_json(summary_json_str).model_dump()
                    body_text = f"### Ollama AI PR Summary (50+ files)\n\n*Due to the size of this PR, a deep line-by-line review was skipped.*\n\n**Summary:**\n{summary_data.get('summary', '')}\n\n**Module Risks:**\n"
                    for risk in summary_data.get('module_risks', []):
                        body_text += f"- {risk}\n"

                    await mcp_session.call_tool("post_review_comment", {"repo_name": repo_name, "pr_number": pr_number, "payload": {"commit_id": commit_sha, "body": body_text, "event": "COMMENT", "comments": []}})
                except Exception as e:
                    print(f"Error generating summary: {e}")

            elif file_count >= 21:
                print("Strategy: Triage + Chunked Review (21-49 files)")
                triage_candidates = [f for f in eligible_files if f['local_score'] > 0]
                print(f"Sending {len(triage_candidates)} files for AI triage.")

                try:
                    triage_json_str = await ask_ollama_triage(triage_candidates)
                    triage_data = TriageResult.model_validate_json(triage_json_str).model_dump()

                    file_map = {f['filename']: f for f in triage_candidates}

                    for tf in triage_data.get('files', []):
                        fname = tf.get('filename')
                        if fname in file_map:
                            file_map[fname]['local_score'] = tf.get('risk_score', 0)

                    triage_candidates.sort(key=lambda f: (-f.get('local_score', 0), get_dir(f)))
                    top_files = triage_candidates[:15]

                    chunks = chunk_files_fn(top_files)

                    triage_msg = f"### Ollama AI Review Status\n\nThis PR contains {file_count} files. Performed AI triage and selected the top {len(top_files)} highest-risk files for deep review.\n\n*Model: `{OLLAMA_MODEL}` running locally via Ollama*"
                    await mcp_session.call_tool("post_issue_comment", {"repo_name": repo_name, "pr_number": pr_number, "body": triage_msg})

                    for chunk in chunks:
                        await process_and_post_chunk(chunk)
                        await asyncio.sleep(2)
                except Exception as e:
                    print(f"Error during triage: {e}")

            elif file_count >= 6:
                print("Strategy: Chunked Review (6-20 files)")
                chunks = chunk_files_fn(eligible_files)
                for chunk in chunks:
                    await process_and_post_chunk(chunk)
                    await asyncio.sleep(2)

            else:
                print("Strategy: Single Prompt (1-5 files)")
                await process_and_post_chunk(eligible_files)

            # Stale-SHA guard
            res = await mcp_session.call_tool("check_pr_sha", {"repo_name": repo_name, "pr_number": pr_number})
            if res.isError:
                print(f"MCP Tool Error (check_pr_sha): {res.content[0].text}")
                return
            try:
                current_sha = json.loads(res.content[0].text)
                if isinstance(current_sha, str) and (current_sha.startswith("{") or current_sha.startswith('"')):
                    # If it's a JSON string of a string, loads will handle it, but just in case
                    try:
                        current_sha = json.loads(current_sha)
                    except:
                        pass
            except Exception as e:
                print(f"Failed to parse check_pr_sha response: {e}")
                return
            if current_sha and current_sha != commit_sha:
                print(f"PR HEAD SHA has changed ({current_sha} != {commit_sha}). Aborting final review post.")
                return

            # Post final meta-summary
            if file_count < 50:
                final_verdict = "COMMENT"
                if "REQUEST_CHANGES" in overall_verdicts:
                    final_verdict = "REQUEST_CHANGES"
                elif "APPROVE" in overall_verdicts and "REQUEST_CHANGES" not in overall_verdicts:
                    final_verdict = "APPROVE"

                meta_summary = f"### Ollama AI Overall Verdict\n\nAll chunks have been reviewed by `{OLLAMA_MODEL}` running locally. Final Verdict: **{final_verdict}**."
                summary_payload = {
                    "commit_id": commit_sha,
                    "body": meta_summary,
                    "event": final_verdict,
                    "comments": []
                }
                await mcp_session.call_tool("post_review_comment", {"repo_name": repo_name, "pr_number": pr_number, "payload": summary_payload})

    except Exception as e:
        print(f"Exception during PR analysis: {e}")