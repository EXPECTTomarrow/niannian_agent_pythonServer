"""Deterministic date interpretation for agent workflows.

The model may explain dates, but this skill owns parsing and ambiguity. It never
silently chooses a locale or century when the source does not provide one.
"""

from datetime import date, timedelta
import re
from typing import Any

from .skills import SkillRegistry, Tool


def register_date_skill(registry: SkillRegistry) -> SkillRegistry:
    registry.declare_capability("日期理解", ["识别和规范化常见日期", "提示有歧义的日期并提供候选解释"], "仅根据用户提供的原始日期和明确上下文处理", "无法唯一确定时会请用户确认，不会擅自猜测")
    registry.register(Tool(
        "date.parse",
        "Parse a date value deterministically. Return resolved, ambiguous, or invalid; never guess a locale or century.",
        parse_date,
        parameters={
            "type": "object",
            "properties": {
                "value": {"description": "Original date value from a document or user message"},
                "locale": {"type": "string", "enum": ["MDY", "DMY"]},
                "century": {"type": "integer", "minimum": 1900, "maximum": 2100},
            },
            "required": ["value"],
        },
    ))
    return registry


def parse_date(arguments: dict[str, Any], _: Any) -> dict[str, Any]:
    raw = arguments.get("value")
    source = str(raw).strip()
    if not source:
        return {"status": "invalid", "reason": "empty_value", "suggestion": "请提供日期原文。", "source": source}

    if isinstance(raw, (int, float)) and float(raw).is_integer() and 1 <= int(raw) <= 100000:
        parsed = date(1899, 12, 30) + timedelta(days=int(raw))
        return _resolved(parsed, source, "excel_serial")

    text = re.sub(r"\s+", "", source)
    chinese = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", text)
    if chinese:
        return _calendar_result(int(chinese[1]), int(chinese[2]), int(chinese[3]), source, "explicit")

    full = re.fullmatch(r"(\d{4})[\-/\.](\d{1,2})[\-/\.](\d{1,2})", text)
    if full:
        return _calendar_result(int(full[1]), int(full[2]), int(full[3]), source, "explicit")

    parts = re.fullmatch(r"(\d{1,2})[\-/\.](\d{1,2})[\-/\.](\d{2}|\d{4})", text)
    if parts:
        first = int(parts[1])
        second = int(parts[2])
        year_source = parts[3]
        year_text = int(year_source)
        locale = str(arguments.get("locale", "")).upper()
        century = arguments.get("century")
        if len(year_source) == 2:
            if century is None:
                return _ambiguous_short_year(first, second, year_text, source)
            year = int(century) + year_text
        else:
            year = year_text
        candidates = []
        for order in ([locale] if locale in {"MDY", "DMY"} else ["MDY", "DMY"]):
            month, day = (first, second) if order == "MDY" else (second, first)
            result = _calendar_result(year, month, day, source, "explicit")
            if result["status"] == "resolved":
                candidates.append((order, result["value"]))
        unique = list(dict.fromkeys(value for _, value in candidates))
        if len(unique) == 1:
            return _resolved(date.fromisoformat(unique[0]), source, "explicit")
        return {"status": "ambiguous", "source": source, "reason": "regional_date_order_requires_confirmation", "requiresConfirmation": True, "candidates": [{"value": value, "label": value, "description": f"按{order}顺序解释"} for order, value in candidates]}

    compact = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if compact:
        return _calendar_result(int(compact[1]), int(compact[2]), int(compact[3]), source, "explicit")
    return {"status": "invalid", "reason": "unrecognized_format", "suggestion": "可使用 YYYY-MM-DD、YYYY/MM/DD、YYYY年M月D日，或确认文件的地区日期规则。", "source": source}


def _ambiguous_short_year(first: int, second: int, short: int, source: str) -> dict[str, Any]:
    candidates = []
    for year in (1900 + short, 2000 + short):
        for order, month, day in (("MDY", first, second), ("DMY", second, first)):
            result = _calendar_result(year, month, day, source, "explicit")
            if result["status"] == "resolved":
                candidates.append({"value": result["value"], "label": result["value"], "description": f"按{order}顺序且采用{year // 100}世纪解释"})
    return {"status": "ambiguous", "source": source, "reason": "two_digit_year_requires_confirmation", "requiresConfirmation": True, "candidates": list({item["value"]: item for item in candidates}.values())}


def _calendar_result(year: int, month: int, day: int, source: str, confidence: str) -> dict[str, Any]:
    try:
        return _resolved(date(year, month, day), source, confidence)
    except ValueError:
        return {"status": "invalid", "reason": "invalid_calendar_date", "suggestion": "请确认月份和日期是否真实存在。", "source": source}


def _resolved(value: date, source: str, confidence: str) -> dict[str, Any]:
    return {"status": "resolved", "value": value.isoformat(), "source": source, "confidence": confidence}
