from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

import httpx
from google.genai import Client
from streamlit.testing.v1 import AppTest

from ai_interpretation import DEFAULT_MODEL, SCHEMA, InterpretationError, apply_proposal, interpret, parse_proposal, proposal_inputs
from problem_models import PROBLEM_TYPES, solve_model
from problem_studio import _ai_setting


def proposal(kind="scheduling"):
    result = dict(category=kind, summary="Proposed inputs only", assumptions=[], questions=[],
                  unsupported_requirements=[], scheduling=None, routing=None, allocation=None)
    result[kind] = {
        "scheduling": dict(tasks=["Review", "Demo"], slots=["AM", "PM"],
                           conflicts=[dict(first="Review", second="Demo")], goal="feasible"),
        "routing": dict(nodes=["Depot", "Hub", "Airport"], source="Depot", target="Airport",
                        connections=[dict(first="Depot", second="Hub", cost=3), dict(first="Hub", second="Airport", cost=2)]),
        "allocation": dict(resources=[dict(name="North", capacity=2), dict(name="South", capacity=2)],
                           tasks=[dict(name="Install", requirement=2, eligible=["North", "South"])],
                           goal="min_cost", costs=[dict(task="Install", resource="North", cost=5),
                                                   dict(task="Install", resource="South", cost=3)]),
    }[kind]
    return result


def studio_state():
    data = {"kind": "Task scheduling", "description": "my problem", "model": None, "solution": None}
    for definition in PROBLEM_TYPES.values():
        data.update(deepcopy(definition.input_defaults))
    return {"ps_data": data}


