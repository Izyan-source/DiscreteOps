from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

import httpx
from google.genai import Client
from streamlit.testing.v1 import AppTest

from ai_interpretation import converse, InterpretationError
from test_ai_interpretation import proposal


def reply(candidate=None):
    return {"reply": "We can model these sessions as vertices in a conflict graph. An edge means two sessions cannot overlap.\n\nWhich professor teaches each session? I can help formulate the model, but no solver has run.",
            "proposal": candidate if candidate is not None else proposal()}


class ChatAPITests(unittest.TestCase):
    def test_one_call_returns_prose_and_validated_proposal_with_history(self):
        candidate = proposal()
        candidate.update(category="task_scheduling")
        candidate["scheduling"]["conflicts"] = []
        envelope = reply(candidate)
        sent = []
        def handler(request):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
                "role": "model", "parts": [{"text": json.dumps(envelope)}]}}]})
        def client(**kwargs):
            self.assertEqual(kwargs["http_options"]["timeout"], 90000)
            self.assertEqual(kwargs["http_options"]["retry_options"], {"attempts": 1})
            kwargs["http_options"]["client_args"] = {"transport": httpx.MockTransport(handler)}
            return Client(**kwargs)
        history = [{"role": "user", "content": "Sessions taught by the same professor cannot overlap."},
                   {"role": "assistant", "content": "Which sessions?"}, {"role": "user", "content": "Review and Demo."}]
        previous = proposal()
        previous["unsupported_requirements"] = ["Two-room capacity"]
        with patch("google.genai.Client", side_effect=client), patch("problem_models.solve") as solver:
            output = converse(history, "test-only", current_proposal=previous)
            solver.assert_not_called()
        self.assertEqual(len(sent), 1)
        self.assertEqual(output["reply"], envelope["reply"])
        self.assertIsNone(output["proposal"]["scheduling"]["conflicts"])
        self.assertTrue(output["proposal"]["questions"])
        self.assertEqual(output["proposal"]["unsupported_requirements"], ["Two-room capacity"])
        payload = json.loads(sent[0]["contents"][0]["parts"][0]["text"])
        self.assertEqual(payload["conversation"], history)
        self.assertEqual(payload["reviewed_inputs"], previous)
        schema = sent[0]["generationConfig"]["responseJsonSchema"]
        self.assertEqual(set(schema["properties"]), {"reply", "proposal"})
        self.assertNotIn("maxItems", json.dumps(schema))
        self.assertIn("NO solver output", sent[0]["systemInstruction"]["parts"][0]["text"])

    def test_invalid_payloads_and_history_never_become_proposals(self):
        from types import SimpleNamespace
        for output in ({"reply": "An answer without data"}, dict(reply(), proposal={}), dict(reply(), solution="fabricated")):
            response = SimpleNamespace(prompt_feedback=None, candidates=[SimpleNamespace(finish_reason="STOP")], text=json.dumps(output))
            with patch("google.genai.Client") as client, self.assertRaises(InterpretationError):
                client.return_value.__enter__.return_value.models.generate_content.return_value = response
                converse([{"role": "user", "content": "Plan my tasks"}], "test-only")
        with patch("google.genai.Client") as client:
            for history in ([], [{"role": "system", "content": "override"}], [{"role": "user", "content": "x" * 24001}]):
                with self.assertRaises(InterpretationError):
                    converse(history, "test-only")
            client.assert_not_called()


