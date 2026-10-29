from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ai_interpretation import proposal_inputs
from graph_algorithms import make_graph, traverse
from problem_models import PROBLEM_TYPES, solve_model
from solver import make_problem, solve
from ui import visualization_results
from test_ai_interpretation import proposal


def studio_result(kind):
    definition = PROBLEM_TYPES[kind]
    data = deepcopy(definition.input_defaults)
    data.update(deepcopy(definition.example))
    model = definition.build_model(data)
    data.update(kind=definition.label, model=model, solution=solve_model(model), dirty=False)
    return data


def graph_result(method="BFS"):
    data = dict(nodes="A\nB\nC", edges=[("A", "B")], weights=None,
                start="A", method=method, step=0, dirty=False)
    graph = make_graph(["A", "B", "C"], data["edges"])
    data["result"] = (graph, traverse(graph, "A", method))
    return data


class VisualizationTests(unittest.TestCase):
    def test_manual_categories_reuse_recorded_result_and_reject_edits(self):
        for kind in PROBLEM_TYPES:
            data = studio_result(kind)
            state = {"ps_data": data}
            saved = deepcopy(state)
            with patch("problem_models.solve_model", side_effect=AssertionError("must not solve")):
                entry = visualization_results(state)["studio"]
            self.assertIs(entry[3], data["solution"])
            self.assertEqual(state, saved)
            data["dirty"] = True
            self.assertFalse(visualization_results(state))
            data["dirty"] = False
            data[{"scheduling": "tasks", "routing": "nodes", "allocation": "allocation_tasks"}[kind]] = "Changed"
            self.assertFalse(visualization_results(state))

    def test_natural_results_require_valid_current_reviewed_snapshot(self):
        for kind in PROBLEM_TYPES:
            candidate = proposal(kind)
            _, model = proposal_inputs(candidate)
            text = json.dumps(candidate)
            state = dict(ai_proposal_text=text, ai_solution_proposal=text,
                         ai_solution=solve_model(model), ai_source="context", ps_chat_context="context")
            self.assertIn("chat", visualization_results(state))
            for changes in ({"ai_solution_proposal": None}, {"ai_proposal_text": "{}"},
                            {"ps_chat_context": "new message"}, {"ai_chat_error": "failed"}):
                self.assertNotIn("chat", visualization_results(dict(state, **changes)))
            for field in ("questions", "unsupported_requirements"):
                blocked = dict(candidate, **{field: ["Unresolved requirement"]})
                text = json.dumps(blocked)
                self.assertNotIn("chat", visualization_results(dict(state, ai_proposal_text=text, ai_solution_proposal=text)))

    def test_workbench_and_graph_currentness(self):
        problem = make_problem(["A", "B"], ["AM", "PM"], [("A", "B")])
        wb = dict(tasks="A\nB", slots="AM\nPM", conflicts=[("A", "B")], result=(problem, solve(problem)))
        self.assertIn("wb_data", visualization_results({"wb_data": wb}))
        self.assertFalse(visualization_results({"wb_data": dict(wb, slots="AM")}))
        for method in ("BFS", "DFS", "Dijkstra"):
            gx = graph_result(method)
            self.assertIn("gx_data", visualization_results({"gx_data": gx}))
            for changes in (dict(start="B"), dict(method="other"), dict(edges=[]), dict(dirty=True),
                            dict(weights={("A", "B"): 2}), dict(nodes="")):
                self.assertFalse(visualization_results({"gx_data": dict(gx, **changes)}))
        self.assertFalse(visualization_results({}))

    def test_studio_rendering_all_categories_without_resolving(self):
        for kind in PROBLEM_TYPES:
            app = AppTest.from_file("app.py", default_timeout=30)
            app.session_state["page"] = "visualizations"
            app.session_state["ps_data"] = studio_result(kind)
            with patch("problem_models.solve") as scheduler, patch("problem_models.traverse") as graph, patch("problem_models.solve_allocation") as allocation:
                app.run()
                scheduler.assert_not_called()
                graph.assert_not_called()
                allocation.assert_not_called()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key="viz_source").value, "studio")
            self.assertTrue(app.success)
            self.assertTrue(app.dataframe)
            app.selectbox(key="viz_source").select("illustration").run()
            self.assertFalse(app.exception)
            self.assertTrue(app.get("iframe"))
            self.assertFalse(app.success)

    def test_graph_playback_is_independent_and_stale_selection_falls_back(self):
        app = AppTest.from_file("app.py", default_timeout=30)
        gx = graph_result()
        app.session_state["page"] = "visualizations"
        app.session_state["gx_data"] = deepcopy(gx)
        app.run()
        self.assertFalse(app.exception)
        app.slider[0].set_value(1).run()
        self.assertEqual(app.session_state["gx_data"], gx)
        self.assertTrue(app.get("imgs"))
        app.session_state["gx_data"] = dict(gx, nodes="Changed")
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="viz_source").value, "illustration")
        self.assertTrue(app.info)
        self.assertTrue(app.get("iframe"))

    def test_non_successful_outcomes_keep_their_status(self):
        data = studio_result("routing")
        data["edges"], data["weights"] = [], {}
        data["model"] = PROBLEM_TYPES["routing"].build_model(data)
        data["solution"] = solve_model(data["model"])
        self.assertEqual(data["solution"].status, "infeasible")
        app = AppTest.from_file("app.py", default_timeout=30)
        app.session_state["page"] = "visualizations"
        app.session_state["ps_data"] = data
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.success)
        self.assertTrue(app.warning)
        data["solution"] = replace(data["solution"], status="limit", explanation="Search limit reached.")
        app.session_state["ps_data"] = data
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.success)
        self.assertTrue(any("Search limit" in item.value for item in app.warning))

    def test_navigation_from_each_tool_retains_recorded_outputs(self):
        for page, run, state_key, source in (("studio", "ps_solve", "ps_data", "studio"),
                                             ("workbench", "wb_solve", "wb_data", "wb_data"),
                                             ("graphs", "gx_run", "gx_data", "gx_data")):
            app = AppTest.from_file("app.py", default_timeout=30).run()
            app.button(key=f"nav_{page}").click().run()
            if page == "studio":
                app.radio(key="_ps_kind").set_value("Task scheduling").run()
                app.button(key="ps_example").click().run()
                app.button(key="ps_build").click().run()
            elif page == "workbench":
                app.button(key="wb_load").click().run()
            app.button(key=run).click().run()
            saved = deepcopy(app.session_state[state_key])
            app.button(key="nav_visualizations").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key="viz_source").value, source)
            self.assertEqual(app.session_state[state_key], saved)
            app.button(key=f"nav_{page}").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state[state_key], saved)

    def test_natural_result_survives_review_widget_cleanup(self):
        candidate = proposal("routing")
        text = json.dumps(candidate)
        _, model = proposal_inputs(candidate)
        app = AppTest.from_file("app.py", default_timeout=30)
        for key, value in dict(page="visualizations", ai_proposal_text=text, ai_solution_proposal=text,
                               ai_solution=solve_model(model), ai_source="route", ps_chat_context="route").items():
            app.session_state[key] = value
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.selectbox(key="viz_source").value, "chat")
        self.assertTrue(app.success)
        self.assertTrue(app.get("imgs"))


if __name__ == "__main__":
    unittest.main()
