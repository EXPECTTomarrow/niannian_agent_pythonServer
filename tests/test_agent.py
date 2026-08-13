from niannian_agent.agent import Agent
from niannian_agent.skills import contact_skill
from niannian_agent.state import InMemoryStateStore
from niannian_agent.config import Settings
from niannian_agent.import_draft import import_draft_skill

def test_skill_capability_declarations_are_available_to_the_agent_without_exposing_internal_tool_names():
    class CapabilityLLM:
        def chat(self, messages, tools):
            system = next(item["content"] for item in messages if item["role"] == "system")
            assert "联系人资料" in system
            assert "查询、筛选和统计联系人" in system
            assert "contact.search" not in system
            return {"content": "我可以帮你查询和整理联系人资料，也可以在你确认后准备新增、修改、删除或导入内容。"}

    result = Agent(CapabilityLLM(), contact_skill([]), InMemoryStateStore(), Settings(max_steps=1)).run("s-capabilities", "u1", "你能帮我做什么")
    assert result["status"] == "completed"

class FakeLLM:
    def __init__(self): self.calls = 0
    def chat(self, messages, tools):
        self.calls += 1
        if self.calls == 1: return {"tool_call": {"name": "contact.find", "arguments": {"name": "小王"}}}
        return {"content": "小王的生日是 1 月 2 日。"}

def test_agent_replans_after_observation_and_keeps_subject():
    store = InMemoryStateStore()
    agent = Agent(FakeLLM(), contact_skill([{"id": "c1", "name": "小王", "birthday": "1-2"}]), store, Settings(max_steps=3))
    result = agent.run("s1", "u1", "小王生日是什么时候")
    state = store.load("s1", "u1")
    assert result["status"] == "completed"
    assert state.subject_contact == {"id": "c1", "name": "小王"}
    assert len(state.timeline) == 3

def test_session_cannot_be_crossed_between_users():
    store = InMemoryStateStore()
    store.load("s1", "u1")
    try:
        store.load("s1", "u2")
        assert False
    except PermissionError:
        pass

def test_agent_returns_a_frontend_only_import_plan_without_writing_contacts():
    class ImportLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_call": {"name": "import.mutate", "arguments": {"action": "delete", "filter": {"sourceRow": 3}}}}
            return {"content": "已删除第 3 行，请核对最新预览。"}

    agent = Agent(ImportLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=3))
    result = agent.run("import-1", "u1", "删掉第3行", import_summary={"total": 3, "rows": [{"sourceRow": 3, "name": "王芳"}]})

    assert result["status"] == "completed"
    assert result["content"] == "已删除第 3 行，请核对最新预览。"
    assert result["importPlan"] == [{"tool": "mutate_import", "action": "delete", "filter": {"sourceRow": 3}}]

def test_import_agent_returns_final_plan_after_multiple_draft_operations():
    class ImportLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_call": {"name": "import.filter", "arguments": {"filter": {"status": "invalid"}}}}
            if self.calls == 2:
                return {"tool_call": {"name": "import.mutate", "arguments": {"action": "update", "target": {"sourceRow": 9}, "changes": {"field": "birthday", "value": "1989-11-22"}}}}
            if self.calls == 3:
                return {"tool_call": {"name": "import.mutate", "arguments": {"action": "update", "target": {"sourceRow": 30}, "changes": {"field": "birthday", "value": "1993-04-11"}}}}
            return {"content": "已按你的说明修正两条生日。"}

    result = Agent(ImportLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=4)).run(
        "import-multi-step", "u1", "把两条日期修正", import_summary={"total": 38, "rows": []}
    )
    assert result["status"] == "completed"
    assert result["content"] == "已按你的说明修正两条生日。"
    assert len(result["importPlan"]) == 3

