import json
import unittest

import httpx

from niannian_agent.birthdae import BirthdaeToolGatewayClient
from niannian_agent.import_task_skill import import_task_skill
from niannian_agent.state import ConversationState


class ImportTaskSkillTests(unittest.TestCase):
    def test_duplicate_choice_skill_sends_task_revision_and_operation_id(self):
        received = {}

        def handler(request):
            received.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"success": True, "data": {"task": {"id": "task-1", "revision": 4, "rows": []}}})

        client = BirthdaeToolGatewayClient("https://gateway.example", httpx.Client(transport=httpx.MockTransport(handler)))
        skill = import_task_skill(client, "actor-token")
        state = ConversationState(session_id="s1", user_id="u1")
        result = skill.get("import.resolve_duplicate").handler({
            "taskId": "task-1", "expectedRevision": 3, "rowId": "row-2", "decision": "skip", "operationId": "op-1",
        }, state)

        self.assertEqual(received["tool"], "import.resolve_duplicate")
        self.assertEqual(received["arguments"]["expectedRevision"], 3)
        self.assertEqual(received["arguments"]["operationId"], "op-1")
        self.assertEqual(result["task"]["revision"], 4)
