import unittest

from niannian_agent.config import Settings
from niannian_agent.llm import DashScopeClient


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "好的"}}]}


class HttpClient:
    def __init__(self):
        self.payload = None

    def post(self, _url, headers, json):
        self.payload = {"headers": headers, "json": json}
        return Response()


class DashScopeClientTests(unittest.TestCase):
    def test_disables_thinking_in_the_model_request(self):
        http = HttpClient()
        client = DashScopeClient(Settings(api_key="test", max_tokens=128), http)

        client.chat([{"role": "user", "content": "你好"}], [])

        self.assertFalse(http.payload["json"]["enable_thinking"])


if __name__ == "__main__":
    unittest.main()
