import base64
import hashlib
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_actor_token(token: str, secret: str) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(secret.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).digest()
        supplied = _decode_base64url(signature)
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        payload = json.loads(_decode_base64url(encoded))
        if not payload.get("openid") or float(payload.get("exp", 0)) <= time.time() * 1000:
            raise ValueError
        return payload
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("ACTOR_TOKEN_INVALID")


class AgentHttpApplication:
    def __init__(self, agent: Any, token_secret: str) -> None:
        self.agent = agent
        self.token_secret = token_secret

    def handle_json(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        try:
            actor_token = str(payload.get("actorToken", ""))
            actor = verify_actor_token(actor_token, self.token_secret)
            action = str(payload.get("action", "chat"))
            if action == "conversation.list":
                return self.agent.list_conversations(actor_token), 200
            if action == "conversation.load":
                session_id = str(payload.get("sessionId", "")).strip()
                return self.agent.load_history(session_id, actor["openid"], actor_token), 200
            session_id = str(payload.get("sessionId", "")).strip()
            message = str(payload.get("message", "")).strip()
            request_id = str(payload.get("requestId", "")).strip()[:100]
            if not session_id or not message:
                return {"code": "REQUEST_INVALID"}, 400
            import_summary = payload.get("importSummary") if isinstance(payload.get("importSummary"), dict) else None
            subject_contact = payload.get("subjectContact") if isinstance(payload.get("subjectContact"), dict) else None
            require_observation = payload.get("requireObservation") is True
            def run_agent(*args: Any, **kwargs: Any) -> dict[str, Any]:
                if subject_contact is not None:
                    kwargs["subject_contact"] = subject_contact
                kwargs["authorized_scope"] = str(actor.get("scope", ""))
                return self.agent.run(*args, **kwargs)
            if import_summary is None:
                if not require_observation:
                    return self._response(run_agent(session_id, actor["openid"], message, actor_token, request_id)), 200
                return self._response(run_agent(session_id, actor["openid"], message, actor_token, request_id, require_observation=True)), 200
            if not require_observation:
                return self._response(run_agent(session_id, actor["openid"], message, actor_token, request_id, import_summary)), 200
            return self._response(run_agent(session_id, actor["openid"], message, actor_token, request_id, import_summary, True)), 200
        except ValueError as error:
            return {"code": str(error)}, 401
        except Exception as error:
            print(json.dumps({
                "event": "agent.error",
                "requestId": str(payload.get("requestId", "")).strip()[:100],
                "stage": "agent.run",
                "errorType": type(error).__name__,
                "message": str(error)[:300],
            }, ensure_ascii=False), flush=True)
            return {"code": "AGENT_UNAVAILABLE"}, 502

    def handle_stream(self, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        events: list[dict[str, Any]] = []
        status = self.stream_to(payload, events.append)
        return events, status

    def stream_to(self, payload: dict[str, Any], emit: Any) -> int:
        try:
            actor_token = str(payload.get("actorToken", ""))
            actor = verify_actor_token(actor_token, self.token_secret)
            session_id = str(payload.get("sessionId", "")).strip()
            message = str(payload.get("message", "")).strip()
            request_id = str(payload.get("requestId", "")).strip()[:100]
            if not session_id or not message:
                emit({"type": "error", "code": "REQUEST_INVALID"}); return 400
            result = self.agent.run(session_id, actor["openid"], message, actor_token, request_id, require_observation=payload.get("requireObservation") is True, subject_contact=payload.get("subjectContact") if isinstance(payload.get("subjectContact"), dict) else None, progress=lambda content: emit({"type": "progress", "content": content}), authorized_scope=str(actor.get("scope", "")))
            emit({"type": "final", "data": self._response(result)})
            return 200
        except ValueError as error:
            emit({"type": "error", "code": str(error)}); return 401
        except Exception as error:
            print(json.dumps({"event": "agent.error", "stage": "agent.stream", "errorType": type(error).__name__, "message": str(error)[:300]}, ensure_ascii=False), flush=True)
            emit({"type": "error", "code": "AGENT_UNAVAILABLE"}); return 502

    @staticmethod
    def _response(result: dict[str, Any]) -> dict[str, Any]:
        output = result if isinstance(result, dict) else {}
        supplied_ui = output.get("ui") if isinstance(output.get("ui"), dict) else {}
        return {
            **output,
            "ui": {
                "kind": supplied_ui.get("kind") or ("import_plan" if "importPlan" in output else "reply"),
                "content": str(output.get("content", "")),
                "subjectContact": output.get("subjectContact") if isinstance(output.get("subjectContact"), dict) else None,
                "importPlan": output.get("importPlan") if isinstance(output.get("importPlan"), list) else [],
                **({"plan": supplied_ui["plan"]} if isinstance(supplied_ui.get("plan"), dict) else {}),
                **({"candidates": supplied_ui["candidates"]} if isinstance(supplied_ui.get("candidates"), list) else {}),
                **({"title": supplied_ui["title"]} if isinstance(supplied_ui.get("title"), str) else {}),
                **({"options": supplied_ui["options"]} if isinstance(supplied_ui.get("options"), list) else {}),
                **({"draft": supplied_ui["draft"]} if isinstance(supplied_ui.get("draft"), dict) else {}),
                **({"scope": supplied_ui["scope"]} if isinstance(supplied_ui.get("scope"), str) else {}),
            },
        }


def create_server(agent: Any, token_secret: str) -> AgentHttpApplication:
    return AgentHttpApplication(agent, token_secret)


def serve(application: AgentHttpApplication, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200 if self.path == "/health" else 404)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"} if self.path == "/health" else {"code": "NOT_FOUND"}).encode())

        def do_POST(self) -> None:
            if self.path not in {"/chat", "/chat/stream", "/conversations"}:
                self.send_response(404); self.end_headers(); return
            try:
                size = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(min(size, 64 * 1024)))
                if self.path == "/chat/stream":
                    self.send_response(200)
                    self.send_header("content-type", "application/x-ndjson; charset=utf-8")
                    self.send_header("transfer-encoding", "chunked")
                    self.end_headers()
                    def emit(event: dict[str, Any]) -> None:
                        line = (json.dumps(event, ensure_ascii=False) + "\n").encode()
                        self.wfile.write(f"{len(line):X}\r\n".encode() + line + b"\r\n")
                        self.wfile.flush()
                    application.stream_to(payload, emit)
                    self.wfile.write(b"0\r\n\r\n")
                    return
                body, status = application.handle_json({**payload, **({"action": "conversation.list"} if self.path == "/conversations" and payload.get("action") == "list" else {"action": "conversation.load"} if self.path == "/conversations" else {})})
            except (ValueError, json.JSONDecodeError):
                body, status = {"code": "REQUEST_INVALID"}, 400
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body, ensure_ascii=False).encode())

        def log_message(self, format: str, *args: Any) -> None:
            return

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
