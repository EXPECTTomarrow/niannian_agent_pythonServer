import unittest

from niannian_agent.date_skill import parse_date
from niannian_agent.agent import Agent
from niannian_agent.config import Settings
from niannian_agent.import_draft import import_draft_skill
from niannian_agent.state import InMemoryStateStore, PersistentStateStore
from niannian_agent.task_runtime import reconcile_import_task, resolve_task_choice


class TaskRuntimeTests(unittest.TestCase):
    def test_import_checkpoint_keeps_the_second_date_after_reload(self):
        summary = {"rows": [
            {"sourceRow": 9, "name": "许嘉言", "rawValues": {"生日": "11/22/89"}},
            {"sourceRow": 30, "name": "孙文博", "rawValues": {"生日": "4/11/93"}},
        ]}
        artifact = {"id": "draft-1", "revision": 1}
        task = reconcile_import_task(None, summary, artifact, parse_date)

        self.assertEqual([item["id"] for item in task["workItems"]], ["row-9:birthday", "row-30:birthday"])
        self.assertEqual(task["focusedWorkItemId"], "row-9:birthday")

        task, decision = resolve_task_choice(task, "第9行选A")
        self.assertEqual(decision["workItemId"], "row-9:birthday")
        self.assertEqual(task["focusedWorkItemId"], "row-30:birthday")

        store = InMemoryStateStore()
        state = store.load("session-1", "user-1")
        state.active_task = task
        state.append("assistant_message", content="已更新第9行")
        store.save(state, 0)
        restored = store.load("session-1", "user-1")

        restored.active_task = reconcile_import_task(restored.active_task, summary, artifact, parse_date)
        focused = next(item for item in restored.active_task["workItems"] if item["id"] == restored.active_task["focusedWorkItemId"])
        self.assertEqual(focused["subjectName"], "孙文博")
        self.assertEqual(focused["rawValue"], "4/11/93")

        restored.active_task, named = resolve_task_choice(restored.active_task, "孙文博的生日也要改")
        self.assertIsNone(named)
        self.assertEqual(restored.active_task["focusedWorkItemId"], "row-30:birthday")

    def test_agent_restores_the_second_import_work_item_from_a_persistent_checkpoint(self):
        database = {"revision": 0, "state": {}, "events": []}

        class Client:
            def load_conversation(self, _session_id, _token):
                return {"revision": database["revision"], "state": database["state"], "events": database["events"]}

            def commit_conversation(self, _session_id, revision, state, events, _token):
                self.assert_revision(revision)
                database["revision"] += 1
                database["state"] = state
                database["events"].extend(events)
                return {"revision": database["revision"], "state": state}

            @staticmethod
            def assert_revision(revision):
                if revision != database["revision"]:
                    raise RuntimeError("revision conflict")

        class NeverCalledLLM:
            def chat(self, *_args, **_kwargs):
                raise AssertionError("structured import work must not depend on model memory")

        client = Client()
        agent = Agent(
            NeverCalledLLM(), import_draft_skill(), settings=Settings(max_steps=3),
            state_store_factory=lambda token: PersistentStateStore(client, token),
        )
        original = {"rows": [
            {"sourceRow": 9, "name": "许嘉言", "rawValues": {"生日": "11/22/89"}},
            {"sourceRow": 30, "name": "孙文博", "rawValues": {"生日": "4/11/93"}},
        ]}

        first = agent.run("session-2", "user-1", "导入联系人", "token", import_summary=original, import_artifact={"id": "draft-2", "revision": 1})
        chosen = agent.run("session-2", "user-1", "A", "token", import_summary=original, import_artifact={"id": "draft-2", "revision": 1})
        refreshed = {"rows": [
            {"sourceRow": 9, "name": "许嘉言", "birthdayKnownYear": True, "birthdayYear": 1989, "birthdayMonth": 11, "birthdayDay": 22, "rawValues": {"生日": "11/22/89"}},
            {"sourceRow": 30, "name": "孙文博", "rawValues": {"生日": "4/11/93"}},
        ]}
        second = agent.run("session-2", "user-1", "孙文博的生日也要改", "token", import_summary=refreshed, import_artifact={"id": "draft-2", "revision": 2, "completedOperationIds": [chosen["operationId"]]})

        self.assertEqual(first["task"]["focusedWorkItemId"], "row-9:birthday")
        self.assertEqual(chosen["expectedArtifactRevision"], 1)
        self.assertEqual(second["task"]["focusedWorkItemId"], "row-30:birthday")
        self.assertEqual(second["ui"]["kind"], "choice_required")
        self.assertEqual(second["ui"]["options"][0]["steps"][0]["target"]["sourceRow"], 30)
        self.assertEqual(database["state"]["activeTask"]["artifact"]["revision"], 2)
        self.assertIn(chosen["operationId"], database["state"]["activeTask"]["completedOperationIds"])

    def test_agent_rejects_an_older_import_artifact_revision(self):
        store = InMemoryStateStore()
        state = store.load("session-3", "user-1")
        state.active_task = {"id": "task-draft-3", "domain": "contact_import", "artifact": {"id": "draft-3", "revision": 4}, "workItems": [], "decisions": [], "completedOperationIds": []}
        store.save(state, 0)

        class NeverCalledLLM:
            def chat(self, *_args, **_kwargs):
                raise AssertionError("stale artifacts must be rejected before planning")

        result = Agent(NeverCalledLLM(), import_draft_skill(), store, Settings(max_steps=1)).run(
            "session-3", "user-1", "继续", import_summary={"rows": []}, import_artifact={"id": "draft-3", "revision": 3},
        )

        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["code"], "AGENT_ARTIFACT_REVISION_CONFLICT")


if __name__ == "__main__":
    unittest.main()
