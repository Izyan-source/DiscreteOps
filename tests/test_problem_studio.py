import unittest
from dataclasses import replace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from graph_algorithms import traverse
from problem_models import PROBLEM_TYPES, Solution, routing_model, scheduling_model, solve_model
from problem_studio import INPUT_RENDERERS, UNSUPPORTED_CHOICE


class ModelTests(unittest.TestCase):
    def test_registry_dispatches_explicitly_and_rejects_unknown_types(self):
        model = scheduling_model(["A"], ["Morning"], [])
        with patch("problem_models.solve") as scheduler, patch("problem_models.traverse") as bfs:
            unknown = replace(model, kind="unregistered")
            self.assertEqual(solve_model(unknown).status, "unsupported")
            scheduler.assert_not_called()
            bfs.assert_not_called()

        # An additional adapter uses the same dispatcher, without a new branch.
        expected = Solution("unsupported", "Test adapter has no solver.")
        adapter = replace(PROBLEM_TYPES["scheduling"], solve=lambda model: expected, inspector=None)
        with patch.dict(PROBLEM_TYPES, {"test_type": adapter}):
            self.assertEqual(solve_model(replace(model, kind="test_type")), expected)

    def test_schedule_model_and_verified_solution(self):
        model = scheduling_model(["Review", "Build", "Demo"], ["AM", "PM"],
                                 [("Review", "Demo"), ("Build", "Demo")])
        self.assertEqual(len(model.variables), 3)
        self.assertEqual(len(model.constraints), 5)
        self.assertEqual(model.variables[0].domain, "{s1, s2}")
        self.assertEqual(model.constraints[-1].expression, "x[2] ≠ x[3]")
        result = solve_model(model)
        assigned = dict(result.schedule)
        self.assertEqual(result.status, "solved")
        self.assertNotEqual(assigned["Review"], assigned["Demo"])
        self.assertNotEqual(assigned["Build"], assigned["Demo"])
        self.assertEqual(result.objective_value, 0)
        impossible = scheduling_model(["A", "B"], ["Only slot"], [("A", "B")])
        self.assertEqual(solve_model(impossible).status, "infeasible")

    def test_unsupported_optimization_never_calls_scheduler(self):
        model = scheduling_model(["A", "B"], ["AM", "PM"], [], "fewest_slots")
        self.assertEqual(model.objective_expression, "min |{x[1], x[2]}|")
        with patch("problem_models.solve") as scheduler:
            result = solve_model(model)
            scheduler.assert_not_called()
        self.assertFalse(model.supported)
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.values, ())
        self.assertEqual(result.schedule, ())

    def test_routing_uses_bfs_and_assigns_flow_variables(self):
        model = routing_model(["A", "B", "C", "D"],
                              [("A", "B"), ("B", "C"), ("C", "D"), ("A", "D")], "A", "D")
        self.assertEqual(len(model.variables), 8)
        self.assertEqual(len(model.constraints), 4)
        self.assertEqual(model.constraints[0].expression, "(f[1,2] + f[1,4]) − (f[2,1] + f[4,1]) = 1")
        with patch("problem_models.traverse", wraps=traverse) as bfs:
            result = solve_model(model)
            bfs.assert_called_once_with(model.problem, "A", "BFS")
        self.assertEqual(result.route, ("A", "D"))
        self.assertEqual(result.objective_value, 1)
        self.assertEqual(dict(result.values)["f[1,4]"], 1)
        self.assertEqual(sum(value for _, value in result.values), 1)
        self.assertEqual(dict(result.values)["f[4,1]"], 0)

    def test_disconnected_and_invalid_routing(self):
        model = routing_model(["A", "B"], [], "A", "B")
        self.assertEqual(model.variables, ())
        self.assertEqual(model.constraints[0].expression, "(0) − (0) = 1")
        self.assertEqual(solve_model(model).status, "infeasible")
        with self.assertRaises(ValueError):
            routing_model(["A", "B"], [], "A", "A")
        with self.assertRaises(ValueError):
            routing_model(["A", "B"], [], "A", "Missing")
        with self.assertRaises(ValueError):
            scheduling_model(["A", "a"], ["Morning"], [])

    def test_weighted_routing_model_solution_and_disconnection(self):
        model = routing_model(["Depot", "Hub", "Airport"],
                              [("Depot", "Airport"), ("Depot", "Hub"), ("Hub", "Airport")], "Depot", "Airport",
                              {("Depot", "Airport"): 12, ("Depot", "Hub"): 3, ("Hub", "Airport"): 2})
        self.assertIn("12 · f[1,3]", model.objective_expression)
        with patch("problem_models.traverse", wraps=traverse) as algorithm:
            result = solve_model(model)
            algorithm.assert_called_once_with(model.problem, "Depot", "Dijkstra")
        self.assertEqual(result.route, ("Depot", "Hub", "Airport"))
        self.assertEqual(result.objective_value, 5)
        self.assertEqual(dict(result.values)["f[1,3]"], 0)
        disconnected = solve_model(routing_model(["A", "B"], [], "A", "B", {}))
        self.assertEqual(disconnected.status, "infeasible")
        self.assertEqual(disconnected.route, ())
        self.assertIsNone(disconnected.objective_value)
        self.assertIn("disconnected", disconnected.explanation)


