import os
import json
import asyncio
import sys
from pydantic import ValidationError
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

from models.schemas import CodeReviewResult, TriageResult, SummaryReviewResult
from dotenv import load_dotenv

from services.db_service import init_db, get_reviewed_files, mark_files_as_reviewed
from services.github_auth_service import get_github_installation_token
from services.ollama_service import ask_ollama_to_review, ask_ollama_triage, ask_ollama_summary, OLLAMA_MODEL
from utils.diff_parser import get_valid_lines, add_line_numbers_to_patch, calculate_local_risk_score

load_dotenv()

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
        reviewed_files = await get_reviewed_files(repo_name, pr_number, commit_sha)

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
                    chunk_filenames = [f.get("filename") for f in chunk_files]
                    await mark_files_as_reviewed(repo_name, pr_number, commit_sha, chunk_filenames)

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
            # FastMCP returns raw strings as-is for str return types
            current_sha = res.content[0].text.strip().strip('"')
        except Exception as e:
            print(f"Failed to read check_pr_sha response: {e}")
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