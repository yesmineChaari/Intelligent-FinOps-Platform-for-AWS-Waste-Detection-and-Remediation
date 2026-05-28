"""
runners/groq_runner.py

Groq API runner.
Covers: qwen3-coder-32b, llama-3.3-70b, and the NL judge (llama-3.1-8b-instant).

Groq uses the OpenAI-compatible chat completions endpoint, so the payload
structure is identical to the OpenAI SDK — role-based messages array,
response_format for JSON mode, standard max_tokens and temperature.

Rate limits from config (free tier):
  qwen3-coder-32b  : 60 RPM, 1000 RPD, interval_seconds=10
  llama-3.3-70b    : 30 RPM, 1000 RPD, interval_seconds=10
"""

import logging
import time
import requests
from .base_runner import BaseRunner, ContextTooLargeError

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqRunner(BaseRunner):

    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")

        payload = {
            "model":       self.model_cfg["model_id"],
            "max_tokens":  self.model_cfg.get("max_tokens", 4096),
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            # JSON mode disabled: Groq rejects responses containing HCL Terraform
            # strings (backslashes, quotes) as invalid JSON. BaseRunner._parse_json
            # handles extraction via 4 fallback strategies instead.
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }

        resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=120)

        # 413 = context too large — not retryable, signal caller to use a larger model
        if resp.status_code == 413:
            raise ContextTooLargeError(f"Groq 413: {resp.text[:300]}")

        # 429 = rate limit — sleep for the reset window then let base_runner retry
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset-requests")
            try:
                wait = max(1, int(float(retry_after))) if retry_after else 62
            except (TypeError, ValueError):
                wait = 62
            msg = f"[{self.model_cfg['model_id']}] 429 — retry-after={wait}s | body: {resp.text[:400]}"
            logger.info(msg)
            print(msg, flush=True)
            if wait > 120:
                raise RuntimeError(
                    f"Groq 429 retry-after={wait}s exceeds 2 minutes — aborting. Body: {resp.text[:300]}"
                )
            time.sleep(wait)
            raise ConnectionError(f"Groq 429 rate limit: {resp.text[:200]}")

        # 401/403 = bad API key — non-retryable
        if resp.status_code in (401, 403):
            raise RuntimeError(f"Groq auth error {resp.status_code}: {resp.text[:200]}")

        # Any other non-200 — treat as retryable server error
        if resp.status_code != 200:
            raise ConnectionError(f"Groq {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        return data["choices"][0]["message"]["content"]