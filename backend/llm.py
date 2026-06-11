import json
import time

import requests

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

# Transient HTTP statuses worth retrying with exponential backoff.
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2


class LLMClient:
    """Chat client for any OpenAI-compatible endpoint (DeepSeek by default).

    Supports plain text responses for dialogue/reflection and forced function
    calling for structured decisions (next-action planning).
    """

    def __init__(self):
        self.api_key = LLM_API_KEY
        self.base_url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
        self.model = LLM_MODEL

    def _build_messages(self, agent_name, context, memory=None):
        memory_context = ""
        if memory:
            memory_context = "\n\nRelevant memory:\n" + "\n".join(f"- {mem}" for mem in memory)
        return [
            {
                "role": "system",
                "content": f"You are {agent_name}, a character in a multi-agent virtual town simulation."
            },
            {
                "role": "user",
                "content": f"{context}{memory_context}"
            }
        ]

    def _post_with_retries(self, payload):
        """POST the payload, retrying transient failures; returns the first
        choice message dict, or None when the request ultimately fails."""
        if not self.api_key:
            print("LLM_API_KEY is not set. Skipping LLM request.")
            return None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
                if response.status_code == 200:
                    choices = response.json().get("choices") or []
                    if choices:
                        return choices[0].get("message") or None
                    return None

                last_error = f"status {response.status_code}: {response.text}"
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    print(f"LLM request failed ({last_error}).")
                    return None
            except requests.RequestException as error:
                last_error = str(error)

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2 ** attempt)
                print(f"LLM request transient failure ({last_error}); retrying in {backoff}s.")
                time.sleep(backoff)

        print(f"LLM request failed after {MAX_RETRIES} attempts: {last_error}")
        return None

    def get_response(self, agent_name, context, memory=None):
        """Free-text completion, used for dialogue and reflection."""
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0.8,
            "messages": self._build_messages(agent_name, context, memory)
        }
        message = self._post_with_retries(payload)
        if not message:
            return None
        return (message.get("content") or "").strip() or None

    def call_tool(self, agent_name, context, tool_name, tool_description, parameters, memory=None):
        """Forced function call returning the parsed argument dict, or None.

        The endpoint must fill the declared parameter schema, which removes
        the need to parse free text on the caller's side."""
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0.7,
            "messages": self._build_messages(agent_name, context, memory),
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": parameters
                    }
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": tool_name}}
        }
        message = self._post_with_retries(payload)
        if not message:
            return None

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return None

        arguments = tool_calls[0].get("function", {}).get("arguments")
        try:
            parsed = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            print(f"LLM tool call returned malformed JSON arguments: {arguments!r}")
            return None
        return parsed if isinstance(parsed, dict) else None
