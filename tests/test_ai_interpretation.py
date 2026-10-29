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

    def test_server_settings_use_environment_then_secrets(self):
        with patch.dict(os.environ, {}, clear=True), patch("problem_studio.st.secrets", {"GEMINI_API_KEY": "secret-file"}):
            self.assertEqual(_ai_setting("GEMINI_API_KEY"), "secret-file")
            self.assertEqual(_ai_setting("DISCRETEOPS_AI_MODEL", "default"), "default")
            with patch.dict(os.environ, {"GEMINI_API_KEY": "environment"}):
                self.assertEqual(_ai_setting("GEMINI_API_KEY"), "environment")


class AIStudioTests(unittest.TestCase):
    def test_description_is_editable_and_ai_tracks_committed_text_across_reruns(self):
        with patch("problem_studio._ai_setting", return_value="test-only"), patch("problem_studio.interpret") as llm:
            app = AppTest.from_file("app.py", default_timeout=60).run()
            self.assertFalse(app.text_area(key="_ps_description").disabled)
            self.assertTrue(app.button(key="ai_interpret").disabled)
            text = "Schedule a review and a demo.\nUse morning and afternoon slots."
            app.text_area(key="_ps_description").set_value(text).run()
            self.assertEqual(app.session_state["ps_data"]["description"], text)
            self.assertFalse(app.button(key="ai_interpret").disabled)
            app.run()
            self.assertEqual(app.text_area(key="_ps_description").value, text)
            app.button(key="nav_about").click().run()
            app.button(key="nav_studio").click().run()
            self.assertEqual(app.text_area(key="_ps_description").value, text)
            self.assertFalse(app.text_area(key="_ps_description").disabled)
            self.assertFalse(app.button(key="ai_interpret").disabled)
            app.text_area(key="_ps_description").set_value("  \n").run()
            self.assertTrue(app.button(key="ai_interpret").disabled)
            llm.assert_not_called()
            self.assertFalse(app.exception)

    def test_api_error_preserves_existing_manual_solution(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.interpret", side_effect=InterpretationError("The AI service could not be reached in time.")):
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.radio(key="_ps_kind").set_value("Task scheduling").run()
            app.button(key="ps_example").click().run()
            app.button(key="ps_build").click().run()
            app.button(key="ps_solve").click().run()
            saved = deepcopy(app.session_state["ps_data"])
            app.text_area(key="_ps_description").set_value("Try interpreting this").run()
            app.button(key="ai_interpret").click().run()
            self.assertTrue(app.error)
            for key in ("model", "solution", "tasks", "slots", "conflicts"):
                self.assertEqual(app.session_state["ps_data"][key], saved[key])
            self.assertFalse(app.exception)

    def test_review_edit_accept_and_manual_solver_boundary(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.interpret", return_value=proposal("routing")) as llm:
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.text_area(key="_ps_description").set_value("Route from a depot via a hub to the airport.").run()
            llm.assert_not_called()
            app.button(key="ai_interpret").click().run()
            llm.assert_called_once()
            self.assertFalse(app.exception)
            self.assertTrue(app.button(key="ai_accept").disabled)
            self.assertIsNone(app.session_state["ps_data"]["model"])
            app.checkbox(key="_ai_reviewed").check().run()
            edited = proposal("routing")
            edited["routing"]["connections"][0]["cost"] = 1
            app.text_area(key="_ai_proposal_editor").set_value(json.dumps(edited)).run()
            self.assertTrue(app.button(key="ai_accept").disabled)
            app.checkbox(key="_ai_reviewed").check().run()
            with patch("problem_models.traverse") as solver:
                app.button(key="ai_accept").click().run()
                solver.assert_not_called()
            self.assertEqual(app.radio(key="_ps_kind").value, "Network routing")
            self.assertEqual(app.number_input(key="_ps_cost_('Depot', 'Hub')").value, 1)
            self.assertIsNone(app.session_state["ps_data"]["solution"])
            app.button(key="ps_build").click().run()
            app.button(key="ps_solve").click().run()
            self.assertEqual(app.session_state["ps_data"]["solution"].objective_value, 3)
            llm.assert_called_once()
            self.assertFalse(app.exception)

    def test_scheduling_missing_fields_remain_editable_then_load_exactly(self):
        candidate = proposal()
        candidate.update(category="task_scheduling", questions=["Which sessions and periods?"])
        candidate["scheduling"].update(tasks=[], slots=[], conflicts=None, goal=None)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.interpret", return_value=candidate):
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.text_area(key="_ps_description").set_value("Schedule sessions").run()
            app.button(key="ai_interpret").click().run()
            warnings = " ".join(item.value for item in app.warning)
            for field in ("scheduling.tasks", "scheduling.slots", "scheduling.conflicts", "scheduling.goal"):
                self.assertIn(field, warnings)
            self.assertFalse(app.text_area(key="_ai_proposal_editor").disabled)
            self.assertTrue(app.button(key="ai_accept").disabled)
            self.assertEqual(len(app.table), 1)
            complete = proposal()
            complete["category"] = "task_scheduling"
            app.text_area(key="_ai_proposal_editor").set_value(json.dumps(complete)).run()
            app.checkbox(key="_ai_reviewed").check().run()
            self.assertFalse(app.button(key="ai_accept").disabled)
            with patch("problem_models.solve") as solver:
                app.button(key="ai_accept").click().run()
                solver.assert_not_called()
            data = app.session_state["ps_data"]
            self.assertEqual(app.radio(key="_ps_kind").value, "Task scheduling")
            self.assertEqual(data["tasks"], "Review\nDemo")
            self.assertEqual(data["slots"], "AM\nPM")
            self.assertEqual(data["conflicts"], [("Review", "Demo")])
            self.assertEqual(data["goal"], "feasible")
            self.assertIsNone(data["solution"])
            self.assertFalse(app.exception)

    def test_scheduling_review_preserves_room_rules_and_model_only_objective(self):
        candidate = proposal()
        candidate.update(category="task_scheduling", unsupported_requirements=["Assign rooms within two-classroom capacity"])
        candidate["scheduling"]["goal"] = "fewest_slots"
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.interpret", return_value=candidate):
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.text_area(key="_ps_description").set_value("Schedule sessions in two rooms, minimize periods").run()
            app.button(key="ai_interpret").click().run()
            app.checkbox(key="_ai_reviewed").check().run()
            warnings = " ".join(item.value for item in app.warning)
            self.assertIn("Loading is blocked", warnings)
            self.assertIn("cannot prove the fewest slots", warnings)
            self.assertTrue(app.button(key="ai_accept").disabled)
            self.assertEqual(json.loads(app.text_area(key="_ai_proposal_editor").value), candidate)
            self.assertIsNone(app.session_state["ps_data"]["solution"])
            self.assertFalse(app.exception)

    def test_errors_ambiguity_navigation_and_stale_proposals(self):
        ambiguous = proposal()
        ambiguous["questions"] = ["Do these tasks have deadlines?"]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.interpret", return_value=ambiguous) as llm:
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.text_area(key="_ps_description").set_value("Plan the tasks").run()
            app.button(key="ai_interpret").click().run()
            app.checkbox(key="_ai_reviewed").check().run()
            self.assertTrue(app.button(key="ai_accept").disabled)
            app.button(key="nav_about").click().run()
            app.button(key="nav_studio").click().run()
            self.assertEqual(json.loads(app.text_area(key="_ai_proposal_editor").value)["questions"], ambiguous["questions"])
            app.text_area(key="_ps_description").set_value("A revised problem").run()
            self.assertTrue(app.button(key="ai_accept").disabled)
            self.assertTrue(any("description changed" in item.value for item in app.warning))
            llm.side_effect = InterpretationError("AI quota or rate limit reached.")
            app.button(key="ai_interpret").click().run()
            self.assertTrue(app.error)
            self.assertIsNone(app.session_state["ps_data"]["model"])
            self.assertFalse(any(button.key == "ai_accept" for button in app.button))
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
