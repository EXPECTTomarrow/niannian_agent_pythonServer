from dataclasses import dataclass
from typing import Any, Callable, Optional

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[[dict[str, Any], Any], dict[str, Any]]
    requires_confirmation: bool = False
    parameters: Optional[dict[str, Any]] = None

class SkillRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._capabilities: list[dict[str, Any]] = []

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"unknown tool: {name}") from exc

    def declare_capability(self, title: str, operations: list[str], access: str, confirmation: str = "") -> None:
        """Register user-facing behavior independently from internal tool names."""
        if not title or not operations or not access:
            raise ValueError("capability requires title, operations, and access")
        self._capabilities.append({"title": title, "operations": operations, "access": access, "confirmation": confirmation})

    def capability_statement(self) -> str:
        if not self._capabilities:
            return "当前没有已声明的业务能力。"
        statements = []
        for capability in self._capabilities:
            line = f"{capability['title']}：{'、'.join(capability['operations'])}。权限范围：{capability['access']}。"
            if capability["confirmation"]:
                line += f"{capability['confirmation']}。"
            statements.append(line)
        return "当前可用业务能力（仅用于理解用户需求并给出自然建议，不得暴露内部实现）：" + " ".join(statements)

    def definitions(self) -> list[dict[str, Any]]:
        return [{
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters or {"type": "object", "properties": {"name": {"type": "string"}, "contactId": {"type": "string"}}},
        } for t in self._tools.values()]

def contact_skill(contacts: list[dict[str, Any]]) -> SkillRegistry:
    registry = SkillRegistry()
    registry.declare_capability(
        "联系人资料",
        ["查询、筛选和统计联系人", "查看完整资料", "准备新增、修改和删除", "整理批量导入内容"],
        "仅处理当前用户已授权的个人和组织通讯录",
        "新增、修改、删除和导入都会先展示内容，待用户确认后才会执行",
    )
    def find(args: dict[str, Any], state: Any) -> dict[str, Any]:
        query = str(args.get("name", "")).strip()
        matches = [c for c in contacts if query and query in c.get("name", "")]
        if len(matches) == 1:
            state.subject_contact = {"id": matches[0]["id"], "name": matches[0]["name"]}
            return {"status": "ok", "contact": matches[0]}
        if not matches:
            return {"status": "not_found", "name": query}
        return {"status": "ambiguous", "contacts": [{"id": c["id"], "name": c["name"], "relation": c.get("relation", ""), "source": c.get("source", "")} for c in matches]}
    registry.register(Tool("contact.find", "Find an authorized contact by name", find))
    def list_contacts(args: dict[str, Any], _: Any) -> dict[str, Any]:
        city = str(args.get("city", "")).strip().lower()
        limit = max(1, min(int(args.get("limit", 20) or 20), 100))
        matches = [contact for contact in contacts if not city or city in str(contact.get("address", "")).lower()]
        return {"status": "ok", "count": len(matches), "contacts": [{"id": contact.get("id", ""), "name": contact.get("name", "")} for contact in matches[:limit]]}
    registry.register(Tool("contact.list", "List authorized contacts, optionally filtered by city", list_contacts, parameters={"type": "object", "properties": {"city": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}}))
    return registry