def test_import_agent_ignores_legacy_tool_events_without_a_result_when_returning_a_new_plan():
    class ImportLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_call": {"name": "import.mutate", "arguments": {"action": "update", "target": {"sourceRow": 30}, "changes": {"field": "birthday", "value": "1993-04-11"}}}}
            return {"content": "已按确认的公历月/日/年格式更新导入预览。"}

    store = InMemoryStateStore()
    state = store.load("import-legacy-observation", "u1")
    state.append("tool_observation", tool="import.propose_choice", content="旧版选择记录")
    store.save(state, 0)

    result = Agent(ImportLLM(), import_draft_skill(), store, Settings(max_steps=2)).run(
        "import-legacy-observation", "u1", "按公历月日年处理", import_summary={"rows": [{"sourceRow": 30, "rawValues": {"生日": "4/11/93"}}]}
    )

    assert result["status"] == "completed"
    assert result["importPlan"] == [{"tool": "mutate_import", "action": "update", "target": {"sourceRow": 30}, "changes": {"field": "birthday", "value": "1993-04-11"}}]

def test_import_runtime_does_not_expose_a_noop_inspection_tool_when_draft_data_is_already_in_context():
    tool_names = [definition["name"] for definition in import_draft_skill().definitions()]
    assert "import.inspect" not in tool_names

def test_agent_corrects_a_repeated_no_progress_tool_call_before_exhausting_its_budget():
    class RepeatingLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls < 3:
                return {"tool_call": {"name": "import.filter", "arguments": {"filter": {"status": "invalid"}}}}
            assert any("repeated the same operation" in item["content"] for item in messages if item["role"] == "system")
            return {"content": "请确认这两条日期采用月/日/年份还是日/月/年份。"}

    result = Agent(RepeatingLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=8)).run(
        "import-repeat", "u1", "处理日期", import_summary={"total": 2, "rows": []}
    )
    assert result["status"] == "completed"
    assert result["content"] == "请确认这两条日期采用月/日/年份还是日/月/年份。"

def test_import_agent_returns_a_date_interpretation_recommendation_before_mutating_ambiguous_rows():
    class SuggestionLLM:
        def chat(self, messages, tools):
            system = next(item["content"] for item in messages if item["role"] == "system")
            assert "ask the user to confirm" in system
            return {"content": "第9行“11/22/89”较可能是 1989年11月22日；第30行“4/11/93”可能是 1993年4月11日或 1993年11月4日。请选择对应解释后，我再更新预览。"}

    result = Agent(SuggestionLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=2)).run(
        "import-date-suggestion", "u1", "处理日期", import_summary={"rows": [{"sourceRow": 9, "rawValues": {"生日": "11/22/89"}}, {"sourceRow": 30, "rawValues": {"生日": "4/11/93"}}]}
    )
    assert result["status"] == "completed"
    assert result["importPlan"] == []

def test_import_agent_returns_structured_choices_for_an_ambiguous_date_before_any_mutation():
    class ChoiceLLM:
        def chat(self, messages, tools):
            return {"tool_call": {"name": "import.propose_choice", "arguments": {
                "title": "确认日期格式", "message": "第30行的日期格式存在歧义。",
                "options": [
                    {"id": "mdy", "label": "1993年4月11日", "description": "按月/日/年份理解", "steps": [{"tool": "mutate_import", "action": "update", "target": {"sourceRow": 30}, "changes": {"field": "birthday", "value": "1993-04-11"}}]},
                    {"id": "dmy", "label": "1993年11月4日", "description": "按日/月/年份理解", "steps": [{"tool": "mutate_import", "action": "update", "target": {"sourceRow": 30}, "changes": {"field": "birthday", "value": "1993-11-04"}}]},
                ],
            }}}

    result = Agent(ChoiceLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=2)).run(
        "import-date-choice", "u1", "处理日期", import_summary={"rows": [{"sourceRow": 30, "rawValues": {"生日": "4/11/93"}}]}
    )
    assert result["ui"]["kind"] == "choice_required"
    assert len(result["ui"]["options"]) == 2
    assert result["importPlan"] == []