class InterpretationTests(unittest.TestCase):
    def test_proposals_reuse_builders_and_solve_only_after_acceptance(self):
        for kind in ("scheduling", "routing", "allocation"):
            state = studio_state()
            state["ps_data"]["slots"] = "My saved slot"
            state["_ps_kind"] = "old widget"
            with self.subTest(kind=kind), patch("problem_models.solve") as scheduler, patch("problem_models.traverse") as graph, patch("problem_models.solve_allocation") as allocator:
                inputs, model = proposal_inputs(proposal(kind))
                self.assertEqual(model.kind, kind)
                apply_proposal(state, json.dumps(proposal(kind)), "my problem")
                scheduler.assert_not_called()
                graph.assert_not_called()
                allocator.assert_not_called()
            self.assertNotIn("_ps_kind", state)
            self.assertIsNone(state["ps_data"]["solution"])
            self.assertIsNone(state["ps_data"]["model"])
            if kind != "scheduling":
                self.assertEqual(state["ps_data"]["slots"], "My saved slot")
            result = solve_model(PROBLEM_TYPES[kind].build_model(inputs))
            self.assertEqual(result.status, "solved")
            if kind == "routing":
                self.assertEqual(result.objective_value, 5)
            elif kind == "allocation":
                self.assertEqual(result.objective_value, 3)

    def test_public_categories_map_to_existing_workflows(self):
        for category, kind in (("task_scheduling", "scheduling"), ("network_routing", "routing"),
                               ("resource_allocation", "allocation")):
            with self.subTest(category=category):
                candidate = proposal(kind)
                candidate["category"] = category
                parsed = parse_proposal(json.dumps(candidate))
                inputs, model = proposal_inputs(parsed)
                self.assertEqual(model.kind, kind)
                state = studio_state()
                apply_proposal(state, json.dumps(candidate), "my problem")
                self.assertEqual(state["ps_data"]["kind"], PROBLEM_TYPES[kind].label)
                self.assertEqual(solve_model(PROBLEM_TYPES[kind].build_model(inputs)).status, "solved")

    def test_classroom_scheduling_retains_unsupported_rules_and_questions(self):
        candidate = proposal()
        candidate.update(category="task_scheduling",
                         questions=["Which professor teaches each session?"],
                         unsupported_requirements=["Two-classroom capacity", "Proving minimum time slots"])
        candidate["scheduling"].update(tasks=["A", "B", "C", "D"], conflicts=[dict(first="A", second="B")], goal="fewest_slots")
        parsed = parse_proposal(json.dumps(candidate))
        _, model = proposal_inputs(parsed)
        self.assertEqual(model.kind, "scheduling")
        self.assertFalse(model.supported)
        self.assertEqual(parsed["scheduling"]["goal"], "fewest_slots")
        state = studio_state()
        before = deepcopy(state)
        with self.assertRaisesRegex(InterpretationError, "Resolve the open questions"):
            apply_proposal(state, json.dumps(candidate), "my problem")
        self.assertEqual(state, before)
        candidate.update(questions=[], unsupported_requirements=[])
        with self.assertRaisesRegex(InterpretationError, "Model only"):
            apply_proposal(state, json.dumps(candidate), "my problem")

    def test_category_does_not_bypass_missing_inputs_or_section_checks(self):
        for category, kind in (("task_scheduling", "scheduling"), ("network_routing", "routing"),
                               ("resource_allocation", "allocation")):
            candidate = proposal(kind)
            candidate.update(category=category, questions=["Clarify missing inputs"])
            with self.assertRaises(InterpretationError):
                apply_proposal(studio_state(), json.dumps(candidate), "my problem")
            candidate[kind] = None
            with self.assertRaises(InterpretationError):
                proposal_inputs(candidate)
        candidate = proposal()
        candidate.update(category="unsupported", scheduling=None)
        self.assertEqual(parse_proposal(json.dumps(candidate))["category"], "unsupported")
        with self.assertRaises(InterpretationError):
            proposal_inputs(candidate)
        candidate["category"] = "forecasting"
        with self.assertRaises(InterpretationError):
            parse_proposal(json.dumps(candidate))

    def test_ambiguous_unsupported_and_stale_proposals_never_replace_inputs(self):
        variants = []
        for field in ("questions", "unsupported_requirements"):
            candidate = proposal()
            candidate[field] = ["What about deadlines?"]
            variants.append(candidate)
        candidate = proposal()
        candidate["scheduling"]["goal"] = "fewest_slots"
        variants.append(candidate)
        candidate = proposal()
        candidate.update(category="unsupported", scheduling=None)
        variants.append(candidate)
        for candidate in variants:
            state = studio_state()
            before = deepcopy(state)
            with self.assertRaises(ValueError):
                apply_proposal(state, json.dumps(candidate), "my problem")
            self.assertEqual(state, before)
        with self.assertRaisesRegex(InterpretationError, "description changed"):
            apply_proposal(studio_state(), json.dumps(proposal()), "an old problem")

    def test_invalid_missing_and_fabricated_result_fields_are_rejected(self):
        variants = []
        candidate = proposal("routing")
        candidate["routing"]["connections"][0]["cost"] = None
        variants.append(candidate)
        candidate = proposal("allocation")
        candidate["allocation"]["tasks"][0]["eligible"] = None
        variants.append(candidate)
        candidate = proposal("allocation")
        candidate["allocation"]["resources"][0]["capacity"] = None
        variants.append(candidate)
        candidate = proposal("allocation")
        candidate["allocation"]["costs"].pop()
        variants.append(candidate)
        candidate = proposal()
        candidate["scheduling"]["tasks"] = ["A\nB", "C"]
        variants.append(candidate)
        candidate = proposal()
        candidate["solution"] = {"assignments": "AI claimed success"}
        variants.append(candidate)
        candidate = proposal("routing")
        candidate["routing"]["connections"][0]["cost"] = True
        variants.append(candidate)
        for candidate in variants:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                proposal_inputs(parse_proposal(json.dumps(candidate)))
        with self.assertRaises(InterpretationError):
            parse_proposal("not json")

    def test_real_sdk_serialization_and_provider_failures_without_network(self):
        requests = []
        body = {"candidates": [{"finishReason": "STOP", "content": {
            "role": "model", "parts": [{"text": json.dumps(proposal())}]}}]}

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=body)

        def factory(transport):
            def create(**kwargs):
                self.assertFalse(kwargs["vertexai"])
                self.assertEqual(kwargs["http_options"]["retry_options"], {"attempts": 1})
                self.assertEqual(kwargs["http_options"]["timeout"], 90000)
                kwargs["http_options"]["client_args"] = {"transport": httpx.MockTransport(transport)}
                return Client(**kwargs)
            return create

        with patch("google.genai.Client", side_effect=factory(handler)):
            self.assertEqual(interpret("my problem", "test-secret"), proposal())
        sent = json.loads(requests[0].content)
        self.assertEqual(requests[0].url.path, f"/v1beta/models/{DEFAULT_MODEL}:generateContent")
        self.assertEqual(requests[0].headers["x-goog-api-key"], "test-secret")
        self.assertEqual(sent["contents"][0]["parts"][0]["text"], "my problem")
        from ai_interpretation import _generation_schema
        expected_schema = _generation_schema(SCHEMA)
        expected_schema["properties"]["category"]["enum"] = ["task_scheduling", "network_routing", "resource_allocation", "unsupported"]
        self.assertEqual(sent["generationConfig"]["responseJsonSchema"], expected_schema)
        prompt = sent["systemInstruction"]["parts"][0]["text"]
        self.assertIn("Classify the primary decision separately", prompt)
        self.assertIn("is task_scheduling with goal fewest_slots", prompt)
        self.assertIn("Classroom counts are NOT time slots", prompt)
        self.assertNotIn("maxItems", json.dumps(sent["generationConfig"]["responseJsonSchema"]))
        oversized = proposal()
        oversized["assumptions"] = ["assumption"] * 21
        with self.assertRaises(InterpretationError):
            parse_proposal(json.dumps(oversized))
        self.assertEqual(sent["generationConfig"]["responseMimeType"], "application/json")
        self.assertNotIn("tools", sent)
        for status, phrase in ((400, "rejected"), (401, "authentication"), (403, "access"),
                               (429, "quota"), (500, "request failed"), (504, "could not be reached")):
            def failing(request):
                requests.append(request)
                return httpx.Response(status, json={"error": {"code": status, "message": "test-secret PRIVATE RESPONSE"}})
            before = len(requests)
            with patch("google.genai.Client", side_effect=factory(failing)):
                with self.assertRaisesRegex(InterpretationError, phrase) as caught:
                    interpret("my problem", "test-secret")
                self.assertNotIn("test-secret", str(caught.exception))
                self.assertIn(f"Gemini HTTP {status}:", str(caught.exception))
                self.assertIn("PRIVATE RESPONSE", str(caught.exception))
            self.assertEqual(len(requests), before + 1)
        for payload, phrase in (
            ({"candidates": [{"finishReason": "MAX_TOKENS"}]}, "incomplete"),
            ({"candidates": [{"finishReason": "SAFETY"}]}, "declined"),
            ({"promptFeedback": {"blockReason": "SAFETY"}}, "declined"),
            ({"candidates": []}, "incomplete"),
            ({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "bad JSON"}]}}]}, "not valid JSON"),
        ):
            body = payload
            with patch("google.genai.Client", side_effect=factory(handler)), self.assertRaisesRegex(InterpretationError, phrase):
                interpret("my problem", "test-secret")
        with self.assertRaisesRegex(InterpretationError, "Configure"):
            interpret("my problem", "")
        def timeout(request):
            raise httpx.ReadTimeout("test-secret", request=request)
        with patch("google.genai.Client", side_effect=factory(timeout)):
            with self.assertRaisesRegex(InterpretationError, "could not be reached"):
                interpret("my problem", "test-secret")

    def test_provider_diagnostics_redact_credentials_and_headers(self):
        from google.genai.errors import APIError
        from ai_interpretation import _provider_detail

        error = APIError(400, {"error": {"message": (
            "Invalid schema: maxItems is too large. test-secret\n"
            "Authorization: Bearer hidden-token\n"
            "x-goog-api-key: another-key\n"
            "Request headers: private headers\n"
            "URL ?key=another-secret&other=ok AIzaExampleCredential"
        )}})
        detail = _provider_detail(error, "test-secret")
        self.assertIn("Gemini HTTP 400", detail)
        self.assertIn("Invalid schema: maxItems is too large", detail)
        for secret in ("test-secret", "hidden-token", "another-key", "private headers",
                       "another-secret", "AIzaExampleCredential"):
            self.assertNotIn(secret, detail)
        self.assertNotIn("Authorization", detail)

    def test_exact_classroom_description_keeps_missing_professor_assignments_unresolved(self):
        from types import SimpleNamespace
        text = "Schedule 4 sessions across 2 classrooms. Sessions taught by the same professor cannot overlap. Minimize time slots."
        candidate = proposal()
        candidate.update(category="task_scheduling")
        candidate["scheduling"]["conflicts"] = []
        candidate["scheduling"]["goal"] = "fewest_slots"
        with patch("google.genai.Client") as client:
            client.return_value.__enter__.return_value.models.generate_content.return_value = SimpleNamespace(
                prompt_feedback=None, candidates=[SimpleNamespace(finish_reason="STOP")], text=json.dumps(candidate))
            result = interpret(text, "test-only")
        self.assertIsNone(result["scheduling"]["conflicts"])
        self.assertTrue(any("Which professor teaches each session" in q for q in result["questions"]))
        self.assertEqual(result["scheduling"]["goal"], "fewest_slots")

    def test_server_settings_use_environment_then_secrets(self):
        with patch.dict(os.environ, {}, clear=True), patch("problem_studio.st.secrets", {"GEMINI_API_KEY": "secret-file"}):
            self.assertEqual(_ai_setting("GEMINI_API_KEY"), "secret-file")
            self.assertEqual(_ai_setting("DISCRETEOPS_AI_MODEL", "default"), "default")
            with patch.dict(os.environ, {"GEMINI_API_KEY": "environment"}):
                self.assertEqual(_ai_setting("GEMINI_API_KEY"), "environment")


