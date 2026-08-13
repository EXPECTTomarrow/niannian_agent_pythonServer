import json
from typing import Any, Callable, Optional
from .config import Settings
from .state import InMemoryStateStore
from .skills import SkillRegistry

class Agent:
    def __init__(self, llm: Any, skills: SkillRegistry, store: Optional[InMemoryStateStore] = None, settings: Optional[Settings] = None, skill_factory: Optional[Callable[[str], SkillRegistry]] = None, state_store_factory: Optional[Callable[[str], Any]] = None) -> None:
        self.llm, self.skills, self.store, self.settings, self.skill_factory, self.state_store_factory = llm, skills, store or InMemoryStateStore(), settings or Settings(), skill_factory, state_store_factory

    def run(self, session_id: str, user_id: str, message: str, actor_token: str = "", request_id: str = "", import_summary: Optional[dict[str, Any]] = None, require_observation: bool = False, subject_contact: Optional[dict[str, Any]] = None, progress: Optional[Callable[[str], None]] = None) -> dict[str, Any]:
        store = self.state_store_factory(actor_token) if self.state_store_factory and actor_token else self.store
        state = store.load(session_id, user_id)
        if isinstance(subject_contact, dict) and subject_contact.get("id") and subject_contact.get("name"):
            state.subject_contact = {key: subject_contact[key] for key in ("id", "name", "scope") if subject_contact.get(key)}
        is_import_draft = isinstance(import_summary, dict)
        skills = __import__("niannian_agent.import_draft", fromlist=["import_draft_skill"]).import_draft_skill() if is_import_draft else (self.skill_factory(actor_token) if self.skill_factory else self.skills)
        expected = state.revision
        state.append("user_message", content=message, requestId=request_id)
        print(json.dumps({"event": "agent.request", "requestId": request_id, "sessionId": session_id, "user": user_id[-8:], "message": message[:200]}, ensure_ascii=False), flush=True)
        system_content = "You are a careful private assistant. Be attentive to the user's long-running context, verify external facts with available tools, and answer naturally in Chinese. Never mention tools, skills, APIs, internal identifiers, or implementation details. For questions about today, now, relative dates, or date ranges such as future three months, obtain the current time through the available time capability before answering. When a search or organization resolution returns multiple candidates, ask the user to choose and do not guess from stale history. A newly named entity must be resolved again; pronouns and a relationship reference such as 妈妈 refer only to the current confirmed subject. Do not re-search a confirmed subject for a follow-up gift or advice request. Use total fields for counts, never infer a total from a visible page. For a new contact, use contact.propose_create to prepare the existing editable contact form. For any update, use contact.propose_update; for deletion use contact.propose_delete immediately after a unique target is confirmed. These only prepare confirmation or form instructions and never write data. Never claim a contact was created, updated, or deleted unless an execution observation confirms it. For multiple full profiles, use contact.batch_details."
        system_content += "\n" + skills.capability_statement() + " When the user asks what can be done or asks for guidance, give suggestions from this capability statement that fit the user's current context and authorization. Do not use fixed canned prompts."
        system_content += self._conversation_context(state)
        if state.subject_contact:
            system_content += " Current conversation subject: " + json.dumps(state.subject_contact, ensure_ascii=False) + ". Resolve pronouns such as 他、她、这位联系人 to this subject unless the user explicitly names another contact."
        if is_import_draft:
            system_content = "You manage only the current uploaded contact import draft. The draft summary below is authoritative and already contains the rows, their original values, validation errors, and editable fields; do not request an inspection. Use import tools only to create a safe client-side plan. Never create, update, delete, or import saved contacts. The user must confirm separately. Before every birthday mutation, call date.parse with the original or proposed date. Only a resolved ISO value may be passed to import.mutate. For ambiguous regional date formats or two-digit years, ask the user to confirm by using import.propose_choice with the date.parse candidates; do not guess a locale or century. For an invalid date, explain the correction needed naturally. Return a concise answer in Chinese. Draft summary: " + json.dumps(import_summary, ensure_ascii=False) + self._conversation_context(state)
        messages = [{"role": "system", "content": system_content}]
        messages += [{"role": "user", "content": message}]
        # Import drafts may require inspection, several row edits, and one final reply.
        # Use the shared runtime budget instead of imposing a special small ceiling.
        max_steps = self.settings.max_steps
        has_observation = False
        attempted_calls: set[str] = set()
        blocked_date_targets: set[str] = set()
        turn_import_plan: list[dict[str, Any]] = []
        for _ in range(max_steps):
            reply = self.llm.chat(messages, skills.definitions())
            call = reply.get("tool_call")
            if not call and reply.get("tool_calls"):
                native_call = reply["tool_calls"][0]
                function = native_call.get("function", {})
                try:
                    arguments = json.loads(function.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}
                call = {"name": function.get("name", ""), "arguments": arguments}
            if not call:
                content = reply.get("content", "")
                embedded_call = self._embedded_tool_call(content, skills)
                if embedded_call:
                    call = embedded_call
                elif self._leaks_internal_protocol(content):
                    messages.append({"role": "system", "content": "Your previous draft exposed internal protocol. Do not expose implementation details. Continue the task with an available tool or answer the user naturally in Chinese."})
                    continue
            if not call:
                content = reply.get("content", "")
                if require_observation and not has_observation:
                    messages.append({"role": "system", "content": "This response needs verified external facts. Call an available tool before answering. Do not say that you are querying; perform the tool call."})
                    continue
                state.append("assistant_message", content=content)
                state.status = "completed"
                store.save(state, expected)
                print(json.dumps({"event": "agent.response", "requestId": request_id, "status": "completed", "subject": state.subject_contact and state.subject_contact.get("id", "")}, ensure_ascii=False), flush=True)
                result = {"status": "completed", "content": content, "revision": state.revision, "subjectContact": state.subject_contact}
                if is_import_draft:
                    result["importPlan"] = turn_import_plan
                return result
            call_signature = json.dumps({"name": call.get("name", ""), "arguments": call.get("arguments", {})}, ensure_ascii=False, sort_keys=True)
            if call_signature in attempted_calls:
                messages.append({"role": "system", "content": "You repeated the same operation without receiving new information. Do not repeat it. Re-plan from the available draft data: either perform a different necessary operation, or give the user a clear answer, recommendation, or clarification."})
                continue
            attempted_calls.add(call_signature)
            print(json.dumps({"event": "agent.tool_call", "requestId": request_id, "tool": call.get("name"), "arguments": call.get("arguments", {})}, ensure_ascii=False), flush=True)
            tool = skills.get(call["name"])
            if is_import_draft and tool.name == "import.mutate":
                arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                target = arguments.get("target") if isinstance(arguments.get("target"), dict) else {}
                target_key = json.dumps(target, ensure_ascii=False, sort_keys=True)
                if arguments.get("action") == "update" and arguments.get("changes", {}).get("field") == "birthday" and target_key in blocked_date_targets:
                    messages.append({"role": "system", "content": "This date target is still ambiguous. Do not apply any birthday mutation until the user confirms a candidate. Use import.propose_choice with valid ISO candidates or ask a natural clarification."})
                    continue
                date_gate = self._validate_import_birthday(skills, call)
                if date_gate:
                    if date_gate["status"] == "resolved":
                        call["arguments"]["changes"]["value"] = date_gate["value"]
                    else:
                        blocked_date_targets.add(target_key)
                        messages.append({"role": "system", "content": "date.parse result: " + json.dumps(date_gate, ensure_ascii=False) + ". Do not create an import mutation for this birthday. If ambiguous, use import.propose_choice with only valid ISO date candidates; if invalid, explain what needs correction naturally in Chinese."})
                        continue
            if progress:
                progress(self._progress_label(tool.name, call.get("arguments", {})))
            try:
                result = tool.handler(call.get("arguments", {}), state)
            except ValueError as error:
                if is_import_draft and str(error).startswith("IMPORT_"):
                    correction = "The draft operation was incomplete. Ask the user naturally in Chinese for the missing row, target, or value. Do not emit an empty or invalid operation."
                    if str(error) == "IMPORT_CHOICES_REQUIRED":
                        correction = "Your choice proposal was invalid. Each option must contain at least one structured step object: {tool: 'mutate_import', action: 'update', target: {sourceRow: number}, changes: {field: string, value: string}}. Reissue the complete structured choice proposal; never put natural-language sentences in steps."
                    messages.append({"role": "system", "content": correction})
                    continue
                raise
            state.last_execution = {"tool": tool.name, "result": result}
            state.append("tool_observation", tool=tool.name, result=result, content=json.dumps(result, ensure_ascii=False)[:2000])
            has_observation = True
            if is_import_draft and isinstance(result, dict) and result.get("tool"):
                turn_import_plan.append(result)
                state.pending_mutation = None
            if tool.requires_confirmation:
                plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
                content = str(plan.get("reply", "我已整理好修改内容，请确认后执行。"))
                state.append("assistant_message", content=content)
                state.status = "completed"
                store.save(state, expected)
                return {"status": "completed", "content": content, "revision": state.revision, "subjectContact": state.subject_contact,
                        "ui": {"kind": "confirmation", "content": content, "plan": plan, "subjectContact": state.subject_contact}}
            if result.get("status") == "form_draft":
                content = str(result.get("message", "我已整理好联系人资料，请补充后确认添加。"))
                state.append("assistant_message", content=content)
                state.status = "completed"
                store.save(state, expected)
                return {"status": "completed", "content": content, "revision": state.revision, "subjectContact": state.subject_contact,
                        "ui": {"kind": "form_draft", "content": content, "draft": result.get("draft", {}), "scope": result.get("scope", "personal")}}
            if result.get("status") == "input_required":
                content = str(result.get("message", "请补充必要信息。"))
                state.append("assistant_message", content=content)
                state.status = "completed"
                store.save(state, expected)
                return {"status": "completed", "content": content, "revision": state.revision, "subjectContact": state.subject_contact,
                        "ui": {"kind": "form_draft", "content": content, "draft": result.get("draft", {}), "scope": "personal"}}
            if result.get("status") == "choice_required":
                content = str(result.get("message", "请选择一种处理方式。"))
                state.append("assistant_message", content=content)
                state.pending_mutation = {"kind": "import_choice", "title": result.get("title", "请确认"), "options": result.get("options", [])}
                state.status = "waiting_for_user"
                store.save(state, expected)
                output = {"status": "completed", "content": content, "revision": state.revision, "subjectContact": state.subject_contact,
                          "ui": {"kind": "choice_required", "content": content, "title": result.get("title", "请确认"), "options": result.get("options", [])}}
                if is_import_draft:
                    output["importPlan"] = []
                return output
            if result.get("status") == "ambiguous" and tool.name != "date.parse":
                state.pending_candidates = [item for item in result.get("contacts", []) if isinstance(item, dict)][:10]
                content = self._clarification_message(result)
                state.append("assistant_message", content=content)
                state.status = "completed"
                store.save(state, expected)
                return {"status": "completed", "content": content, "revision": state.revision, "subjectContact": state.subject_contact,
                        "ui": {"kind": "clarification", "content": content, "candidates": result.get("contacts", [])}}
            messages.extend([{"role": "assistant", "content": json.dumps(call, ensure_ascii=False)}, {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}])
        state.status = "budget_exhausted"
        store.save(state, expected)
        return {"status": "budget_exhausted", "content": "我暂时无法完成这个任务，请换一种说法。", "revision": state.revision, "subjectContact": state.subject_contact}

    @staticmethod
    def _validate_import_birthday(skills: SkillRegistry, call: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Require deterministic date interpretation before a draft birthday mutation."""
        arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
        changes = arguments.get("changes") if isinstance(arguments.get("changes"), dict) else {}
        if arguments.get("action") != "update" or changes.get("field") != "birthday":
            return None
        parser = skills.get("date.parse")
        return parser.handler({"value": changes.get("value", "")}, None)

    def list_conversations(self, actor_token: str) -> dict[str, Any]:
        if not self.state_store_factory:
            return {"conversations": []}
        store = self.state_store_factory(actor_token)
        client = getattr(store, "client", None)
        return client.list_conversations(actor_token) if client else {"conversations": []}

    def load_history(self, session_id: str, user_id: str, actor_token: str) -> dict[str, Any]:
        store = self.state_store_factory(actor_token) if self.state_store_factory else self.store
        state = store.load(session_id, user_id)
        return {"sessionId": session_id, "events": state.timeline, "subjectContact": state.subject_contact}

    @staticmethod
    def _progress_label(tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "time.now": return "正在确认当前时间"
        if tool_name in {"contact.search", "contact.find"}: return "正在查询联系人资料"
        if tool_name in {"contact.details", "contact.select"}: return "正在核实联系人资料"
        if tool_name in {"contact.list", "contact.query"}:
            missing = arguments.get("filter", {}).get("missing", []) if isinstance(arguments.get("filter"), dict) else []
            return "正在查询缺少资料的联系人" if missing else "正在查询通讯录"
        if tool_name == "contact.batch_details": return "正在整理联系人详细资料"
        if tool_name in {"organization.list", "organization.resolve", "addressbook.list"}: return "正在查询通讯录与组织"
        if tool_name.startswith("contact.propose_"): return "正在核实信息并整理确认内容"
        return "正在核实相关资料"

    @staticmethod
    def _embedded_tool_call(content: Any, skills: SkillRegistry) -> Optional[dict[str, Any]]:
        if not isinstance(content, str):
            return None
        try:
            value = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None
        name = value.get("name") if isinstance(value, dict) else ""
        arguments = value.get("arguments", {}) if isinstance(value, dict) else {}
        if isinstance(name, str) and isinstance(arguments, dict):
            try:
                skills.get(name)
                return {"name": name, "arguments": arguments}
            except ValueError:
                return None
        return None

    @staticmethod
    def _leaks_internal_protocol(content: Any) -> bool:
        if not isinstance(content, str):
            return False
        lowered = content.lower()
        return '"arguments"' in lowered or '"tool"' in lowered or "contact." in lowered or "organization." in lowered

    @staticmethod
    def _clarification_message(result: dict[str, Any]) -> str:
        candidates = result.get("contacts") if isinstance(result.get("contacts"), list) else []
        labels = []
        for candidate in candidates[:5]:
            if not isinstance(candidate, dict):
                continue
            name = str(candidate.get("name", "")).strip()
            relation = str(candidate.get("relation", "")).strip()
            scope = str(candidate.get("source", "")).strip()
            hint = " / ".join(item for item in (relation, scope) if item)
            if name:
                labels.append(f"{name}（{hint}）" if hint else name)
        return f"找到多位同名联系人：{'、'.join(labels)}。请告诉我具体是哪一位。" if labels else "找到多位同名联系人，请补充关系、所在组织或其他资料。"

    @staticmethod
    def _conversation_context(state: Any) -> str:
        parts: list[str] = []
        if state.summary:
            parts.append("长期会话摘要: " + str(state.summary)[:4000])
        if state.subject_contact:
            parts.append("当前会话实体: " + json.dumps(state.subject_contact, ensure_ascii=False))
        if state.pending_candidates:
            parts.append("待用户消歧的候选实体: " + json.dumps(state.pending_candidates, ensure_ascii=False) + "。用户按关系、组织或序号选择后，必须调用 contact.select 传入候选的 ref.id。")
        if state.pending_mutation:
            if state.pending_mutation.get("kind") == "import_choice":
                parts.append("待用户选择的草稿方案: " + json.dumps(state.pending_mutation, ensure_ascii=False) + "。用户确认或补充格式后，必须据此生成完整的安全草稿变更计划；不要重新询问已经确认的信息。")
            else:
                parts.append("待用户确认的变更草案: " + json.dumps(state.pending_mutation, ensure_ascii=False) + "。用户在确认前补充同一目标的资料时，必须保留并合并已有全部变更。")
        recent = []
        for item in state.timeline[-12:]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if content:
                recent.append({"type": item.get("type", "event"), "content": content[:500]})
        if recent:
            parts.append("近期事件: " + json.dumps(recent, ensure_ascii=False))
        if not parts:
            return ""
        return "\nAuthoritative conversation state:\n" + "\n".join(parts) + "\nResolve pronouns such as 他、她、这位联系人 to the current entity unless the user explicitly names another entity."
