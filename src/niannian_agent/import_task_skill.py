from typing import Any

from .birthdae import BirthdaeToolGatewayClient
from .skills import SkillRegistry, Tool


def import_task_skill(client: BirthdaeToolGatewayClient, actor_token: str) -> SkillRegistry:
    """Expose only revision-checked import-task operations to the planning model."""
    registry = SkillRegistry()
    registry.declare_capability(
        "联系人导入",
        ["查看导入进度", "处理重复联系人", "补充或修正待确认信息", "提交已确认的联系人"],
        "仅处理当前用户拥有的导入任务",
        "重复、歧义和正式导入均需用户确认",
    )

    def get_task(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        task_id = str(arguments.get("taskId", "")).strip()
        if not task_id:
            raise ValueError("IMPORT_TASK_ARGUMENTS_REQUIRED")
        return client.execute("import.get_task", {"taskId": task_id}, actor_token, request_id)

    def resolve_duplicate(arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        payload = {
            "taskId": str(arguments.get("taskId", "")).strip(),
            "expectedRevision": int(arguments.get("expectedRevision", 0) or 0),
            "operationId": str(arguments.get("operationId", "")).strip(),
            "rowId": str(arguments.get("rowId", "")).strip(),
            "decision": str(arguments.get("decision", "")).strip(),
        }
        if not all((payload["taskId"], payload["expectedRevision"], payload["operationId"], payload["rowId"])):
            raise ValueError("IMPORT_TASK_ARGUMENTS_REQUIRED")
        if payload["decision"] not in {"skip", "add", "update"}:
            raise ValueError("IMPORT_DUPLICATE_DECISION_REQUIRED")
        return client.execute("import.resolve_duplicate", payload, actor_token, request_id)

    def mutate_rows(tool_name: str, action: str, arguments: dict[str, Any], state: Any) -> dict[str, Any]:
        request_id = state.timeline[-1].get("requestId", "") if state.timeline else ""
        payload = {
            "taskId": str(arguments.get("taskId", "")).strip(),
            "expectedRevision": int(arguments.get("expectedRevision", 0) or 0),
            "operationId": str(arguments.get("operationId", "")).strip(),
            "rowIds": [str(value).strip() for value in arguments.get("rowIds", []) if str(value).strip()],
        }
        if not all((payload["taskId"], payload["expectedRevision"], payload["operationId"])) or not payload["rowIds"]:
            raise ValueError("IMPORT_TASK_ARGUMENTS_REQUIRED")
        if action == "resolve_duplicate_batch":
            payload["decision"] = str(arguments.get("decision", "")).strip()
            if payload["decision"] not in {"skip", "update"}:
                raise ValueError("IMPORT_DUPLICATE_DECISION_REQUIRED")
        return client.execute(tool_name, payload, actor_token, request_id)

    registry.register(Tool(
        "import.get_task",
        "Read the latest server-side snapshot for one current contact import task. Use this before advising on its unresolved items or after a revision conflict.",
        get_task,
        parameters={"type": "object", "properties": {"taskId": {"type": "string"}}, "required": ["taskId"]},
    ))
    registry.register(Tool(
        "import.remove_rows",
        "Remove one or more user-selected rows from the current import task. This only changes the review task, never saved contacts.",
        lambda arguments, state: mutate_rows("import.remove_rows", "remove_rows", arguments, state),
        parameters={"type": "object", "properties": {"taskId": {"type": "string"}, "expectedRevision": {"type": "integer", "minimum": 1}, "operationId": {"type": "string"}, "rowIds": {"type": "array", "items": {"type": "string"}, "minItems": 1}}, "required": ["taskId", "expectedRevision", "operationId", "rowIds"]},
    ))
    registry.register(Tool(
        "import.resolve_duplicate_batch",
        "Apply an explicit user choice to multiple unambiguous duplicate rows in one server-side operation.",
        lambda arguments, state: mutate_rows("import.resolve_duplicate_batch", "resolve_duplicate_batch", arguments, state),
        parameters={"type": "object", "properties": {"taskId": {"type": "string"}, "expectedRevision": {"type": "integer", "minimum": 1}, "operationId": {"type": "string"}, "rowIds": {"type": "array", "items": {"type": "string"}, "minItems": 1}, "decision": {"type": "string", "enum": ["skip", "update"]}}, "required": ["taskId", "expectedRevision", "operationId", "rowIds", "decision"]},
    ))
    registry.register(Tool(
        "import.resolve_duplicate",
        "Resolve exactly one pending duplicate contact in the current import task. Use only after the user explicitly chooses whether to keep the existing contact, import another contact, or update it.",
        resolve_duplicate,
        parameters={"type": "object", "properties": {
            "taskId": {"type": "string"}, "expectedRevision": {"type": "integer", "minimum": 1},
            "operationId": {"type": "string"}, "rowId": {"type": "string"},
            "decision": {"type": "string", "enum": ["skip", "add", "update"]},
        }, "required": ["taskId", "expectedRevision", "operationId", "rowId", "decision"]},
    ))
    return registry
