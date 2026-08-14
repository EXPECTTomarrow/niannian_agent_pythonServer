import hashlib
import json
import re
from typing import Any, Callable, Optional


MAX_WORK_ITEMS = 100
MAX_DECISIONS = 100
MAX_COMPLETED_OPERATIONS = 200


def reconcile_import_task(
    current: Optional[dict[str, Any]],
    import_summary: dict[str, Any],
    artifact: Optional[dict[str, Any]],
    parse_date: Callable[[dict[str, Any], Any], dict[str, Any]],
) -> dict[str, Any]:
    artifact_id = _text((artifact or {}).get("id"), 120) or "import-draft"
    revision = max(0, int((artifact or {}).get("revision", 0) or 0))
    previous = current if isinstance(current, dict) and current.get("domain") == "contact_import" and current.get("artifact", {}).get("id") == artifact_id else {}
    previous_items = {item.get("id"): item for item in previous.get("workItems", []) if isinstance(item, dict) and item.get("id")}
    decisions = [item for item in previous.get("decisions", []) if isinstance(item, dict)][-MAX_DECISIONS:]
    decided_ids = {item.get("workItemId") for item in decisions if item.get("workItemId")}
    work_items = []

    rows = import_summary.get("rows") if isinstance(import_summary, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or _birthday_is_resolved(row):
            continue
        raw = _raw_birthday(row)
        if not raw:
            continue
        parsed = parse_date({"value": raw}, None)
        if parsed.get("status") != "ambiguous":
            continue
        source_row = int(row.get("sourceRow", 0) or 0)
        item_id = f"row-{source_row}:birthday"
        options = []
        for candidate in parsed.get("candidates", []):
            value = _text(candidate.get("value"), 40)
            if not value:
                continue
            options.append({
                "id": f"date-{source_row}-{value}",
                "label": value,
                "description": _text(candidate.get("description"), 160),
                "steps": [{"tool": "mutate_import", "action": "update", "target": {"sourceRow": source_row}, "changes": {"field": "birthday", "value": value}}],
            })
        if len(options) < 2:
            continue
        old = previous_items.get(item_id, {})
        status = "awaiting_apply" if item_id in decided_ids or old.get("status") == "awaiting_apply" else "pending"
        work_items.append({
            "id": item_id, "kind": "date_ambiguity", "status": status,
            "sourceRow": source_row, "subjectName": _text(row.get("name"), 100) or f"第{source_row}行",
            "rawValue": _text(raw, 160), "options": options[:8],
        })
        if len(work_items) >= MAX_WORK_ITEMS:
            break

    pending_ids = [item["id"] for item in work_items if item.get("status") == "pending"]
    old_focus = previous.get("focusedWorkItemId")
    focused = old_focus if old_focus in pending_ids else (pending_ids[0] if pending_ids else "")
    acknowledged = (artifact or {}).get("completedOperationIds", [])
    acknowledged_ids = [str(item) for item in acknowledged if item] if isinstance(acknowledged, list) else []
    completed = list(dict.fromkeys([
        *[str(item) for item in previous.get("completedOperationIds", []) if item],
        *acknowledged_ids,
    ]))[-MAX_COMPLETED_OPERATIONS:]
    status = "waiting_user" if pending_ids else ("waiting_apply" if work_items else "completed")
    return {
        "id": _text(previous.get("id"), 120) or f"task-{artifact_id}",
        "domain": "contact_import", "goal": "review_and_import", "status": status,
        "artifact": {"id": artifact_id, "revision": revision, "digest": _artifact_digest(import_summary)},
        "focusedWorkItemId": focused, "workItems": work_items,
        "decisions": decisions, "completedOperationIds": completed,
        "completionCriteria": {"allWorkItemsResolved": True},
    }


def resolve_task_choice(task: dict[str, Any], message: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    updated = json.loads(json.dumps(task, ensure_ascii=False))
    source = str(message or "").strip()
    pending = [item for item in updated.get("workItems", []) if item.get("status") == "pending"]
    if not pending or not source:
        return updated, None

    named = next((item for item in pending if item.get("subjectName") and str(item["subjectName"]) in source), None)
    row_match = re.search(r"第\s*(\d+)\s*(?:行|条|个)", source)
    row_number = int(row_match.group(1)) if row_match else None
    row_item = next((item for item in pending if row_number and int(item.get("sourceRow", 0)) == row_number), None)
    focused = named or row_item or next((item for item in pending if item.get("id") == updated.get("focusedWorkItemId")), None) or pending[0]
    updated["focusedWorkItemId"] = focused["id"]

    option = _selected_option(focused.get("options", []), source)
    if option is None:
        return updated, None
    operation_id = _operation_id(updated, focused["id"], option["id"])
    if operation_id in updated.get("completedOperationIds", []):
        previous = next((item for item in updated.get("decisions", []) if item.get("operationId") == operation_id), None)
        return updated, previous

    focused["status"] = "awaiting_apply"
    decision = {
        "workItemId": focused["id"], "optionId": option["id"], "label": option["label"],
        "steps": option["steps"], "operationId": operation_id,
        "expectedArtifactRevision": int(updated.get("artifact", {}).get("revision", 0) or 0),
    }
    updated["decisions"] = [*updated.get("decisions", []), decision][-MAX_DECISIONS:]
    remaining = [item for item in updated.get("workItems", []) if item.get("status") == "pending"]
    updated["focusedWorkItemId"] = remaining[0]["id"] if remaining else ""
    updated["status"] = "waiting_user" if remaining else "waiting_apply"
    return updated, decision


def focused_work_item(task: dict[str, Any]) -> Optional[dict[str, Any]]:
    focused_id = task.get("focusedWorkItemId") if isinstance(task, dict) else ""
    return next((item for item in task.get("workItems", []) if isinstance(item, dict) and item.get("id") == focused_id), None)


def _selected_option(options: list[dict[str, Any]], source: str) -> Optional[dict[str, Any]]:
    letter = re.search(r"(?:选择|选|用|采用)?\s*([A-Ha-h])(?:\b|$)", source)
    if letter:
        index = ord(letter.group(1).upper()) - ord("A")
        if 0 <= index < len(options):
            return options[index]
    normalized = source.casefold()
    return next((item for item in options if str(item.get("id", "")).casefold() in normalized or str(item.get("label", "")).casefold() in normalized), None)


def _operation_id(task: dict[str, Any], work_item_id: str, option_id: str) -> str:
    artifact = task.get("artifact", {})
    value = f"{task.get('id', '')}\0{artifact.get('id', '')}\0{artifact.get('revision', 0)}\0{work_item_id}\0{option_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _artifact_digest(summary: dict[str, Any]) -> str:
    encoded = json.dumps(summary if isinstance(summary, dict) else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _birthday_is_resolved(row: dict[str, Any]) -> bool:
    return row.get("birthdayKnownYear") is True and bool(row.get("birthdayYear")) and bool(row.get("birthdayMonth")) and bool(row.get("birthdayDay"))


def _raw_birthday(row: dict[str, Any]) -> str:
    if row.get("rawBirthday") not in (None, ""):
        return str(row["rawBirthday"])
    raw = row.get("rawValues") if isinstance(row.get("rawValues"), dict) else {}
    return str(next((raw.get(key) for key in ("生日", "出生日期", "出生年月", "公历生日", "农历生日") if raw.get(key) not in (None, "")), ""))


def _text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]