def test_import_follow_up_receives_the_pending_choice_state():
    class ChoiceThenApplyLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            system = next(item["content"] for item in messages if item["role"] == "system")
            if self.calls == 1:
                return {"tool_call": {"name": "import.propose_choice", "arguments": {
                    "title": "确认日期格式", "message": "请选择完整处理方式。",
                    "options": [
                        {"id": "mdy", "label": "按月/日/年处理全部两行", "steps": [{"tool": "mutate_import", "action": "update", "target": {"sourceRow": 9}, "changes": {"field": "birthday", "value": "1989-11-22"}}]},
                        {"id": "dmy", "label": "按日/月/年处理全部两行", "steps": [{"tool": "mutate_import", "action": "update", "target": {"sourceRow": 9}, "changes": {"field": "birthday", "value": "1989-22-11"}}]},
                    ],
                }}}
            assert "待用户选择的草稿方案" in system
            assert "按月/日/年处理全部两行" in system
            return {"content": "请点击上方选项确认。"}

    agent = Agent(ChoiceThenApplyLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=2))
    summary = {"rows": [{"sourceRow": 9, "rawValues": {"生日": "11/22/89"}}]}
    first = agent.run("import-choice-context", "u1", "处理日期", import_summary=summary)
    second = agent.run("import-choice-context", "u1", "按月日年", import_summary=summary)

    assert first["ui"]["kind"] == "choice_required"
    assert second["status"] == "completed"

def test_import_agent_recovers_from_an_invalid_draft_operation_without_failing_the_request():
    class ImportLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_call": {"name": "import.mutate", "arguments": {}}}
            return {"content": "请告诉我需要修改哪一行，以及要修改成什么内容。"}

    result = Agent(ImportLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=3)).run(
        "import-invalid", "u1", "帮我处理一下", import_summary={"total": 3, "rows": []}
    )

    assert result["status"] == "completed"
    assert result["content"] == "请告诉我需要修改哪一行，以及要修改成什么内容。"
    assert result["importPlan"] == []

def test_import_agent_replans_an_invalid_choice_payload_into_a_structured_choice():
    class ChoiceRepairLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_call": {"name": "import.propose_choice", "arguments": {
                    "title": "确认日期", "message": "请选择。",
                    "options": [
                        {"id": "a", "label": "1989年11月22日", "steps": ["更新第9行"]},
                        {"id": "b", "label": "1993年4月11日", "steps": ["更新第30行"]},
                    ],
                }}}
            assert any("structured step object" in item["content"] for item in messages if item["role"] == "system")
            return {"tool_call": {"name": "import.propose_choice", "arguments": {
                "title": "确认日期", "message": "请选择。",
                "options": [
                    {"id": "a", "label": "1989年11月22日", "steps": [{"tool": "mutate_import", "action": "update", "target": {"sourceRow": 9}, "changes": {"field": "birthday", "value": "1989-11-22"}}]},
                    {"id": "b", "label": "1993年4月11日", "steps": [{"tool": "mutate_import", "action": "update", "target": {"sourceRow": 30}, "changes": {"field": "birthday", "value": "1993-04-11"}}]},
                ],
            }}}

    result = Agent(ChoiceRepairLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=3)).run(
        "import-choice-repair", "u1", "处理日期", import_summary={"rows": []}
    )

    assert result["ui"]["kind"] == "choice_required"
    assert len(result["ui"]["options"]) == 2


def test_import_agent_requires_date_skill_before_accepting_a_birthday_mutation():
    class DateAwareLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_call": {"name": "import.mutate", "arguments": {"action": "update", "target": {"sourceRow": 9}, "changes": {"field": "birthday", "value": "11/22/89"}}}}
            if self.calls == 2:
                assert any("date.parse" in item.get("content", "") for item in messages)
                return {"tool_call": {"name": "date.parse", "arguments": {"value": "11/22/89"}}}
            return {"content": "这个日期包含两位年份，无法确认世纪。请选择正确年份后我再更新预览。"}

    result = Agent(DateAwareLLM(), import_draft_skill(), InMemoryStateStore(), Settings(max_steps=4)).run(
        "import-date-validation", "u1", "处理第9行生日", import_summary={"rows": [{"sourceRow": 9, "rawValues": {"生日": "11/22/89"}}]}
    )

    assert result["status"] == "completed"
    assert result["importPlan"] == []

