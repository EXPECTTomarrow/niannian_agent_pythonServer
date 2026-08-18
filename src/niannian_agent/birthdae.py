import json
from typing import Any, Optional

import httpx

from .skills import SkillRegistry, Tool


class BirthdaeToolGatewayClient:
    """Client for the cloud-side gateway; it never accesses WeChat data directly."""

    def __init__(self, base_url: str, http_client: Optional[httpx.Client] = None) -> None:
        if not base_url:
            raise ValueError("BIRTHDAE_AGENT_TOOL_URL is required")
        self.base_url = base_url
        self.http = http_client or httpx.Client(timeout=15, transport=httpx.HTTPTransport(retries=2))

    def execute(self, tool: str, arguments: dict[str, Any], actor_token: str, request_id: str = "") -> dict[str, Any]:
        if not actor_token:
            raise ValueError("actor_token is required")
        safe_arguments = {key: value for key, value in arguments.items() if key in ("name", "contactId", "city", "missingField", "limit", "scope", "refs", "days", "taskId", "rowId", "rowIds", "decision", "changes", "expectedRevision", "operationId")}
        print(json.dumps({"event": "tool.request", "requestId": request_id, "tool": tool, "arguments": safe_arguments}, ensure_ascii=False), flush=True)
        response = self.http.post(self.base_url, json={
            "tool": tool,
            "arguments": arguments,
            "actorToken": actor_token,
            "requestId": request_id,
        })
        response_summary = response.text[:500] if response.status_code >= 400 else ""
        print(json.dumps({"event": "tool.response", "requestId": request_id, "tool": tool, "httpStatus": response.status_code, "error": response_summary}, ensure_ascii=False), flush=True)
        response.raise_for_status()
        body = response.json()
        if body.get("success") is not True:
            raise RuntimeError(body.get("code", "BIRTHDAE_TOOL_ERROR"))
        result = body["data"]
        print(json.dumps({"event": "tool.observation", "requestId": request_id, "tool": tool, "status": result.get("status"), "count": len(result.get("contacts", []))}, ensure_ascii=False), flush=True)
        return result

    def load_conversation(self, session_id: str, actor_token: str) -> dict[str, Any]:
        return self.execute("conversation.load", {"sessionId": session_id}, actor_token)

    def commit_conversation(self, session_id: str, revision: int, state: dict[str, Any], events: list[dict[str, Any]], actor_token: str) -> dict[str, Any]:
        return self.execute("conversation.commit", {"sessionId": session_id, "revision": revision, "state": state, "events": events}, actor_token)

    def list_conversations(self, actor_token: str) -> dict[str, Any]:
        return self.execute("conversation.list", {}, actor_token)


