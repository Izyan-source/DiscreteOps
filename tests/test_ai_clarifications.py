"""Clarification updates preserve the structured-data boundary and review gate."""
from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from ai_interpretation import answer_proposal, apply_proposal, InterpretationError
from test_ai_interpretation import proposal, studio_state


class AnswerTests(unittest.TestCase):
    def test_partial_answers_never_resolve_questions_or_drop_constraints(self):
        original = proposal()
        original.update(questions=["Which sessions?"], unsupported_requirements=["Two-room capacity"])
        original["scheduling"].update(tasks=[], slots=[], conflicts=None)
        before = deepcopy(original)
        section = deepcopy(original["scheduling"])
        section["tasks"] = ["A", "B"]
        result = answer_proposal(original, section, {})
        self.assertEqual(original, before)
        self.assertEqual(result["questions"], before["questions"])
        self.assertEqual(result["unsupported_requirements"], before["unsupported_requirements"])
        self.assertIsNone(result["scheduling"]["conflicts"])
        with self.assertRaises(ValueError):
            answer_proposal(original, section, {0: "A and B"})
        with self.assertRaises(InterpretationError):
            apply_proposal(studio_state(), json.dumps(result), "my problem")

    def test_valid_answers_update_each_category_and_preserve_audit(self):
        for kind in ("scheduling", "routing", "allocation"):
            with self.subTest(kind=kind):
                original = proposal(kind)
                original["questions"] = ["Are the listed facts complete?"]
                result = answer_proposal(original, original[kind], {0: "Yes, these are all the facts."})
                self.assertEqual(result["questions"], [])
                self.assertIn("Are the listed facts complete?", result["assumptions"][-1])
                self.assertEqual(result[kind], original[kind])
                state = studio_state()
                apply_proposal(state, json.dumps(result), "my problem")
                self.assertIsNone(state["ps_data"]["solution"])
                with self.assertRaises(InterpretationError):
                    answer_proposal(original, original[kind], {0: " "})
                original["unsupported_requirements"] = ["Unsupported real-world rule"]
                result = answer_proposal(original, original[kind], {0: "Yes"})
                with self.assertRaises(InterpretationError):
                    apply_proposal(studio_state(), json.dumps(result), "my problem")


class AnswerFormTests(unittest.TestCase):
    def start(self, candidate):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"})
        env.start()
        self.addCleanup(env.stop)
        llm = patch("problem_studio.converse", return_value={"reply": "Please clarify the missing facts.", "proposal": candidate})
        mocked = llm.start()
        self.addCleanup(llm.stop)
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.radio(key="_ps_workflow").set_value("Natural-language solving").run()
        app.chat_input(key="ai_chat_input").set_value("My problem").run()
        app.button(key="ai_review_model").click().run()
        self.assertFalse(app.exception)
        return app, mocked

    def field(self, app, widget, suffix):
        return next(item for item in getattr(app, widget) if item.key and item.key.startswith("ai_answers_") and item.key.endswith("_" + suffix))

    def submit(self, app):
        return next(item for item in app.button if item.label == "Update proposal").click().run()

    def test_scheduling_form_resolves_professor_pairs_then_loads_without_solver(self):
        candidate = proposal()
        candidate.update(category="task_scheduling", questions=["Which sessions share a professor?"])
        candidate["scheduling"].update(tasks=[], slots=[], conflicts=None)
        app, llm = self.start(candidate)
        self.field(app, "text_area", "tasks").set_value("A\nB")
        self.field(app, "text_area", "slots").set_value("Morning\nAfternoon")
        self.field(app, "selectbox", "conflict_status").set_value("Enter conflicting pairs")
        editor_key = next(k for k in app.session_state.filtered_state if k.startswith("ai_answers_") and k.endswith("_conflicts"))
        app.session_state[editor_key] = {"edited_rows": {}, "added_rows": [{"first": "A", "second": "B"}], "deleted_rows": []}
        self.field(app, "text_input", "answer_0").set_value("A and B share the same professor; this is the only conflict.")
        self.field(app, "checkbox", "resolved_0").check()
        self.submit(app)
        self.assertFalse(app.exception)
        result = json.loads(app.session_state["ai_proposal_text"])
        self.assertEqual(result["scheduling"]["conflicts"], [{"first": "A", "second": "B"}])
        self.assertFalse(result["questions"])
        self.assertEqual(app.text_area(key="_ai_proposal_editor").value, app.session_state["ai_proposal_text"])
        self.assertTrue(app.button(key="ai_solve").disabled)
        app.checkbox(key="_ai_reviewed").check().run()
        from solver import solve
        with patch("problem_models.solve", wraps=solve) as solver:
            app.button(key="ai_solve").click().run()
            solver.assert_called_once()
        schedule = dict(app.session_state["ai_solution"].schedule)
        self.assertNotEqual(schedule["A"], schedule["B"])
        self.assertEqual(set(schedule.values()), {"Morning", "Afternoon"})
        self.assertIsNone(app.session_state["ps_data"]["model"])
        llm.assert_called_once()

    def test_routing_invalid_answer_and_json_edit_refresh_form(self):
        candidate = proposal("routing")
        candidate["questions"] = ["Where should the route start?"]
        candidate["routing"]["source"] = None
        app, _ = self.start(candidate)
        self.field(app, "text_input", "source").set_value("Unknown location")
        self.field(app, "text_input", "answer_0").set_value("Unknown location")
        self.field(app, "checkbox", "resolved_0").check()
        self.submit(app)
        self.assertTrue(any("Answers were not applied" in item.value for item in app.error))
        self.assertEqual(json.loads(app.session_state["ai_proposal_text"]), candidate)
        self.field(app, "text_input", "source").set_value("Depot")
        self.field(app, "text_input", "answer_0").set_value("Depot")
        self.submit(app)
        self.assertFalse(app.exception)
        edited = json.loads(app.session_state["ai_proposal_text"])
        edited["routing"]["source"] = "Hub"
        app.text_area(key="_ai_proposal_editor").set_value(json.dumps(edited)).run()
        self.assertEqual(self.field(app, "text_input", "source").value, "Hub")
        app.session_state["ps_chat_context"] = "Changed context"
        app.run()
        self.assertTrue(next(item for item in app.button if item.label == "Update proposal").disabled)
        self.assertTrue(app.button(key="ai_solve").disabled)

    def test_allocation_answers_preserve_unsupported_requirements(self):
        candidate = proposal("allocation")
        candidate.update(questions=["Which resources can handle Install?"], unsupported_requirements=["A deadline is required"])
        candidate["allocation"]["tasks"][0]["eligible"] = None
        app, _ = self.start(candidate)
        self.field(app, "multiselect", "eligible_0").set_value(["North", "South"])
        self.field(app, "checkbox", "eligibility_known_0").check()
        self.field(app, "text_input", "answer_0").set_value("North and South can both handle Install.")
        self.field(app, "checkbox", "resolved_0").check()
        self.submit(app)
        self.assertFalse(app.exception)
        result = json.loads(app.session_state["ai_proposal_text"])
        self.assertEqual(result["allocation"]["tasks"][0]["eligible"], ["North", "South"])
        self.assertEqual(result["unsupported_requirements"], candidate["unsupported_requirements"])
        app.checkbox(key="_ai_reviewed").check().run()
        self.assertTrue(app.button(key="ai_solve").disabled)


if __name__ == "__main__":
    unittest.main()
