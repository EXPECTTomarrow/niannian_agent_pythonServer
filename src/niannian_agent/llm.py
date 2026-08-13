from typing import Optional
import httpx
from .config import Settings

class DashScopeClient:
    def __init__(self, settings: Optional[Settings] = None, http_client: Optional[httpx.Client] = None) -> None:
        self.settings = settings or Settings()
        self.http = http_client or httpx.Client(timeout=30)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        if not self.settings.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required")
        response = self.http.post(
            f"{self.settings.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.api_key}"},
            json={"model": self.settings.model, "messages": messages, "tools": [{"type": "function", "function": t} for t in tools], "temperature": self.settings.temperature, "max_tokens": self.settings.max_tokens, "enable_thinking": False},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]
