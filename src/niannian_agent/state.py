from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class ConversationState:
    session_id: str
    user_id: str
    revision: int = 0
    timeline: list[dict[str, Any]] = field(default_factory=list)
    subject_contact: Optional[dict[str, Any]] = None
    pending_candidates: list[dict[str, Any]] = field(default_factory=list)
    goal: Optional[str] = None
    last_execution: Optional[dict[str, Any]] = None
    pending_mutation: Optional[dict[str, Any]] = None
    status: str = "idle"
    summary: str = ""

    def append(self, event_type: str, **data: Any) -> None:
        self.timeline.append({"type": event_type, **data})
        self.revision += 1

class InMemoryStateStore:
    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}

    def load(self, session_id: str, user_id: str) -> ConversationState:
        state = self._states.get(session_id)
        if state is None:
            state = ConversationState(session_id=session_id, user_id=user_id)
            self._states[session_id] = state
        if state.user_id != user_id:
            raise PermissionError("session does not belong to user")
        return deepcopy(state)

    def save(self, state: ConversationState, expected_revision: int) -> ConversationState:
        current = self._states.get(state.session_id)
        if current and current.revision != expected_revision:
            raise RuntimeError("stale conversation revision")
        saved = deepcopy(state)
        self._states[state.session_id] = saved
        return deepcopy(saved)


class PersistentStateStore:
    """Adapter that keeps the runtime independent from CloudBase transport details."""

    def __init__(self, client: Any, actor_token: str) -> None:
        self.client = client
        self.actor_token = actor_token
        self._remote_revision: dict[str, int] = {}
        self._event_offsets: dict[str, int] = {}

    def load(self, session_id: str, user_id: str) -> ConversationState:
        payload = self.client.load_conversation(session_id, self.actor_token)
        state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        self._remote_revision[session_id] = int(payload.get("revision", 0) or 0)
        subject = state.get("subjectContact") if isinstance(state.get("subjectContact"), dict) else None
        candidates = state.get("workItems", {}).get("pendingCandidates", []) if isinstance(state.get("workItems"), dict) else []
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        self._event_offsets[session_id] = len(events[-20:])
        task = state.get("task") if isinstance(state.get("task"), dict) else {}
        pending_mutation = state.get("workItems", {}).get("pendingMutation") if isinstance(state.get("workItems"), dict) else None
        return ConversationState(
            session_id=session_id, user_id=user_id, revision=self._remote_revision[session_id],
            timeline=[item for item in events[-20:] if isinstance(item, dict)], subject_contact=subject,
            pending_candidates=[item for item in candidates if isinstance(item, dict)][:10],
            goal=task.get("goal") if isinstance(task.get("goal"), str) else None,
            status=task.get("status") if isinstance(task.get("status"), str) and task.get("status") else "idle",
            summary=state.get("summary") if isinstance(state.get("summary"), str) else "",
            pending_mutation=pending_mutation if isinstance(pending_mutation, dict) else None,
        )

    def save(self, state: ConversationState, expected_revision: int) -> ConversationState:
        remote_revision = self._remote_revision.get(state.session_id, 0)
        if expected_revision != remote_revision:
            raise RuntimeError("stale conversation revision")
        offset = self._event_offsets.get(state.session_id, 0)
        events = state.timeline[offset:]
        recent = state.timeline[-20:]
        dropped = state.timeline[:-20]
        summary = state.summary[-4000:]
        if dropped:
            compressed = "；".join(str(item.get("content", "")).strip()[:200] for item in dropped if isinstance(item, dict) and item.get("content"))
            if compressed:
                summary = (summary + "\n历史事件摘要: " + compressed)[-4000:]
        projection = {
            "subjectContact": state.subject_contact,
            "task": {"domain": "", "goal": state.goal or "", "status": state.status},
            "workItems": {"pendingCandidates": state.pending_candidates[:10], "pendingMutation": state.pending_mutation}, "facts": [], "summary": summary,
        }
        saved = self.client.commit_conversation(state.session_id, remote_revision, projection, events, self.actor_token)
        self._remote_revision[state.session_id] = int(saved.get("revision", remote_revision + 1))
        self._event_offsets[state.session_id] = len(recent)
        return deepcopy(state)