def test_grounded_agent_retries_when_the_model_answers_before_using_a_tool():
    class PrematureAnswerLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"content": "我来为您统计通讯录中的联系人数量。"}
            if self.calls == 2:
                return {"tool_call": {"name": "contact.find", "arguments": {"name": "小王"}}}
            return {"content": "当前共有 1 位联系人。"}

    agent = Agent(PrematureAnswerLLM(), contact_skill([{"id": "c1", "name": "小王"}]), InMemoryStateStore(), Settings(max_steps=3))
    result = agent.run("s-grounded", "u1", "我有多少联系人？", require_observation=True)

    assert result["status"] == "completed"
    assert result["content"] == "当前共有 1 位联系人。"

def test_agent_can_answer_a_collection_question_with_a_skill_collection_tool():
    class CollectionLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_call": {"name": "contact.list", "arguments": {"city": "上海", "limit": 20}}}
            return {"content": "上海有 2 位联系人：甲、乙。"}

    contacts = [{"id": "c1", "name": "甲", "address": "上海市浦东新区"}, {"id": "c2", "name": "乙", "address": "上海市徐汇区"}]
    agent = Agent(CollectionLLM(), contact_skill(contacts), InMemoryStateStore(), Settings(max_steps=3))
    result = agent.run("s-collection", "u1", "有谁在上海", require_observation=True)

    assert result["status"] == "completed"
    assert result["content"] == "上海有 2 位联系人：甲、乙。"

def test_agent_returns_a_clarification_after_an_ambiguous_entity_search():
    class AmbiguousLLM:
        def chat(self, messages, tools):
            return {"tool_call": {"name": "contact.find", "arguments": {"name": "王芳"}}}

    contacts = [{"id": "c1", "name": "王芳", "relation": "妈妈"}, {"id": "c2", "name": "王芳", "relation": "同事"}]
    result = Agent(AmbiguousLLM(), contact_skill(contacts), InMemoryStateStore(), Settings(max_steps=3)).run("s-ambiguous", "u1", "查王芳的生日", require_observation=True)

    assert result["status"] == "completed"
    assert "找到多位同名联系人" in result["content"]
    assert "妈妈" in result["content"]
    assert "同事" in result["content"]

def test_agent_returns_a_confirmation_instruction_instead_of_claiming_a_write():
    class UpdateLLM:
        def chat(self, messages, tools):
            return {"tool_call": {"name": "contact.propose_update", "arguments": {"field": "dislikes", "value": "香菜"}}}

    from niannian_agent.birthdae import birthdae_contact_skill
    class Client:
        def execute(self, tool, arguments, *args, **kwargs):
            assert tool == "contact.details"
            assert arguments == {"contactId": "c1"}
            return {"status": "ok", "contact": {"ref": {"id": "c1", "scope": "personal"}, "name": "王芳"}}
    state = InMemoryStateStore()
    loaded = state.load("s-confirm", "u1")
    loaded.subject_contact = {"id": "c1", "name": "王芳", "scope": "personal"}
    state.save(loaded, 0)

    result = Agent(UpdateLLM(), birthdae_contact_skill(Client(), "token"), state, Settings(max_steps=3)).run("s-confirm", "u1", "给她加上不吃香菜")

    assert result["ui"]["kind"] == "confirmation"
    assert result["ui"]["plan"]["steps"][0]["changes"]["field"] == "dislikes"

def test_agent_never_exposes_a_serialized_internal_tool_call_to_the_user():
    class LeakingLLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"content": '{"name":"contact.details","arguments":{"contactId":"c1"}}'}
            return {"content": "王芳的完整资料已整理好。"}

    result = Agent(LeakingLLM(), contact_skill([{ "id": "c1", "name": "王芳" }]), InMemoryStateStore(), Settings(max_steps=2)).run("s-firewall", "u1", "把她的资料给我")

    assert result["content"] == "王芳的完整资料已整理好。"