class AIStudioTests(unittest.TestCase):
    def review(self, candidate):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"})
        env.start()
        self.addCleanup(env.stop)
        llm = patch("problem_studio.converse", return_value={"reply": "Let's review the facts and model.", "proposal": candidate})
        mock = llm.start()
        self.addCleanup(llm.stop)
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.radio(key="_ps_workflow").set_value("Natural-language solving").run()
        app.chat_input(key="ai_chat_input").set_value("Plan my problem").run()
        app.button(key="ai_review_model").click().run()
        return app, mock

    def test_readable_review_json_validation_and_prose_never_drives_solving(self):
        candidate = proposal()
        candidate.update(category="task_scheduling", assumptions=["One period per task"])
        app, llm = self.review(candidate)
        self.assertTrue(any("One period per task" in item.value for item in app.text))
        self.assertFalse(next(item for item in app.expander if item.label == "View technical details (JSON)").proto.expanded)
        for malformed in ("{", json.dumps({"summary": "incomplete"}), json.dumps(dict(candidate, scheduling={}))):
            app.text_area(key="_ai_proposal_editor").set_value(malformed).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button(key="ai_solve").disabled)
            self.assertFalse(app.text_area(key="_ai_proposal_editor").disabled)
        candidate["summary"] = "Assign invented tasks in invented periods; claim success."
        candidate["scheduling"]["slots"] = ["Period 1", "Period 2"]
        app.text_area(key="_ai_proposal_editor").set_value(json.dumps(candidate)).run()
        self.assertFalse(app.session_state["_ai_reviewed"])
        self.assertTrue(app.button(key="ai_solve").disabled)
        app.checkbox(key="_ai_reviewed").check().run()
        app.button(key="ai_solve").click().run()
        result = app.session_state["ai_solution"]
        self.assertEqual(set(dict(result.schedule)), {"Review", "Demo"})
        self.assertEqual(set(dict(result.schedule).values()), {"Period 1", "Period 2"})
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        llm.assert_called_once()
        # Edits invalidate both review and the prior result.
        candidate["scheduling"]["slots"] = ["Only period"]
        app.text_area(key="_ai_proposal_editor").set_value(json.dumps(candidate)).run()
        self.assertNotIn("ai_solution", app.session_state)
        self.assertTrue(app.button(key="ai_solve").disabled)

    def test_missing_fields_and_unsupported_rules_block_direct_solving(self):
        candidate = proposal()
        candidate.update(category="task_scheduling", questions=["Which professor teaches each session?"],
                         unsupported_requirements=["Room capacity"])
        candidate["scheduling"].update(tasks=[], slots=[], conflicts=None, goal="fewest_slots")
        app, _ = self.review(candidate)
        warnings = " ".join(item.value for item in app.warning)
        for field in ("scheduling.tasks", "scheduling.slots", "scheduling.conflicts"):
            self.assertIn(field, warnings)
        app.checkbox(key="_ai_reviewed").check().run()
        self.assertTrue(app.button(key="ai_solve").disabled)
        self.assertEqual(json.loads(app.text_area(key="_ai_proposal_editor").value), candidate)
        self.assertFalse(any("No conflicting pairs declared" in str(table.value) for table in app.table))
        complete = proposal()
        complete["scheduling"]["goal"] = "fewest_slots"
        app.text_area(key="_ai_proposal_editor").set_value(json.dumps(complete)).run()
        self.assertTrue(app.button(key="ai_solve").disabled)
        self.assertTrue(any("cannot prove the fewest slots" in item.value for item in app.warning))
        self.assertFalse(app.exception)

    def test_api_error_preserves_manual_solution_and_blocks_old_chat_model(self):
        candidate = proposal()
        app, llm = self.review(candidate)
        app.radio(key="_ps_workflow").set_value("Manual structured solving").run()
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.button(key="ps_example").click().run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        saved = deepcopy(app.session_state["ps_data"])
        app.radio(key="_ps_workflow").set_value("Natural-language solving").run()
        llm.side_effect = InterpretationError("Gemini HTTP 429: quota reached")
        app.chat_input(key="ai_chat_input").set_value("A new constraint").run()
        self.assertTrue(app.error)
        app.checkbox(key="_ai_reviewed").check().run()
        self.assertTrue(app.button(key="ai_solve").disabled)
        self.assertEqual(app.session_state["ps_data"], saved)
        self.assertFalse(app.exception)

    def test_readable_facts_for_all_categories_and_missing_values(self):
        from problem_studio import _proposal_facts
        for kind, expected in (("scheduling", "Review"), ("routing", "Depot"), ("allocation", "North")):
            with self.subTest(kind=kind):
                rows, questions = _proposal_facts(proposal(kind))
                self.assertIn(expected, str(rows))
                self.assertFalse(questions)
        candidate = proposal("allocation")
        candidate["allocation"]["resources"][0]["capacity"] = 0
        candidate["allocation"]["costs"].pop()
        rows, questions = _proposal_facts(candidate)
        self.assertTrue(any(row["Extracted input"] == "0" for row in rows))
        self.assertTrue(any("Install to South" in question for question in questions))
        candidate = proposal("routing")
        candidate["routing"]["source"] = None
        self.assertIn("Where should the route start?", _proposal_facts(candidate)[1])

    def test_professor_guard_preserves_known_pairs_and_unrelated_empty_conflicts(self):
        from ai_interpretation import _clarify_professor_conflicts
        known = proposal()
        self.assertEqual(_clarify_professor_conflicts(deepcopy(known),
                         "Sessions taught by the same professor cannot overlap."), known)
        empty = proposal()
        empty["scheduling"]["conflicts"] = []
        self.assertEqual(_clarify_professor_conflicts(deepcopy(empty), "No task conflicts; any schedule is fine."), empty)
        state = studio_state()
        # An explicitly reviewed empty conflict list remains valid; no solver is run.
        apply_proposal(state, json.dumps(empty), "my problem")
        self.assertEqual(state["ps_data"]["conflicts"], [])
        self.assertIsNone(state["ps_data"]["solution"])


if __name__ == "__main__":
    unittest.main()
