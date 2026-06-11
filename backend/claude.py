import requests
from config import ANTHROPIC_API_KEY, ANTHROPIC_API_URL, CLAUDE_MODEL


class ClaudeAPI:
    def __init__(self):
        self.api_key = ANTHROPIC_API_KEY
        self.base_url = f"{ANTHROPIC_API_URL.rstrip('/')}/v1/messages"
        self.model = CLAUDE_MODEL

    def get_response(self, agent_name, context, memory):
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

        try:
            response = requests.post(self.base_url, headers=headers, json=data, timeout=60)
            if response.status_code != 200:
                print(f"Claude request failed: {response.status_code}")
                print(response.text)
                return None

            result = response.json()
            text_parts = [
                block.get("text", "")
                for block in result.get("content", [])
                if block.get("type") == "text"
            ]
            return "".join(text_parts).strip() or None
        except Exception as error:
            print(f"Claude request error: {error}")
            return None