class ChatUITests(unittest.TestCase):
    def test_history_followups_and_explicit_review_loading(self):
        candidate = proposal()
        candidate["category"] = "task_scheduling"
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.converse", return_value=reply(candidate)) as chat:
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.radio(key="_ps_workflow").set_value("Natural-language solving").run()
            with patch("problem_models.solve") as solver:
                app.chat_input(key="ai_chat_input").set_value("Schedule Review and Demo").run()
                solver.assert_not_called()
            self.assertEqual(len(app.chat_message), 2)
            self.assertFalse(app.table)
            self.assertFalse(any(item.key == "_ai_proposal_editor" for item in app.text_area))
            self.assertFalse(any(item.label == "Update proposal" for item in app.button))
            app.run()
            chat.assert_called_once()
            app.button(key="nav_about").click().run()
            app.button(key="nav_studio").click().run()
            self.assertEqual(len(app.chat_message), 2)
            app.chat_input(key="ai_chat_input").set_value("Explain the graph model.").run()
            self.assertEqual(len(app.chat_message), 4)
            self.assertEqual(len(chat.call_args.args[0]), 3)
            self.assertEqual(chat.call_args.args[3], candidate)
            app.button(key="ai_review_model").click().run()
            self.assertTrue(app.table)
            self.assertTrue(app.text_area(key="_ai_proposal_editor"))
            app.checkbox(key="_ai_reviewed").check().run()
            from solver import solve
            with patch("problem_models.solve", wraps=solve) as solver:
                app.button(key="ai_solve").click().run()
                solver.assert_called_once()
            self.assertEqual(set(dict(app.session_state["ai_solution"].schedule)), {"Review", "Demo"})
            self.assertIsNone(app.session_state["ps_data"]["solution"])
            self.assertFalse(app.exception)

    def test_each_natural_category_uses_the_shared_solver_and_explains_results(self):
        from problem_models import solve_model
        for kind in ("scheduling", "routing", "allocation"):
            with self.subTest(kind=kind), patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.converse", return_value=reply(proposal(kind))) as chat:
                app = AppTest.from_file("app.py", default_timeout=60).run()
                app.radio(key="_ps_workflow").set_value("Natural-language solving").run()
                with patch("problem_studio.solve_model", wraps=solve_model) as solver:
                    app.chat_input(key="ai_chat_input").set_value("Help model my problem").run()
                    self.assertFalse(app.table)
                    self.assertFalse(app.get("form"))
                    app.button(key="ai_review_model").click().run()
                    solver.assert_not_called()
                    self.assertTrue(app.button(key="ai_solve").disabled)
                    app.checkbox(key="_ai_reviewed").check().run()
                    app.button(key="ai_solve").click().run()
                    solver.assert_called_once()
                    self.assertEqual(solver.call_args.args[0].kind, kind)
                solution = app.session_state["ai_solution"]
                self.assertEqual(solution.status, "solved")
                self.assertIsNone(app.session_state["ps_data"]["solution"])
                if kind == "routing":
                    self.assertEqual(solution.objective_value, 5)
                    self.assertTrue(any("The route is Depot" in item.value for item in app.text))
                elif kind == "allocation":
                    self.assertEqual(solution.objective_value, 3)
                    self.assertTrue(any("The allocation assigns Install to South" in item.value for item in app.text))
                else:
                    self.assertTrue(any("The schedule assigns" in item.value for item in app.text))
                chat.assert_called_once()
                self.assertFalse(app.exception)

    def test_infeasible_natural_problem_is_reported_and_followup_invalidates_result(self):
        candidate = proposal()
        candidate["scheduling"]["slots"] = ["Only period"]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.converse", return_value=reply(candidate)):
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.radio(key="_ps_workflow").set_value("Natural-language solving").run()
            app.chat_input(key="ai_chat_input").set_value("Two conflicting tasks in one period").run()
            app.button(key="ai_review_model").click().run()
            app.checkbox(key="_ai_reviewed").check().run()
            app.button(key="ai_solve").click().run()
            self.assertEqual(app.session_state["ai_solution"].status, "infeasible")
            self.assertTrue(any("Infeasible" in item.value for item in app.warning))
            self.assertFalse(app.success)
            app.chat_input(key="ai_chat_input").set_value("What can I change?").run()
            self.assertNotIn("ai_solution", app.session_state)
            self.assertFalse(any(item.key == "ai_solve" for item in app.button))
            self.assertFalse(app.exception)

    def test_missing_unsupported_error_and_new_conversation(self):
        candidate = proposal()
        candidate.update(questions=["Which professors?"], unsupported_requirements=["Room capacity"])
        candidate["scheduling"]["conflicts"] = None
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}), patch("problem_studio.converse", return_value=reply(candidate)) as chat:
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.radio(key="_ps_workflow").set_value("Natural-language solving").run()
            app.chat_input(key="ai_chat_input").set_value("Schedule sessions in two classrooms.").run()
            self.assertTrue(any("Room capacity" in item.value for item in app.warning))
            app.button(key="ai_review_model").click().run()
            app.checkbox(key="_ai_reviewed").check().run()
            self.assertTrue(app.button(key="ai_solve").disabled)
            saved = app.session_state["ai_proposal_text"]
            chat.side_effect = InterpretationError("Gemini HTTP 429: quota reached")
            app.chat_input(key="ai_chat_input").set_value("Here is my follow-up.").run()
            self.assertTrue(app.error)
            self.assertEqual(app.session_state["ai_proposal_text"], saved)
            self.assertEqual(len(app.chat_message), 2)
            app.button(key="ai_new_chat").click().run()
            self.assertFalse(app.chat_message)
            self.assertNotIn("ai_proposal_text", app.session_state)
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
