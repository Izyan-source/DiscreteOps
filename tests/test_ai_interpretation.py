from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI
from streamlit.testing.v1 import AppTest

from ai_interpretation import InterpretationError, apply_proposal, interpret, parse_proposal, proposal_inputs
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
        body = dict(id="resp_test", object="response", created_at=0, status="completed", model="gpt-4.1-mini",
                    output=[dict(type="message", id="msg_test", role="assistant", status="completed",
                                 content=[dict(type="output_text", text=json.dumps(proposal()), annotations=[])])])

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=body)

        def factory(**kwargs):
            self.assertEqual(kwargs["max_retries"], 0)
            self.assertEqual(kwargs["timeout"], 30)
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        with patch("openai.OpenAI", side_effect=factory):
            self.assertEqual(interpret("my problem", "test-secret"), proposal())
        sent = json.loads(requests[0].content)
        self.assertEqual(requests[0].url.path, "/v1/responses")
        self.assertEqual(sent["input"], "my problem")
        self.assertFalse(sent["store"])
        self.assertTrue(sent["text"]["format"]["strict"])
        self.assertNotIn("tools", sent)
        for status, phrase in ((401, "authentication"), (429, "quota"), (500, "request failed")):
            def failing(request):
                return httpx.Response(status, json={"error": {"message": "test-secret PRIVATE RESPONSE"}})
            with patch("openai.OpenAI", side_effect=lambda **kw: OpenAI(**kw, http_client=httpx.Client(transport=httpx.MockTransport(failing)))):
                with self.assertRaisesRegex(InterpretationError, phrase) as caught:
                    interpret("my problem", "test-secret")
                self.assertNotIn("test-secret", str(caught.exception))
        for status, output, phrase in (("incomplete", [], "incomplete"),
                                      ("completed", [dict(type="message", id="msg", role="assistant", status="completed", content=[dict(type="refusal", refusal="no")])], "declined")):
            body.update(status=status, output=output)
            with patch("openai.OpenAI", side_effect=factory), self.assertRaisesRegex(InterpretationError, phrase):
                interpret("my problem", "test-secret")
        with self.assertRaisesRegex(InterpretationError, "Configure"):
            interpret("my problem", "")
        def timeout(request):
            raise httpx.ReadTimeout("test-secret", request=request)
        with patch("openai.OpenAI", side_effect=lambda **kw: OpenAI(**kw, http_client=httpx.Client(transport=httpx.MockTransport(timeout)))):
            with self.assertRaisesRegex(InterpretationError, "could not be reached"):
                interpret("my problem", "test-secret")

    def test_server_settings_use_environment_then_secrets(self):
        with patch.dict(os.environ, {}, clear=True), patch("problem_studio.st.secrets", {"OPENAI_API_KEY": "secret-file"}):
            self.assertEqual(_ai_setting("OPENAI_API_KEY"), "secret-file")
            self.assertEqual(_ai_setting("DISCRETEOPS_AI_MODEL", "default"), "default")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "environment"}):
                self.assertEqual(_ai_setting("OPENAI_API_KEY"), "environment")


class AIStudioTests(unittest.TestCase):
    def test_api_error_preserves_existing_manual_solution(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch("problem_studio.interpret", side_effect=InterpretationError("The AI service could not be reached in time.")):
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
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch("problem_studio.interpret", return_value=proposal("routing")) as llm:
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

    def test_errors_ambiguity_navigation_and_stale_proposals(self):
        ambiguous = proposal()
        ambiguous["questions"] = ["Do these tasks have deadlines?"]
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch("problem_studio.interpret", return_value=ambiguous) as llm:
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
