from copy import deepcopy
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from allocation_solver import solve_allocation
from explanations import solution_status
from graph_algorithms import traverse
from problem_models import PROBLEM_TYPES, allocation_model, routing_model, scheduling_model, solve_model
from problem_studio import WORKFLOWS
from solver import solve


class UnifiedWorkflowTests(unittest.TestCase):
    def app(self):
        return AppTest.from_file("app.py", default_timeout=60).run()

    def test_two_workflows_have_distinct_entry_points(self):
        app = self.app()
        self.assertEqual(app.radio(key="_ps_workflow").options, list(WORKFLOWS))
        self.assertFalse(app.chat_input)
        self.assertFalse(any(item.key == "_ps_description" for item in app.text_area))
        app.radio(key="_ps_workflow").set_value(WORKFLOWS[1]).run()
        self.assertEqual(len(app.chat_input), 1)
        self.assertFalse(any(item.key == "_ps_kind" for item in app.radio))
        self.assertFalse(any(item.key in ("ai_interpret", "ai_accept", "ps_build") for item in app.button))
        self.assertFalse(any("Build a proposal from" in item.label for item in app.expander))
        self.assertFalse(app.exception)

    def test_examples_reset_objectives_and_preserve_other_drafts(self):
        app = self.app()
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.button(key="ps_example").click().run()
        app.selectbox(key="_ps_goal").select("fewest_slots").run()
        app.button(key="ps_example").click().run()
        self.assertEqual(app.selectbox(key="_ps_goal").value, "feasible")
        app.text_area(key="_ps_slots").set_value("One\nTwo\nThree").run()
        app.radio(key="_ps_kind").set_value("Resource allocation").run()
        app.button(key="ps_example").click().run()
        app.selectbox(key="_ps_allocation_goal").select("min_cost").run()
        app.button(key="ps_example").click().run()
        self.assertEqual(app.selectbox(key="_ps_allocation_goal").value, "feasible")
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        self.assertEqual(app.text_area(key="_ps_slots").value, "One\nTwo\nThree")
        self.assertFalse(app.exception)

    def test_each_category_uses_existing_solver_and_can_revise_without_losing_inputs(self):
        solvers = {"scheduling": ("problem_models.solve", solve),
                   "routing": ("problem_models.traverse", traverse),
                   "allocation": ("problem_models.solve_allocation", solve_allocation)}
        for slug, definition in PROBLEM_TYPES.items():
            with self.subTest(category=slug):
                app = self.app()
                app.radio(key="_ps_kind").set_value(definition.label).run()
                self.assertTrue(app.button(key="ps_build").disabled)
                self.assertTrue(app.warning)
                app.button(key="ps_example").click().run()
                saved = {key: deepcopy(app.session_state["ps_data"][key]) for key in definition.input_defaults}
                path, algorithm = solvers[slug]
                with patch(path, wraps=algorithm) as existing:
                    app.button(key="ps_build").click().run()
                    existing.assert_not_called()
                    app.button(key="ps_solve").click().run()
                    existing.assert_called_once()
                self.assertEqual(app.session_state["ps_data"]["model"].kind, slug)
                self.assertEqual(app.session_state["ps_data"]["solution"].status, "solved")
                self.assertTrue(any(item.label == "Solution explanation" for item in app.expander))
                if slug == "routing":
                    self.assertIs(app.session_state["ps_data"]["solution"].optimal, True)
                    self.assertTrue(any("Proven optimum" in item.value for item in app.success))
                else:
                    self.assertTrue(any("Feasible" in item.value for item in app.success))
                app.button(key="ps_revise").click().run()
                self.assertIsNone(app.session_state["ps_data"]["solution"])
                self.assertIsNone(app.session_state["ps_data"]["model"])
                app.button(key="nav_about").click().run()
                app.button(key="nav_studio").click().run()
                for key, value in saved.items():
                    self.assertEqual(app.session_state["ps_data"][key], value)
                app.button(key="ps_build").click().run()
                app.button(key="ps_solve").click().run()
                self.assertEqual(app.session_state["ps_data"]["solution"].status, "solved")
                self.assertFalse(app.exception)

    def test_infeasible_schedule_can_be_revised_to_feasible(self):
        app = self.app()
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.text_area(key="_ps_tasks").set_value("A\na").run()
        self.assertTrue(app.button(key="ps_build").disabled)
        self.assertTrue(any("unique" in item.value for item in app.warning))
        app.text_area(key="_ps_tasks").set_value("A\nB").run()
        app.text_area(key="_ps_slots").set_value("Morning").run()
        app.multiselect(key="_ps_conflicts").set_value([("A", "B")]).run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertTrue(any("Infeasible" in item.value for item in app.warning))
        app.button(key="ps_revise").click().run()
        app.text_area(key="_ps_slots").set_value("Morning\nAfternoon").run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertTrue(any("Feasible" in item.value for item in app.success))
        self.assertFalse(app.exception)

    def test_statuses_follow_actual_solver_outcomes(self):
        schedule = scheduling_model(["A", "B"], ["AM", "PM"], [("A", "B")])
        with patch("problem_models.solve", side_effect=lambda problem: solve(problem, max_attempts=0)):
            limited = solve_model(schedule)
        self.assertIn("Inconclusive", solution_status(limited))
        preview = AppTest.from_string("from problem_studio import _render_solution\nimport streamlit as st\n_render_solution(st.session_state.solution, st.session_state.model)")
        preview.session_state["solution"] = limited
        preview.session_state["model"] = schedule
        preview.run()
        self.assertTrue(any("Inconclusive" in item.value for item in preview.warning))
        self.assertFalse(preview.success)
        self.assertFalse(preview.exception)
        self.assertIn("Unsupported", solution_status(solve_model(scheduling_model(["A"], ["AM"], [], "fewest_slots"))))
        self.assertIn("Infeasible", solution_status(solve_model(routing_model(["A", "B"], [], "A", "B", {}))))
        model = allocation_model(["A", "B"], ["X", "Y"], {"A": 1, "B": 1},
                                 {"X": 1, "Y": 1}, {"X": ["A", "B"], "Y": ["A", "B"]}, "min_cost",
                                 {("X", "A"): 1, ("X", "B"): 2, ("Y", "A"): 1, ("Y", "B"): 100})
        with patch("problem_models.solve_allocation", side_effect=lambda problem: solve_allocation(problem, max_attempts=3)):
            incumbent = solve_model(model)
        self.assertIn("optimality not proven", solution_status(incumbent))
        self.assertIn("Proven optimum", solution_status(solve_model(model)))


if __name__ == "__main__":
    unittest.main()
