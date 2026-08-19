import json
import unittest
import httpx

from niannian_agent.birthdae import BirthdaeToolGatewayClient, birthdae_contact_skill
from niannian_agent.state import ConversationState


class BirthdaeToolGatewayClientTests(unittest.TestCase):
    def test_contact_search_forwards_short_lived_actor_token(self):
        received = {}

        def handler(request):
            received.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "contacts": [{"ref": {"id": "c1", "scope": "personal"}, "name": "小王"}]}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        state = ConversationState(session_id="s1", user_id="u1")
        result = birthdae_contact_skill(client, "short-lived-token").get("contact.search").handler({"name": "小王"}, state)

        self.assertEqual(received["actorToken"], "short-lived-token")
        self.assertEqual(received["tool"], "contact.search")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(state.subject_contact, {"id": "c1", "scope": "personal", "name": "小王"})

    def test_contact_list_forwards_collection_filters(self):
        received = {}

        def handler(request):
            received.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "count": 2, "contacts": [{"name": "甲"}, {"name": "乙"}]}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        state = ConversationState(session_id="s1", user_id="u1")
        result = birthdae_contact_skill(client, "short-lived-token").get("contact.list").handler({"city": "上海", "limit": 20}, state)

        self.assertEqual(received["tool"], "contact.list")
        self.assertEqual(received["arguments"], {"city": "上海", "limit": 20})
        self.assertEqual(result["count"], 2)

    def test_contact_query_forwards_structured_filter_and_page(self):
        received = {}
        def handler(request):
            received.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "total": 8, "contacts": []}})

        skill = birthdae_contact_skill(BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler))), "token")
        skill.get("contact.query").handler({"scope": "all", "filter": {"missing": ["address"]}, "page": {"limit": 10}}, ConversationState(session_id="s1", user_id="u1"))

        self.assertEqual(received["arguments"], {"scope": "all", "filter": {"missing": ["address"]}, "page": {"limit": 10}})

    def test_upcoming_birthdays_use_the_dedicated_bounded_gateway_operation(self):
        received = {}
        def handler(request):
            received.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "total": 2, "contacts": [{"name": "甲", "days": 3}]}})

        skill = birthdae_contact_skill(BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler))), "token")
        result = skill.get("contact.birthdays").handler({"scope": "all", "days": 30}, ConversationState(session_id="s1", user_id="u1"))

        self.assertEqual(received["tool"], "contact.birthdays")
        self.assertEqual(received["arguments"], {"scope": "all", "days": 30})
        self.assertEqual(result["total"], 2)

    def test_addressbook_list_includes_personal_and_organization_containers(self):
        def handler(_request):
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "addressbooks": [{"id": "personal", "name": "个人通讯录"}]}})

        skill = birthdae_contact_skill(BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler))), "token")
        result = skill.get("addressbook.list").handler({}, ConversationState(session_id="s1", user_id="u1"))
        self.assertEqual(result["addressbooks"][0]["name"], "个人通讯录")

    def test_addressbook_stats_forwards_one_aggregate_request(self):
        received = {}
        def handler(request):
            received.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "addressbooks": [{"name": "蒙太奇通讯录", "contactCount": 3}]}})
        skill = birthdae_contact_skill(BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler))), "token")

        result = skill.get("addressbook.stats").handler({}, ConversationState(session_id="s1", user_id="u1"))

        self.assertEqual(received["tool"], "addressbook.stats")
        self.assertEqual(result["addressbooks"][0]["contactCount"], 3)

    def test_organization_resolution_and_scoped_count_use_declared_skill_arguments(self):
        received = []

        def handler(request):
            body = json.loads(request.content.decode("utf-8"))
            received.append(body)
            if body["tool"] == "organization.resolve":
                return httpx.Response(200, json={"success": True, "data": {"status": "ok", "organization": {"id": "org-1", "name": "智菲集团", "role": "admin"}}})
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "total": 38, "contacts": []}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        skill = birthdae_contact_skill(client, "short-lived-token")
        state = ConversationState(session_id="s1", user_id="u1")
        resolved = skill.get("organization.resolve").handler({"name": "智菲"}, state)
        listed = skill.get("contact.list").handler({"scope": resolved["organization"]["id"], "limit": 1}, state)

        self.assertEqual(resolved["organization"]["id"], "org-1")
        self.assertEqual(listed["total"], 38)
        self.assertEqual(received[1]["arguments"], {"scope": "org-1", "city": "", "limit": 1})

    def test_contact_search_defaults_to_the_last_resolved_organization(self):
        received = []

        def handler(request):
            body = json.loads(request.content.decode("utf-8"))
            received.append(body)
            if body["tool"] == "organization.resolve":
                return httpx.Response(200, json={"success": True, "data": {"status": "ok", "organization": {"id": "org-1", "name": "智菲公司通讯录"}}})
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "contacts": [{"ref": {"id": "c-1", "scope": "org-1"}, "name": "陈雨桐"}]}})

        skill = birthdae_contact_skill(BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler))), "token")
        state = ConversationState(session_id="s1", user_id="u1")
        skill.get("organization.resolve").handler({"name": "智菲"}, state)
        skill.get("contact.search").handler({"name": "陈雨桐"}, state)

        self.assertEqual(state.active_addressbook, {"id": "org-1", "name": "智菲公司通讯录"})
        self.assertEqual(received[1]["arguments"], {"name": "陈雨桐", "scope": "org-1"})

    def test_contact_search_defaults_to_the_organization_used_for_the_member_list(self):
        received = []

        def handler(request):
            body = json.loads(request.content.decode("utf-8"))
            received.append(body)
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "total": 47, "contacts": []}})

        skill = birthdae_contact_skill(BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler))), "token")
        state = ConversationState(session_id="s1", user_id="u1")
        skill.get("contact.list").handler({"scope": "org-1", "limit": 100}, state)
        skill.get("contact.search").handler({"name": "陈雨桐"}, state)

        self.assertEqual(state.active_addressbook, {"id": "org-1", "name": "当前群组通讯录"})
        self.assertEqual(received[1]["arguments"], {"name": "陈雨桐", "scope": "org-1"})

    def test_contact_details_uses_the_current_subject_when_no_id_is_provided(self):
        received = {}

        def handler(request):
            received.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "contact": {"ref": {"id": "zhu-1", "scope": "org-1"}, "name": "朱思远"}}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        state = ConversationState(session_id="s1", user_id="u1", subject_contact={"id": "zhu-1", "scope": "org-1", "name": "朱思远"})
        result = birthdae_contact_skill(client, "short-lived-token").get("contact.details").handler({}, state)

        self.assertEqual(received["arguments"], {"contactId": "zhu-1"})
        self.assertEqual(result["contact"]["name"], "朱思远")

    def test_conversation_store_loads_and_commits_a_structured_projection(self):
        requests = []

        def handler(request):
            body = json.loads(request.content.decode("utf-8"))
            requests.append(body)
            if body["tool"] == "conversation.load":
                return httpx.Response(200, json={"success": True, "data": {"revision": 3, "state": {"subjectContact": {"id": "zhu-1", "name": "朱思远", "scope": "org-1"}}, "events": []}})
            return httpx.Response(200, json={"success": True, "data": {"revision": 4, "state": body["arguments"]["state"]}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        loaded = client.load_conversation("s1", "short-lived-token")
        saved = client.commit_conversation("s1", 3, loaded["state"], [{"type": "assistant_message", "content": "已找到朱思远。"}], "short-lived-token")

        self.assertEqual(loaded["state"]["subjectContact"]["id"], "zhu-1")
        self.assertEqual(saved["revision"], 4)
        self.assertEqual(requests[1]["arguments"]["revision"], 3)

    def test_contact_search_keeps_the_subject_empty_when_multiple_candidates_match(self):
        def handler(_request):
            return httpx.Response(200, json={"success": True, "data": {"status": "ambiguous", "contacts": [
                {"ref": {"id": "c1", "scope": "personal"}, "name": "王芳", "relation": "妈妈"},
                {"ref": {"id": "c2", "scope": "org-1"}, "name": "王芳", "relation": "同事"},
            ]}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        state = ConversationState(session_id="s1", user_id="u1")
        result = birthdae_contact_skill(client, "short-lived-token").get("contact.search").handler({"name": "王芳"}, state)

        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(state.subject_contact)

    def test_update_proposal_uses_the_selected_subject_and_never_writes(self):
        received = {}
        def handler(request):
            received.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "contact": {"ref": {"id": "c1", "scope": "personal"}, "name": "王芳", "phone": "13800000000", "dislikes": "芹菜"}}})
        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        state = ConversationState(session_id="s1", user_id="u1", subject_contact={"id": "c1", "name": "王芳", "scope": "personal"})

        result = birthdae_contact_skill(client, "short-lived-token").get("contact.propose_update").handler({"field": "dislikes", "value": "香菜"}, state)

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["plan"]["steps"][0]["target"]["id"], "c1")
        self.assertEqual(result["plan"]["steps"][0]["changes"], {"field": "dislikes", "value": "香菜"})
        self.assertEqual(result["plan"]["steps"][0]["before"]["dislikes"], "芹菜")
        self.assertEqual(result["plan"]["steps"][0]["after"]["dislikes"], "香菜")
        self.assertEqual(received["tool"], "contact.details")
        self.assertEqual(received["arguments"], {"contactId": "c1"})

    def test_update_proposal_merges_an_unconfirmed_change_into_the_same_confirmation(self):
        def handler(_request):
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "contact": {"ref": {"id": "c1", "scope": "personal"}, "name": "王芳", "gender": "female", "phone": "13800000000"}}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        state = ConversationState(session_id="s1", user_id="u1", subject_contact={"id": "c1", "name": "王芳", "scope": "personal"})
        skill = birthdae_contact_skill(client, "short-lived-token")
        skill.get("contact.propose_update").handler({"field": "gender", "value": "男"}, state)
        result = skill.get("contact.propose_update").handler({"field": "phone", "value": "15884895549"}, state)

        step = result["plan"]["steps"][0]
        self.assertEqual(step["changeSet"], {"gender": "男", "phone": "15884895549"})
        self.assertEqual(step["after"]["gender"], "男")
        self.assertEqual(step["after"]["phone"], "15884895549")

    def test_contact_proposal_rejects_an_invalid_phone_without_creating_a_confirmation(self):
        skill = birthdae_contact_skill(BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))), "short-lived-token")
        result = skill.get("contact.propose_create").handler({"contact": {"name": "王建", "phone": "1389895544"}, "scope": "personal"}, ConversationState(session_id="s1", user_id="u1"))
        self.assertEqual(result["status"], "input_required")
        self.assertIn("手机号", result["message"])

    def test_contact_create_proposal_returns_an_editable_form_draft(self):
        skill = birthdae_contact_skill(BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))), "short-lived-token")
        result = skill.get("contact.propose_create").handler({"contact": {"name": "王建", "phone": "13898955449", "relation": "同学", "interests": "羽毛球"}, "scope": "personal"}, ConversationState(session_id="s1", user_id="u1"))
        self.assertEqual(result["status"], "form_draft")
        self.assertEqual(result["draft"]["name"], "王建")

    def test_delete_proposal_reads_full_contact_before_requesting_confirmation(self):
        def handler(_request):
            return httpx.Response(200, json={"success": True, "data": {"status": "ok", "contact": {"ref": {"id": "c1", "scope": "personal"}, "name": "王芳", "phone": "13800000000"}}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        state = ConversationState(session_id="s1", user_id="u1", subject_contact={"id": "c1", "name": "王芳", "scope": "personal"})
        result = birthdae_contact_skill(client, "short-lived-token").get("contact.propose_delete").handler({}, state)

        step = result["plan"]["steps"][0]
        self.assertEqual(step["action"], "delete")
        self.assertEqual(step["before"]["phone"], "13800000000")


if __name__ == "__main__":
    unittest.main()
