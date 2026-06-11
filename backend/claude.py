import time

import requests

from config import ANTHROPIC_API_KEY, ANTHROPIC_API_URL, CLAUDE_MODEL

# Transient HTTP statuses worth retrying with exponential backoff.
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2


class ClaudeAPI:
    def __init__(self):
        self.api_key = ANTHROPIC_API_KEY
        self.base_url = f"{ANTHROPIC_API_URL.rstrip('/')}/v1/messages"
        self.model = CLAUDE_MODEL

    def get_response(self, agent_name, context, memory=None):
        if not self.api_key:
            print("ANTHROPIC_API_KEY is not set. Skipping Claude request.")
            return None

        memory_context = ""
        if memory:
            memory_context = "\n\nRelevant memory:\n" + "\n".join(f"- {mem}" for mem in memory)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        data = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0.8,
            "system": f"You are {agent_name}, a character in a multi-agent virtual town simulation.",
            "messages": [
                {
                    "role": "user",
                    "content": f"{context}{memory_context}"
                }
            ]
        }

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(self.base_url, headers=headers, json=data, timeout=60)
                if response.status_code == 200:
                    result = response.json()
                    text_parts = [
                        block.get("text", "")
                        for block in result.get("content", [])
                        if block.get("type") == "text"
                    ]
                    return "".join(text_parts).strip() or None

                last_error = f"status {response.status_code}: {response.text}"
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    print(f"Claude request failed ({last_error}).")
                    return None
            except requests.RequestException as error:
                last_error = str(error)

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2 ** attempt)
                print(f"Claude request transient failure ({last_error}); retrying in {backoff}s.")
                time.sleep(backoff)

        print(f"Claude request failed after {MAX_RETRIES} attempts: {last_error}")
        return None