class StudioTests(unittest.TestCase):
    def test_guided_models_editing_support_and_navigation(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.button(key="nav_studio").click().run()
        self.assertTrue(app.button(key="ps_build").disabled)
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.button(key="ps_example").click().run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertEqual(app.session_state["ps_data"]["solution"].status, "solved")
        app.button(key="nav_graphs").click().run()
        app.button(key="nav_studio").click().run()
        self.assertEqual(app.session_state["ps_data"]["solution"].status, "solved")
        app.selectbox(key="_ps_goal").select("fewest_slots").run()
        self.assertIsNone(app.session_state["ps_data"]["model"])
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        app.button(key="ps_build").click().run()
        self.assertTrue(app.button(key="ps_solve").disabled)
        app.radio(key="_ps_kind").set_value("Network routing").run()
        app.button(key="ps_example").click().run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        result = app.session_state["ps_data"]["solution"]
        self.assertEqual(result.route, ("Depot", "Junction", "Airport"))
        self.assertEqual(result.objective_value, 5)
        app.number_input(key="_ps_cost_('Depot', 'Airport')").set_value(0.5).run()
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertEqual(app.session_state["ps_data"]["solution"].route, ("Depot", "Airport"))
        self.assertEqual(app.session_state["ps_data"]["solution"].objective_value, 0.5)
        app.button(key="ps_example").click().run()
        self.assertEqual(app.number_input(key="_ps_cost_('Depot', 'Airport')").value, 12.0)
        app.multiselect(key="_ps_edges").set_value([]).run()
        self.assertIsNone(app.session_state["ps_data"]["model"])
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertEqual(app.session_state["ps_data"]["solution"].status, "infeasible")
        self.assertEqual(app.session_state["ps_data"]["weights"], {})
        app.text_area(key="_ps_nodes").set_value("Custom\nOther").run()
        self.assertEqual(app.selectbox(key="_ps_source").value, "Custom")
        self.assertEqual(app.selectbox(key="_ps_target").value, "Other")
        app.selectbox(key="_ps_target").select("Custom").run()
        self.assertTrue(app.button(key="ps_build").disabled)
        self.assertFalse(app.exception)

    def test_description_is_context_and_unsupported_types_do_not_solve(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        self.assertIsNone(app.radio(key="_ps_kind").value)
        app.text_area(key="_ps_description").set_value("Allocate a transport budget using weighted routes.").run()
        self.assertTrue(app.button(key="ps_build").disabled)
        self.assertTrue(app.button(key="ps_example").disabled)
        app.radio(key="_ps_kind").set_value(UNSUPPORTED_CHOICE).run()
        self.assertTrue(app.button(key="ps_build").disabled)
        self.assertIsNone(app.session_state["ps_data"]["model"])
        self.assertTrue(any("not supported" in warning.value for warning in app.warning))
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.button(key="ps_example").click().run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        result = app.session_state["ps_data"]["solution"]
        app.text_area(key="_ps_description").set_value("Context edited; the structured task inputs are unchanged.").run()
        self.assertEqual(app.session_state["ps_data"]["solution"], result)
        app.button(key="ps_inspect").click().run()
        app.button(key="workflow_return").click().run()
        self.assertEqual(app.text_area(key="_ps_description").value, "Context edited; the structured task inputs are unchanged.")
        app.radio(key="_ps_kind").set_value(UNSUPPORTED_CHOICE).run()
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        self.assertFalse(any(button.key == "ps_solve" for button in app.button))
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        self.assertEqual(app.text_area(key="_ps_tasks").value, "Review\nBuild\nDemo")
        self.assertEqual(app.multiselect(key="_ps_conflicts").value, [("Review", "Demo"), ("Build", "Demo")])
        self.assertFalse(app.exception)

    def test_shared_studio_flow_accepts_an_additional_adapter(self):
        base = PROBLEM_TYPES["scheduling"]
        def build(data):
            return replace(base.build_model(data), kind="test_adapter")
        adapter = replace(base, label="Test adapter", build_model=build, inspector=None)
        with patch.dict(PROBLEM_TYPES, {"test_adapter": adapter}), patch.dict(INPUT_RENDERERS, {"test_adapter": INPUT_RENDERERS["scheduling"]}):
            app = AppTest.from_file("app.py", default_timeout=60).run()
            app.radio(key="_ps_kind").set_value("Test adapter").run()
            app.button(key="ps_example").click().run()
            app.button(key="ps_build").click().run()
            self.assertEqual(app.session_state["ps_data"]["model"].kind, "test_adapter")
            app.button(key="ps_solve").click().run()
            self.assertEqual(app.session_state["ps_data"]["solution"].status, "solved")
            self.assertFalse(any(button.key == "ps_inspect" for button in app.button))
            self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
