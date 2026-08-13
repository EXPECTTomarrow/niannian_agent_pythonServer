from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .skills import SkillRegistry, Tool


def register_runtime_tools(registry: SkillRegistry, now: Callable[[], datetime] = datetime.now) -> SkillRegistry:
    """Register deterministic, non-business runtime capabilities available to every agent."""
    registry.declare_capability(
        "当前时间",
        ["获取当前日期、时间和时区"],
        "仅使用服务运行时的可信系统时钟",
    )

    def current_time(arguments: dict[str, Any], _: Any) -> dict[str, Any]:
        timezone = str(arguments.get("timezone") or "Asia/Shanghai")
        try:
            zone = ZoneInfo(timezone)
        except Exception as exc:
            raise ValueError("TIMEZONE_INVALID") from exc
        value = now()
        value = value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)
        return {"status": "ok", "timezone": timezone, "iso": value.isoformat()}

    registry.register(Tool(
        "time.now",
        "Get the current date and time in an IANA timezone. Use this for questions about today, now, relative dates, or date ranges; never ask the user for the current date when this tool is available.",
        current_time,
        parameters={"type": "object", "properties": {"timezone": {"type": "string", "default": "Asia/Shanghai"}}},
    ))
    return registry
