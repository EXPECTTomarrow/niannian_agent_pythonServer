from datetime import datetime

from niannian_agent.skills import SkillRegistry
from niannian_agent.runtime_skills import register_runtime_tools
from niannian_agent.date_skill import register_date_skill


def test_runtime_clock_reports_a_timezone_aware_current_time():
    registry = SkillRegistry()
    register_runtime_tools(registry, now=lambda: datetime(2026, 8, 13, 19, 20))

    result = registry.get("time.now").handler({"timezone": "Asia/Shanghai"}, None)

    assert result == {"status": "ok", "timezone": "Asia/Shanghai", "iso": "2026-08-13T19:20:00+08:00"}
    assert "当前时间" in registry.capability_statement()


def test_date_skill_normalizes_common_unambiguous_formats():
    registry = SkillRegistry()
    register_date_skill(registry)

    result = registry.get("date.parse").handler({"value": "1993年4月11日"}, None)

    assert result == {
        "status": "resolved",
        "value": "1993-04-11",
        "source": "1993年4月11日",
        "confidence": "explicit",
    }


def test_date_skill_returns_choices_for_region_or_two_digit_ambiguity():
    registry = SkillRegistry()
    register_date_skill(registry)

    result = registry.get("date.parse").handler({"value": "4/11/93"}, None)

    assert result["status"] == "ambiguous"
    assert result["source"] == "4/11/93"
    assert {item["value"] for item in result["candidates"]} == {
        "1993-04-11",
        "1993-11-04",
        "2093-04-11",
        "2093-11-04",
    }
    assert result["requiresConfirmation"] is True


def test_date_skill_does_not_guess_century_for_11_22_89():
    registry = SkillRegistry()
    register_date_skill(registry)

    result = registry.get("date.parse").handler({"value": "11/22/89"}, None)

    assert result["status"] == "ambiguous"
    assert result["reason"] == "two_digit_year_requires_confirmation"
    assert result["requiresConfirmation"] is True


def test_date_skill_supports_excel_serial_dates_without_contact_specific_logic():
    registry = SkillRegistry()
    register_date_skill(registry)

    result = registry.get("date.parse").handler({"value": 34477}, None)

    assert result["status"] == "resolved"
    assert result["value"] == "1994-05-23"
    assert result["source"] == "34477"


def test_date_skill_explains_invalid_dates():
    registry = SkillRegistry()
    register_date_skill(registry)

    result = registry.get("date.parse").handler({"value": "2024-02-31"}, None)

    assert result["status"] == "invalid"
    assert result["reason"] == "invalid_calendar_date"
    assert result["suggestion"]