def test_private_assistant_keeps_a_confirmed_relation_subject_for_a_gift_question():
    class LLM:
        def chat(self, messages, tools):
            system = next(item["content"] for item in messages if item["role"] == "system")
            assert "王芳" in system
            assert "Do not re-search" in system
            return {"content": "我会按妈妈这位王芳的资料准备建议。"}

    store = InMemoryStateStore()
    state = store.load("s-gift", "u1")
    state.subject_contact = {"id": "c1", "name": "王芳", "scope": "personal", "relation": "妈妈"}
    store.save(state, 0)
    result = Agent(LLM(), contact_skill([]), store, Settings(max_steps=1)).run("s-gift", "u1", "应该给妈妈准备什么礼物？")

    assert result["content"] == "我会按妈妈这位王芳的资料准备建议。"

def test_agent_reports_user_safe_tool_progress_without_exposing_tool_name():
    updates = []
    class LLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            return {"tool_call": {"name": "contact.find", "arguments": {"name": "王芳"}}} if self.calls == 1 else {"content": "已找到王芳。"}

    Agent(LLM(), contact_skill([{ "id": "c1", "name": "王芳" }]), InMemoryStateStore(), Settings(max_steps=2)).run("s-progress", "u1", "查王芳", progress=updates.append)

    assert updates == ["正在查询联系人资料"]

def test_agent_persists_ambiguous_candidates_for_the_follow_up_selection():
    class LLM:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_call": {"name": "contact.find", "arguments": {"name": "王芳"}}}
            system = next(item["content"] for item in messages if item["role"] == "system")
            assert '"relation": "妈妈"' in system
            return {"content": "请确认是妈妈这位王芳。"}

    store = InMemoryStateStore()
    agent = Agent(LLM(), contact_skill([{ "id": "c1", "name": "王芳", "relation": "妈妈" }, { "id": "c2", "name": "王芳", "relation": "同事" }]), store, Settings(max_steps=3))
    agent.run("s-candidates", "u1", "查王芳", require_observation=True)
    result = agent.run("s-candidates", "u1", "妈妈那位", require_observation=False)

    assert result["status"] == "completed"

def test_agent_includes_the_current_subject_in_the_next_turn_context():
    class SubjectAwareLLM:
        def __init__(self): self.calls = 0; self.messages = []
        def chat(self, messages, tools):
            self.calls += 1
            self.messages = messages
            if self.calls == 1:
                return {"tool_call": {"name": "contact.find", "arguments": {"name": "朱思远"}}}
            return {"content": "朱思远的资料已展示。"}

    llm = SubjectAwareLLM()
    agent = Agent(llm, contact_skill([{ "id": "zhu-1", "name": "朱思远" }]), InMemoryStateStore(), Settings(max_steps=3))
    agent.run("s-subject", "u1", "查询朱思远", require_observation=True)
    agent.run("s-subject", "u1", "再给我展示一下他的完整信息", require_observation=True)

    system_messages = [message["content"] for message in llm.messages if message["role"] == "system"]
    assert any("朱思远" in message and "zhu-1" in message for message in system_messages)

def test_agent_restores_subject_from_a_persistent_state_adapter():
    class Store:
        def load(self, session_id, user_id):
            from niannian_agent.state import ConversationState
            return ConversationState(session_id=session_id, user_id=user_id, revision=2, subject_contact={"id": "zhu-1", "name": "朱思远", "scope": "org-1"})
        def save(self, state, expected_revision):
            assert expected_revision == 2
            assert state.subject_contact["id"] == "zhu-1"
            return state

    class LLM:
        def chat(self, messages, tools):
            assert any("朱思远" in item["content"] for item in messages if item["role"] == "system")
            return {"tool_call": {"name": "contact.details", "arguments": {}}}

    class Client:
        def execute(self, tool, arguments, actor_token, request_id):
            assert tool == "contact.details"
            assert arguments == {"contactId": "zhu-1"}
            return {"status": "ok", "contact": {"ref": {"id": "zhu-1", "scope": "org-1"}, "name": "朱思远"}}

    from niannian_agent.birthdae import birthdae_contact_skill
    result = Agent(LLM(), birthdae_contact_skill(Client(), "token"), Store(), Settings(max_steps=1)).run("s1", "u1", "展示他的完整资料", "token", require_observation=True)

    assert result["status"] == "budget_exhausted"

