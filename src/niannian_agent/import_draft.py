from typing import Any

from .skills import SkillRegistry, Tool
from .date_skill import register_date_skill


def import_draft_skill() -> SkillRegistry:
    """Tools that produce plans for the client-side import draft only."""
    registry = SkillRegistry()
    register_date_skill(registry)

    def compare(arguments: dict[str, Any], _: Any) -> dict[str, Any]:
        return {
            "tool": "compare_import",
            "leftSourceRow": int(arguments.get("leftSourceRow", 0)),
            "rightSourceRow": int(arguments.get("rightSourceRow", 0)),
        }

    def filter_rows(arguments: dict[str, Any], _: Any) -> dict[str, Any]:
        return {"tool": "filter_import", "filter": _filter(arguments.get("filter"))}

    def mutate(arguments: dict[str, Any], _: Any) -> dict[str, Any]:
        action = arguments.get("action")
        if action == "delete":
            return {"tool": "mutate_import", "action": "delete", "filter": _filter(arguments.get("filter"))}
        if action == "update":
            target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
            changes = arguments.get("changes") if isinstance(arguments.get("changes"), dict) else {}
            return {"tool": "mutate_import", "action": "update", "target": _target(target), "changes": {"field": str(changes.get("field", "")), "value": str(changes.get("value", ""))}}
        if action == "resolve_duplicate":
            decision = str(arguments.get("decision", "")).strip()
            if decision not in {"skip", "add"}:
                raise ValueError("IMPORT_DUPLICATE_DECISION_REQUIRED")
            return {"tool": "mutate_import", "action": "resolve_duplicate", "target": _target(arguments.get("target") if isinstance(arguments.get("target"), dict) else {}), "decision": decision}
        raise ValueError("IMPORT_ACTION_NOT_ALLOWED")

    def propose_choice(arguments: dict[str, Any], _: Any) -> dict[str, Any]:
        options = arguments.get("options") if isinstance(arguments.get("options"), list) else []
        safe_options = []
        for item in options[:5]:
            if not isinstance(item, dict):
                continue
            option_id = str(item.get("id", "")).strip()[:40]
            label = str(item.get("label", "")).strip()[:100]
            steps = item.get("steps") if isinstance(item.get("steps"), list) else []
            if not option_id or not label or not steps:
                continue
            safe_steps = []
            for step in steps[:20]:
                if not isinstance(step, dict) or step.get("tool") != "mutate_import" or step.get("action") != "update":
                    continue
                target = _target(step.get("target") if isinstance(step.get("target"), dict) else {})
                changes = step.get("changes") if isinstance(step.get("changes"), dict) else {}
                field = str(changes.get("field", "")).strip()
                value = str(changes.get("value", "")).strip()
                if field not in {"name", "birthday", "gender", "phone", "address", "company", "relation", "relationNote", "interests", "skills", "dislikes", "education", "giftNote", "note", "importance"} or not value:
                    continue
                safe_steps.append({"tool": "mutate_import", "action": "update", "target": target, "changes": {"field": field, "value": value}})
            if safe_steps:
                safe_options.append({"id": option_id, "label": label, "description": str(item.get("description", "")).strip()[:160], "steps": safe_steps})
        if len(safe_options) < 2:
            raise ValueError("IMPORT_CHOICES_REQUIRED")
        return {"status": "choice_required", "title": str(arguments.get("title", "请确认")).strip()[:80], "message": str(arguments.get("message", "请选择一种处理方式。")).strip()[:300], "options": safe_options}

    filter_schema = {"type": "object", "properties": {"filter": {"type": "object", "properties": {"sourceRow": {"type": "integer"}, "name": {"type": "string"}, "status": {"type": "string", "enum": ["ready", "invalid", "duplicate"]}}}}}
    registry.register(Tool("import.compare", "Compare two draft rows by source row number. Never writes contacts.", compare, parameters={"type": "object", "properties": {"leftSourceRow": {"type": "integer"}, "rightSourceRow": {"type": "integer"}}, "required": ["leftSourceRow", "rightSourceRow"]}))
    registry.register(Tool("import.filter", "Filter current draft rows by source row, exact name, or status. Never writes contacts.", filter_rows, parameters=filter_schema))
    registry.register(Tool("import.mutate", "Change only the current client-side import draft. Use delete with a filter, update with one target and one editable field, or resolve_duplicate with one duplicate row or target.all=true for every duplicate row and an explicit keep-existing or import-anyway decision. Never writes contacts.", mutate, parameters={"type": "object", "properties": {"action": {"type": "string", "enum": ["delete", "update", "resolve_duplicate"]}, "filter": filter_schema["properties"]["filter"], "target": {"type": "object", "properties": {"sourceRow": {"type": "integer"}, "name": {"type": "string"}, "all": {"type": "boolean"}}}, "decision": {"type": "string", "enum": ["skip", "add"]}, "changes": {"type": "object", "properties": {"field": {"type": "string", "enum": ["name", "birthday", "gender", "phone", "address", "company", "relation", "relationNote", "interests", "skills", "dislikes", "education", "giftNote", "note", "importance"]}, "value": {"type": "string"}}}}}))
    registry.register(Tool("import.propose_choice", "Propose two to five safe alternative draft changes when source data is ambiguous. Never mutates the draft. The user must choose one option before its plan is applied.", propose_choice, parameters={"type": "object", "properties": {"title": {"type": "string"}, "message": {"type": "string"}, "options": {"type": "array", "minItems": 2, "maxItems": 5, "items": {"type": "object", "properties": {"id": {"type": "string"}, "label": {"type": "string"}, "description": {"type": "string"}, "steps": {"type": "array"}}, "required": ["id", "label", "steps"]}}}, "required": ["title", "message", "options"]}))
    return registry


def _filter(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    result = {key: data[key] for key in ("sourceRow", "name", "status") if data.get(key) not in (None, "")}
    if not result:
        raise ValueError("IMPORT_TARGET_REQUIRED")
    return result


def _target(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("all") is True:
        return {"all": True}
    result = {key: value[key] for key in ("sourceRow", "name") if value.get(key) not in (None, "")}
    if not result:
        raise ValueError("IMPORT_TARGET_REQUIRED")
    return result
