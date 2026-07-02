import json
import asyncio
from services.llm_service import LLMService
from services.github_service import GithubService

class ReviewStrategy:
    def __init__(self, llm_service: LLMService, github_service: GithubService, commit_sha: str):
        self.llm = llm_service
        self.github = github_service
        self.commit_sha = commit_sha
        self.overall_verdicts = []

    async def execute(self, eligible_files: list[dict]):
        raise NotImplementedError("Subclasses must implement execute method.")

    def _get_dir(self, f):
        parts = f.get('filename', '').split('/')
        return parts[0] if len(parts) > 1 else ''

    def _chunk_files(self, files_to_chunk):
        files_to_chunk.sort(key=lambda f: (-f.get('local_score', 0), self._get_dir(f)))
        chunks = []
        for i in range(0, len(files_to_chunk), 3):
            chunks.append(files_to_chunk[i:i + 3])
        if len(chunks) > 1 and len(chunks[-1]) == 1:
            last = chunks.pop()
            chunks[-1].extend(last)
        return chunks

    async def _process_and_post_chunk(self, chunk_files: list[dict], pr_number: int):
        files_data = []
        for f in chunk_files:
            files_data.append({
                "filename": f.get("filename", ""),
                "diff_text": f.get("numbered_patch", "")
            })

        print(f"Analyzing chunk of {len(files_data)} files with Ollama ({self.llm.ollama_model})...")
        try:
            review_json_str = await self.llm.ask_ollama_to_review(files_data)
            review_data = json.loads(review_json_str)
        except Exception as e:
            print(f"Could not retrieve or parse review for chunk. Error: {e}")
            return

        if not review_data:
            return

        verdict = review_data.get("verdict", "COMMENT")
        self.overall_verdicts.append(verdict)

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
            "commit_id": self.commit_sha,
            "body": general_body,
            "event": "COMMENT",
            "comments": inline_comments
        }

        res = await self.github.post_review(pr_number, review_payload)

        if res.status_code in [200, 201]:
            print(f"Review for chunk posted successfully with {len(inline_comments)} inline comments!")
        elif res.status_code == 422:
            print(f"Failed to post inline comments for chunk. Falling back to general review comment...")
            fallback_body = review_payload["body"] + "\n\n### Detailed Comments\n"
            for ic in inline_comments:
                fallback_body += f"\n---\n📍 **{ic['path']} (Line {ic['line']})**\n{ic['body']}\n"
            review_payload["body"] = fallback_body
            review_payload["comments"] = []

            fallback_res = await self.github.post_review(pr_number, review_payload)
            if fallback_res.status_code not in [200, 201]:
                print(f"Failed to post fallback review. Status: {fallback_res.status_code}, Response: {fallback_res.text}")
        else:
            print(f"Failed to post review for chunk. Status: {res.status_code}, Response: {res.text}")

    async def post_meta_summary(self, pr_number: int):
        final_verdict = "COMMENT"
        if "REQUEST_CHANGES" in self.overall_verdicts:
            final_verdict = "REQUEST_CHANGES"
        elif "APPROVE" in self.overall_verdicts and "REQUEST_CHANGES" not in self.overall_verdicts:
            final_verdict = "APPROVE"

        meta_summary = f"### Ollama AI Overall Verdict\n\nAll chunks have been reviewed by `{self.llm.ollama_model}` running locally. Final Verdict: **{final_verdict}**."
        summary_payload = {
            "commit_id": self.commit_sha,
            "body": meta_summary,
            "event": final_verdict,
            "comments": []
        }
        await self.github.post_review(pr_number, summary_payload)


class SummaryOnlyStrategy(ReviewStrategy):
    async def execute(self, eligible_files: list[dict], pr_number: int):
        print("Strategy: Summary only (50+ files)")
        try:
            summary_json_str = await self.llm.ask_ollama_summary(eligible_files)
            summary_data = json.loads(summary_json_str)
            body_text = f"### Ollama AI PR Summary (50+ files)\n\n*Due to the size of this PR, a deep line-by-line review was skipped.*\n\n**Summary:**\n{summary_data.get('summary', '')}\n\n**Module Risks:**\n"
            for risk in summary_data.get('module_risks', []):
                body_text += f"- {risk}\n"

            await self.github.post_review(pr_number, {
                "commit_id": self.commit_sha,
                "body": body_text,
                "event": "COMMENT",
                "comments": []
            })
        except Exception as e:
            print(f"Error generating summary: {e}")


class TriageChunkedStrategy(ReviewStrategy):
    async def execute(self, eligible_files: list[dict], pr_number: int):
        print("Strategy: Triage + Chunked Review (21-49 files)")
        triage_candidates = [f for f in eligible_files if f['local_score'] > 0]
        print(f"Sending {len(triage_candidates)} files for AI triage.")

        try:
            triage_json_str = await self.llm.ask_ollama_triage(triage_candidates)
            triage_data = json.loads(triage_json_str)

            file_map = {f['filename']: f for f in triage_candidates}

            for tf in triage_data.get('files', []):
                fname = tf.get('filename')
                if fname in file_map:
                    file_map[fname]['local_score'] = tf.get('risk_score', 0)

            triage_candidates.sort(key=lambda f: (-f.get('local_score', 0), self._get_dir(f)))
            top_files = triage_candidates[:15]

            chunks = self._chunk_files(top_files)

            triage_msg = f"### Ollama AI Review Status\n\nThis PR contains {len(eligible_files)} files. Performed AI triage and selected the top {len(top_files)} highest-risk files for deep review.\n\n*Model: `{self.llm.ollama_model}` running locally via Ollama*"
            await self.github.post_issue_comment(pr_number, {"body": triage_msg})

            for chunk in chunks:
                await self._process_and_post_chunk(chunk, pr_number)
                await asyncio.sleep(2)
            
            await self.post_meta_summary(pr_number)
        except Exception as e:
            print(f"Error during triage: {e}")


class ChunkedStrategy(ReviewStrategy):
    async def execute(self, eligible_files: list[dict], pr_number: int):
        print("Strategy: Chunked Review (6-20 files)")
        chunks = self._chunk_files(eligible_files)
        for chunk in chunks:
            await self._process_and_post_chunk(chunk, pr_number)
            await asyncio.sleep(2)
        
        await self.post_meta_summary(pr_number)


class SinglePromptStrategy(ReviewStrategy):
    async def execute(self, eligible_files: list[dict], pr_number: int):
        print("Strategy: Single Prompt (1-5 files)")
        await self._process_and_post_chunk(eligible_files, pr_number)
        await self.post_meta_summary(pr_number)

class StrategyFactory:
    @staticmethod
    def get_strategy(file_count: int, llm_service: LLMService, github_service: GithubService, commit_sha: str) -> ReviewStrategy:
        if file_count >= 50:
            return SummaryOnlyStrategy(llm_service, github_service, commit_sha)
        elif file_count >= 21:
            return TriageChunkedStrategy(llm_service, github_service, commit_sha)
        elif file_count >= 6:
            return ChunkedStrategy(llm_service, github_service, commit_sha)
        else:
            return SinglePromptStrategy(llm_service, github_service, commit_sha)
