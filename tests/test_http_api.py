import base64
import hashlib
import io
import hmac
import json
import unittest
from contextlib import redirect_stdout

from niannian_agent.http_api import create_server


def actor_token(payload, secret):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{encoded}.{signature}"


class HttpApiTests(unittest.TestCase):
    def test_chat_uses_verified_token_owner_not_client_user_id(self):
        calls = []

        class Agent:
            def run(self, session_id, user_id, message, actor_token, request_id):
                calls.append((session_id, user_id, message, actor_token, request_id))
                return {"status": "completed", "content": "已找到小王", "revision": 2}

        secret = "test-secret"
        token = actor_token({"openid": "trusted-user", "scope": "personal", "exp": 9999999999999}, secret)
        server = create_server(Agent(), secret)
        body, status = server.handle_json({"sessionId": "s1", "userId": "forged", "message": "查小王", "actorToken": token, "requestId": "request-1"})

        self.assertEqual(status, 200)
        self.assertEqual(body["content"], "已找到小王")
        self.assertEqual(calls[0][1], "trusted-user")
        self.assertEqual(calls[0][4], "request-1")

    def test_chat_rejects_invalid_actor_token(self):
        server = create_server(object(), "test-secret")
        body, status = server.handle_json({"sessionId": "s1", "message": "查小王", "actorToken": "invalid"})
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "ACTOR_TOKEN_INVALID")

    def test_chat_logs_request_id_and_failure_summary_when_agent_fails(self):
        class Agent:
            def run(self, *_):
                raise RuntimeError("model request failed")

        secret = "test-secret"
        token = actor_token({"openid": "trusted-user", "scope": "personal", "exp": 9999999999999}, secret)
        server = create_server(Agent(), secret)
        output = io.StringIO()

        with redirect_stdout(output):
            body, status = server.handle_json({"sessionId": "s1", "message": "查小王", "actorToken": token, "requestId": "request-2"})

        self.assertEqual(status, 502)
        self.assertEqual(body["code"], "AGENT_UNAVAILABLE")
        self.assertIn('"event": "agent.error"', output.getvalue())
        self.assertIn('"requestId": "request-2"', output.getvalue())
        self.assertIn('"stage": "agent.run"', output.getvalue())
        self.assertIn('"errorType": "RuntimeError"', output.getvalue())

    def test_chat_returns_a_stable_ui_instruction_envelope(self):
        class Agent:
            def run(self, *_args, **_kwargs):
                return {"status": "completed", "content": "已找到朱思远。", "revision": 2, "subjectContact": {"id": "zhu-1", "name": "朱思远", "scope": "org-1"}}

        secret = "test-secret"
        token = actor_token({"openid": "trusted-user", "scope": "org-1", "exp": 9999999999999}, secret)
        body, status = create_server(Agent(), secret).handle_json({"sessionId": "s1", "message": "查询朱思远", "actorToken": token})

        self.assertEqual(status, 200)
        self.assertEqual(body["ui"]["kind"], "reply")
        self.assertEqual(body["ui"]["subjectContact"]["id"], "zhu-1")

    def test_progress_events_are_ndjson_and_end_with_the_final_response(self):
        class Agent:
            def run(self, *_args, progress=None, **_kwargs):
                progress("正在查询通讯录")
                return {"status": "completed", "content": "已完成", "revision": 1}

        secret = "test-secret"
        token = actor_token({"openid": "trusted-user", "scope": "personal", "exp": 9999999999999}, secret)
        events, status = create_server(Agent(), secret).handle_stream({"sessionId": "s1", "message": "查一下", "actorToken": token})

        self.assertEqual(status, 200)
        self.assertEqual(events[0], {"type": "progress", "content": "正在查询通讯录"})
        self.assertEqual(events[-1]["type"], "final")


if __name__ == "__main__":
    unittest.main()
