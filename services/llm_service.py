import os
import re
import asyncio
import httpx
from dotenv import load_dotenv
from constants.prompts import REVIEW_PROMPT_TEMPLATE, TRIAGE_PROMPT_TEMPLATE, SUMMARY_PROMPT_TEMPLATE

load_dotenv()

class LLMService:
    def __init__(self):
        self.ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

    async def _call_ollama(self, prompt: str, max_retries: int = 3) -> str:
        """Core function to send an HTTP POST request to the local Ollama instance."""
        payload = {
            "model": self.ollama_model,
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
                        f"{self.ollama_base_url}/api/chat",
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

    def _extract_json(self, text: str) -> str:
        """Extracts JSON object from model output."""
        # Strip markdown code fences if present
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            return fenced.group(1)

        # Find the first { ... } block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        return text  # Return as-is and let the caller handle parse errors

    async def ask_ollama_to_review(self, files_data: list[dict], max_retries: int = 3) -> str:
        """Queries local Ollama to review parsed code vulnerabilities."""
        diff_context = ""
        for fd in files_data:
            diff_context += f"\n\n### Filename: `{fd['filename']}`\n{fd['diff_text']}"

        full_prompt = REVIEW_PROMPT_TEMPLATE.format(diff_context=diff_context)
        raw = await self._call_ollama(full_prompt, max_retries)
        return self._extract_json(raw)

    async def ask_ollama_triage(self, files_metadata: list[dict], max_retries: int = 3) -> str:
        """Asks Ollama to re-rank and flag risky files heuristically."""
        context_str = ""
        for f in files_metadata:
            context_str += f"- `{f['filename']}` | Added: {f.get('additions', 0)} | Deleted: {f.get('deletions', 0)} | Local Score: {f.get('local_score', 0)}\n"

        full_prompt = TRIAGE_PROMPT_TEMPLATE.format(context_str=context_str)
        raw = await self._call_ollama(full_prompt, max_retries)
        return self._extract_json(raw)

    async def ask_ollama_summary(self, files_metadata: list[dict], max_retries: int = 3) -> str:
        """Provides a high-level module risk summary for large PRs (50+ files)."""
        context_str = ""
        for f in files_metadata:
            context_str += f"- `{f['filename']}` | Added: {f.get('additions', 0)} | Local Score: {f.get('local_score', 0)}\n"

        full_prompt = SUMMARY_PROMPT_TEMPLATE.format(context_str=context_str)
        raw = await self._call_ollama(full_prompt, max_retries)
        return self._extract_json(raw)
