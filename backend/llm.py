import json
import re
import time

import requests

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from observability import log_llm_call

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

    def _post_with_retries(self, agent_name, payload):
        """POST the payload, retrying transient failures; returns the first
        choice message dict, or None when the request ultimately fails.

        Every outcome (success, empty, failure, skipped) is recorded as a
        structured trace via ``log_llm_call``."""
        call_kind = "tool" if payload.get("tools") else "text"

        if not self.api_key:
            print("LLM_API_KEY is not set. Skipping LLM request.")
            log_llm_call({
                "agent_name": agent_name,
                "call_kind": call_kind,
                "model": payload.get("model"),
                "prompt": payload.get("messages"),
                "status": "skipped",
                "error": "no_api_key",
                "attempts": 0,
                "latency_ms": 0,
            })
            return None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        last_error = None
        last_status = None
        usage = None
        message = None
        status = "failed"
        attempts = 0
        started = time.monotonic()

        for attempt in range(MAX_RETRIES):
            attempts = attempt + 1
            try:
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=60)
                last_status = response.status_code
                if response.status_code == 200:
                    body = response.json()
                    usage = body.get("usage") or {}
                    choices = body.get("choices") or []
                    message = (choices[0].get("message") if choices else None) or None
                    status = "success" if message else "empty"
                    break

                last_error = f"status {response.status_code}: {response.text}"
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    break
            except requests.RequestException as error:
                last_error = str(error)

            if attempt < MAX_RETRIES - 1:
                backoff = BASE_BACKOFF_SECONDS * (2 ** attempt)
                print(f"LLM request transient failure ({last_error}); retrying in {backoff}s.")
                time.sleep(backoff)

        latency_ms = int((time.monotonic() - started) * 1000)

        response_for_log = None
        if message is not None:
            if call_kind == "tool":
                tool_calls = message.get("tool_calls") or []
                response_for_log = tool_calls[0].get("function", {}).get("arguments") if tool_calls else None
            else:
                response_for_log = message.get("content")

        log_llm_call({
            "agent_name": agent_name,
            "call_kind": call_kind,
            "model": payload.get("model"),
            "prompt": payload.get("messages"),
            "response": response_for_log,
            "status": status,
            "http_status": last_status,
            "attempts": attempts,
            "latency_ms": latency_ms,
            "prompt_tokens": (usage or {}).get("prompt_tokens"),
            "completion_tokens": (usage or {}).get("completion_tokens"),
            "total_tokens": (usage or {}).get("total_tokens"),
            "error": None if status == "success" else last_error,
        })

        if status == "failed":
            print(f"LLM request failed after {attempts} attempt(s): {last_error}")
        return message  # the message dict on success; None on failure/empty

    def rate_importance(self, agent_name, memory_text, fallback=4):
        """Score how poignant/significant a memory is on a 1-10 scale.

        Mundane routines (eating, walking to a room) score low; emotionally or
        socially significant events (a heartfelt talk, a conflict, a milestone)
        score high. Returns the integer score, or ``fallback`` when the LLM is
        unavailable or the reply cannot be parsed."""
        context = (
            "On a scale of 1 to 10, rate how poignant the following memory is. "
            "1 is purely mundane (brushing teeth, walking to another room, a "
            "routine meal); 10 is extremely significant (a heartfelt or tense "
            "conversation, a conflict, a milestone, a strong emotional moment).\n"
            f"Memory: \"{memory_text}\"\n"
            "Respond with a single integer from 1 to 10 and nothing else."
        )
        reply = self.get_response(agent_name, context)
        if not reply:
            return fallback
        match = re.search(r"\d+", reply)
        if not match:
            return fallback
        return max(1, min(10, int(match.group())))

    def get_response(self, agent_name, context, memory=None):
        """Free-text completion, used for dialogue and reflection."""
        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0.8,
            "messages": self._build_messages(agent_name, context, memory)
        }
        message = self._post_with_retries(agent_name, payload)
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
        message = self._post_with_retries(agent_name, payload)
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
