from datetime import datetime

from niannian_agent.skills import SkillRegistry
from niannian_agent.runtime_skills import register_runtime_tools


def test_runtime_clock_reports_a_timezone_aware_current_time():
    registry = SkillRegistry()
    register_runtime_tools(registry, now=lambda: datetime(2026, 8, 13, 19, 20))

    result = registry.get("time.now").handler({"timezone": "Asia/Shanghai"}, None)

    assert result == {"status": "ok", "timezone": "Asia/Shanghai", "iso": "2026-08-13T19:20:00+08:00"}
    assert "当前时间" in registry.capability_statement()