def birthdae_contact_skill(client: BirthdaeToolGatewayClient, actor_token: str) -> SkillRegistry:
    registry = SkillRegistry()
    registry.declare_capability(
        "联系人资料",
        ["查询、筛选和统计联系人", "查看完整资料", "准备新增、修改和删除", "整理批量导入内容"],
        "仅处理当前用户已授权的个人和组织通讯录",
        "新增、修改、删除和导入都会先展示内容，待用户确认后才会执行",
    )

    def search(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        result = client.execute("contact.search", {"name": arguments.get("name", "")}, actor_token, request_id)
        contacts = result.get("contacts", [])
        if result.get("status") == "ok" and contacts:
            state.subject_contact = {**contacts[0].get("ref", {}), "name": contacts[0].get("name", "")}
        elif result.get("status") == "ambiguous":
            state.subject_contact = None
        return result

    def details(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        contact_id = arguments.get("contactId") or (state.subject_contact or {}).get("id", "")
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        result = client.execute("contact.details", {"contactId": contact_id}, actor_token, request_id)
        contact = result.get("contact")
        if result.get("status") == "ok" and contact:
            state.subject_contact = {**contact["ref"], "name": contact.get("name", "")}
        return result

    def select(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        return details({"contactId": arguments.get("contactId", "")}, state)

    def list_contacts(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        payload = {"city": arguments.get("city", ""), "limit": arguments.get("limit", 20)}
        if arguments.get("scope"):
            payload["scope"] = arguments["scope"]
        if arguments.get("missingField"):
            payload["missingField"] = arguments["missingField"]
        return client.execute("contact.list", payload, actor_token, request_id)

    def query_contacts(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        return client.execute("contact.query", {"scope": arguments.get("scope", ""), "filter": arguments.get("filter", {}), "page": arguments.get("page", {})}, actor_token, request_id)

    def upcoming_birthdays(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        return client.execute("contact.birthdays", {"scope": arguments.get("scope", "all"), "days": arguments.get("days", 30)}, actor_token, request_id)

    def batch_details(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        return client.execute("contact.batch_details", {"refs": arguments.get("refs", [])}, actor_token, request_id)

    def list_organizations(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        return client.execute("organization.list", {}, actor_token, request_id)

    def list_addressbooks(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        return client.execute("addressbook.list", {}, actor_token, request_id)

    def addressbook_stats(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        return client.execute("addressbook.stats", {}, actor_token, request_id)

    def resolve_organization(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        return client.execute("organization.resolve", {"name": arguments.get("name", "")}, actor_token, request_id)

    def verified_subject(state: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        subject = state.subject_contact if isinstance(state.subject_contact, dict) else {}
        if not subject.get("id") or not subject.get("name"):
            raise ValueError("CONTACT_TARGET_REQUIRED")
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        verified = client.execute("contact.details", {"contactId": subject["id"]}, actor_token, request_id)
        if verified.get("status") != "ok" or not isinstance(verified.get("contact"), dict):
            raise ValueError("CONTACT_TARGET_NOT_FOUND")
        contact = verified["contact"]
        state.subject_contact = {**contact.get("ref", {}), "name": contact.get("name", subject["name"])}
        return state.subject_contact, contact

    def propose_update(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        field = str(arguments.get("field", "")).strip()
        value = str(arguments.get("value", "")).strip()
        if field not in {"name", "gender", "relation", "importance", "phone", "address", "company", "interests", "skills", "dislikes", "education", "relationNote", "giftNote", "note", "birthday"} or not value:
            raise ValueError("CONTACT_CHANGE_INVALID")
        subject, contact = verified_subject(state)
        pending = state.pending_mutation if isinstance(state.pending_mutation, dict) else {}
        same_target = pending.get("action") == "update" and pending.get("target", {}).get("id") == subject["id"]
        previous_changes = pending.get("changeSet", {}) if same_target and isinstance(pending.get("changeSet"), dict) else {}
        changes = {**previous_changes, field: value}
        base = pending.get("before", contact) if same_target and isinstance(pending.get("before"), dict) else contact
        after = {**base, **changes}
        step = {
            "tool": "propose_contact_mutation", "action": "update", "requiresConfirmation": True,
            "target": {"id": subject["id"], "name": subject["name"], "scope": subject.get("scope", "personal")},
            "changes": {"field": field, "value": value},
            "changeSet": changes,
            "before": base, "after": after,
        }
        state.pending_mutation = step
        return {"status": "confirmation_required", "plan": {"intent": "contact_agent", "reply": "我已整理好修改内容，请确认后执行。", "steps": [step]}}

    def normalize_contact(value: Any) -> tuple[dict[str, Any], list[str]]:
        source = value if isinstance(value, dict) else {}
        contact = {key: str(source.get(key, "")).strip() for key in ("name", "relation", "phone", "address", "company", "interests", "skills", "dislikes", "education", "relationNote", "giftNote", "note")}
        gender = str(source.get("gender", "")).strip()
        contact["gender"] = "male" if gender in {"男", "male"} else "female" if gender in {"女", "female"} else ""
        contact["importance"] = "important" if str(source.get("importance", "")).strip() in {"important", "特别关注"} else ""
        for key in ("birthdayYear", "birthdayMonth", "birthdayDay"):
            value = source.get(key)
            contact[key] = int(value) if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()) else None
        contact["birthdayType"] = "农历" if source.get("birthdayType") == "农历" else "公历"
        contact["birthdayKnownYear"] = bool(contact["birthdayYear"])
        contact["birthdayLeap"] = bool(source.get("birthdayLeap"))
        errors = []
        if not contact["name"]: errors.append("请补充联系人姓名")
        if contact["phone"] and not __import__("re").fullmatch(r"1[3-9]\d{9}", contact["phone"].replace(" ", "").replace("-", "")):
            errors.append("手机号应为 11 位有效手机号")
        return contact, errors

    def propose_create(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        contact, errors = normalize_contact(arguments.get("contact"))
        if errors:
            return {"status": "input_required", "message": "；".join(errors), "draft": contact}
        scope = str(arguments.get("scope", "personal")).strip() or "personal"
        return {"status": "form_draft", "draft": contact, "scope": scope,
                "message": "我已整理好联系人资料，请补充卡片中尚未填写的信息并确认添加。"}

    def propose_delete(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        subject, contact = verified_subject(state)
        step = {
            "tool": "propose_contact_mutation", "action": "delete", "requiresConfirmation": True,
            "target": {"id": subject["id"], "name": subject["name"], "scope": subject.get("scope", "personal")},
            "before": contact,
        }
        return {"status": "confirmation_required", "plan": {"intent": "contact_agent", "reply": "删除后无法恢复，请确认是否删除该联系人。", "steps": [step]}}

    registry.register(Tool("contact.search", "Search authorized contacts by name before selecting one", search))
    registry.register(Tool("contact.details", "Read the authorized details of the selected contact", details))
    registry.register(Tool("contact.select", "Select one contact candidate by its id after an ambiguity clarification, then read its authorized details", select, parameters={"type": "object", "properties": {"contactId": {"type": "string"}}, "required": ["contactId"]}))
    registry.register(Tool("contact.list", "List authorized contacts in personal, all, or one resolved organization scope. Filter by a declared missing field when needed. Use total for counts, never the visible contacts array length.", list_contacts, parameters={"type": "object", "properties": {"scope": {"type": "string"}, "city": {"type": "string"}, "missingField": {"type": "string", "enum": ["address", "phone", "company", "birthday", "relation"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}}))
    registry.register(Tool("contact.query", "Query authorized contacts using a structured scope, filter, and page. Use this for all filtered contact questions and counts. Supported filter fields: city and missing (address, phone, company, birthday, relation).", query_contacts, parameters={"type": "object", "properties": {"scope": {"type": "string"}, "filter": {"type": "object", "properties": {"city": {"type": "string"}, "missing": {"type": "array", "items": {"type": "string", "enum": ["address", "phone", "company", "birthday", "relation"]}, "maxItems": 1}}}, "page": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}}}, "required": ["filter"]}))
    registry.register(Tool("contact.birthdays", "Query and sort upcoming birthdays across an authorized scope in one operation. Use this for birthday date ranges; do not list all contacts or calculate dates yourself.", upcoming_birthdays, parameters={"type": "object", "properties": {"scope": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": 365}}, "required": ["days"]}))
    registry.register(Tool("contact.batch_details", "Read complete authorized details for explicitly selected contact references. Use this for multiple people rather than emitting internal calls or guessing IDs.", batch_details, parameters={"type": "object", "properties": {"refs": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "properties": {"id": {"type": "string"}, "scope": {"type": "string"}}, "required": ["id", "scope"]}}}, "required": ["refs"]}))
    registry.register(Tool("organization.list", "List every organization the current user is authorized to access", list_organizations, parameters={"type": "object", "properties": {}}))
    registry.register(Tool("addressbook.list", "List every address book available to the current user, including the personal address book and authorized organization address books.", list_addressbooks, parameters={"type": "object", "properties": {}}))
    registry.register(Tool("addressbook.stats", "Return exact contact totals for the personal address book and every authorized organization in one operation. Use this for per-address-book or per-organization counts; do not query each organization separately.", addressbook_stats, parameters={"type": "object", "properties": {}}))
    registry.register(Tool("organization.resolve", "Resolve a user-mentioned organization name to exactly one organization the user can access before organization-specific questions.", resolve_organization, parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}))
    registry.register(Tool("contact.propose_update", "Propose one update to the current selected contact. This never writes data and always requires user confirmation.", propose_update, requires_confirmation=True, parameters={"type": "object", "properties": {"field": {"type": "string", "enum": ["name", "gender", "relation", "importance", "phone", "address", "company", "interests", "skills", "dislikes", "education", "relationNote", "giftNote", "note", "birthday"]}, "value": {"type": "string"}}, "required": ["field", "value"]}))
    create_parameters = {
        "type": "object",
        "properties": {
            "scope": {"type": "string"},
            "contact": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"}, "gender": {"type": "string"}, "relation": {"type": "string"},
                    "phone": {"type": "string"}, "address": {"type": "string"}, "company": {"type": "string"},
                    "interests": {"type": "string"}, "birthdayType": {"type": "string"},
                    "birthdayYear": {"type": "integer"}, "birthdayMonth": {"type": "integer"}, "birthdayDay": {"type": "integer"},
                },
            },
        },
        "required": ["contact"],
    }
    registry.register(Tool("contact.propose_create", "Prepare a contact creation form from the user-provided facts. Validate supplied fields, return a form draft, and ask only for invalid or required missing information. This never writes data.", propose_create, parameters=create_parameters))
    registry.register(Tool("contact.propose_delete", "Propose deleting the current selected contact. This never writes data and always requires user confirmation.", propose_delete, requires_confirmation=True, parameters={"type": "object", "properties": {}}))
    return registry