def test_agent_uses_a_token_scoped_state_store_factory():
    calls = []
    class Store:
        def load(self, session_id, user_id):
            from niannian_agent.state import ConversationState
            return ConversationState(session_id=session_id, user_id=user_id)
        def save(self, state, expected_revision): return state
    class LLM:
        def chat(self, messages, tools): return {"content": "已记录。"}

    agent = Agent(LLM(), contact_skill([]), settings=Settings(max_steps=1), state_store_factory=lambda token: calls.append(token) or Store())
    agent.run("s1", "u1", "你好", actor_token="scoped-token")

    assert calls == ["scoped-token"]

def test_persistent_state_store_restores_recent_events_and_task_summary():
    from niannian_agent.state import PersistentStateStore, ConversationState
    saved = {}
    class Client:
        def load_conversation(self, session_id, token):
            return {"revision": 4, "state": {"subjectContact": {"id": "zhu-1", "name": "朱思远", "scope": "org-1"}, "task": {"goal": "补全朱思远的资料", "status": "active"}, "summary": "已确认朱思远是当前联系人。"}, "events": [{"type": "user_message", "content": "查询朱思远"}, {"type": "assistant_message", "content": "已找到朱思远。"}]}
        def commit_conversation(self, session_id, revision, state, events, token):
            saved.update({"session_id": session_id, "revision": revision, "state": state, "events": events})
            return {"revision": revision + 1, "state": state}

    store = PersistentStateStore(Client(), "token")
    state = store.load("s1", "u1")
    state.append("user_message", content="再展示他的完整信息")
    state.summary = "已确认朱思远是当前联系人，正在展示完整资料。"
    store.save(state, 4)

    assert state.subject_contact["id"] == "zhu-1"
    assert state.goal == "补全朱思远的资料"
    assert len(state.timeline) == 3
    assert saved["revision"] == 4
    assert saved["state"]["summary"].endswith("完整资料。")

def test_agent_uses_summary_and_recent_events_as_long_conversation_context():
    class Store:
        def load(self, session_id, user_id):
            from niannian_agent.state import ConversationState
            return ConversationState(session_id=session_id, user_id=user_id, revision=10, summary="已查询朱思远，并补充性别男、关系同学。", timeline=[{"type": "assistant_message", "content": "朱思远已更新。"}])
        def save(self, state, expected_revision): return state
    class LLM:
        def chat(self, messages, tools):
            system = next(item["content"] for item in messages if item["role"] == "system")
            assert "长期会话摘要" in system
            assert "朱思远已更新。" in system
            return {"content": "已继续处理。"}

    result = Agent(LLM(), contact_skill([]), Store(), Settings(max_steps=1)).run("s1", "u1", "继续")
    assert result["status"] == "completed"

def test_persistent_state_store_appends_only_new_events_and_bounds_the_projection():
    from niannian_agent.state import PersistentStateStore
    saved = {}
    old_events = [{"type": "assistant_message", "content": f"历史消息{i}"} for i in range(30)]
    class Client:
        def load_conversation(self, session_id, token): return {"revision": 6, "state": {"summary": "已有摘要"}, "events": old_events}
        def commit_conversation(self, session_id, revision, state, events, token):
            saved["events"] = events; saved["state"] = state
            return {"revision": 7, "state": state}
    store = PersistentStateStore(Client(), "token")
    state = store.load("s1", "u1")
    state.append("user_message", content="第31轮继续")
    store.save(state, 6)

    assert saved["events"] == [{"type": "user_message", "content": "第31轮继续"}]
    assert "历史消息10" in saved["state"]["summary"]
