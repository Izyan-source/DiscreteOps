from copy import deepcopy
import unittest

from streamlit.testing.v1 import AppTest

from problem_models import scheduling_model
from workflow import open_inspector


class WorkflowTests(unittest.TestCase):
    def test_schedule_round_trip_preserves_run_and_independent_draft(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        self.assertEqual(app.session_state["page"], "studio")
        self.assertEqual(app.sidebar.button[0].key, "nav_studio")
        app.button(key="nav_workbench").click().run()
        app.button(key="wb_load").click().run()
        app.button(key="wb_solve").click().run()
        original = deepcopy(app.session_state["wb_data"])
        app.button(key="nav_studio").click().run()
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.button(key="ps_example").click().run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        solution = app.session_state["ps_data"]["solution"]
        app.button(key="ps_inspect").click().run()
        self.assertEqual(app.session_state["page"], "workbench")
        self.assertEqual(app.session_state["wb_data"]["result"][1], solution.schedule_trace)
        self.assertEqual(app.text_area(key="_wb_tasks").value, "Review\nBuild\nDemo")
        app.text_area(key="_wb_slots").set_value("Morning\nAfternoon\nEvening").run()
        app.button(key="workflow_return").click().run()
        self.assertEqual(app.text_area(key="_ps_slots").value, "Morning\nAfternoon\nEvening")
        self.assertIsNone(app.session_state["ps_data"]["model"])
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        self.assertEqual(app.session_state["wb_data"], original)
        app.button(key="nav_workbench").click().run()
        self.assertEqual(app.text_area(key="_wb_tasks").value, original["tasks"])
        self.assertFalse(app.exception)

    def test_graph_playback_and_edits_return_to_studio(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.button(key="nav_graphs").click().run()
        app.radio(key="_gx_method").set_value("DFS").run()
        app.button(key="gx_run").click().run()
        app.button(key="gx_next").click().run()
        original = deepcopy(app.session_state["gx_data"])
        app.button(key="nav_studio").click().run()
        app.radio(key="_ps_kind").set_value("Network routing").run()
        app.button(key="ps_example").click().run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        solution = app.session_state["ps_data"]["solution"]
        app.button(key="ps_inspect").click().run()
        self.assertEqual(app.session_state["gx_data"]["result"][1], solution.traversal)
        self.assertEqual(app.radio(key="_gx_method").value, "Dijkstra")
        self.assertEqual(app.selectbox(key="_gx_start").value, "Depot")
        app.button(key="gx_next").click().run()
        app.button(key="workflow_return").click().run()
        self.assertEqual(app.session_state["ps_data"]["solution"], solution)
        self.assertEqual(app.text_area(key="_ps_nodes").value, "Depot\nJunction\nHarbour\nAirport")
        self.assertEqual(app.selectbox(key="_ps_source").value, "Depot")
        self.assertEqual(app.selectbox(key="_ps_target").value, "Airport")
        self.assertEqual(app.session_state["gx_data"], original)
        app.button(key="ps_inspect").click().run()
        app.number_input(key="_gx_cost_('Depot', 'Junction')").set_value(9.0).run()
        self.assertIsNone(app.session_state["gx_data"]["result"])
        app.button(key="workflow_return").click().run()
        self.assertEqual(app.number_input(key="_ps_cost_('Depot', 'Junction')").value, 9.0)
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        self.assertEqual(app.session_state["gx_data"], original)
        app.button(key="ps_build").click().run()
        app.button(key="ps_inspect").click().run()
        app.text_area(key="_gx_nodes").set_value("Depot\nJunction\nHarbour").run()
        # Sidebar navigation also finishes the handoff and preserves edits.
        app.button(key="nav_explore").click().run()
        self.assertEqual(app.session_state["gx_data"], original)
        app.button(key="nav_studio").click().run()
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        self.assertIsNone(app.selectbox(key="_ps_target").value)
        self.assertEqual(app.text_area(key="_ps_nodes").value, "Depot\nJunction\nHarbour")
        self.assertTrue(app.button(key="ps_build").disabled)
        self.assertFalse(app.exception)

    def test_unsupported_goal_cannot_be_downgraded_through_handoff(self):
        model = scheduling_model(["A"], ["Morning"], [], "fewest_slots")
        state = {}
        with self.assertRaises(ValueError):
            open_inspector(state, model, None)
        self.assertEqual(state, {})
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.button(key="ps_example").click().run()
        app.selectbox(key="_ps_goal").select("fewest_slots").run()
        app.button(key="ps_build").click().run()
        self.assertTrue(app.button(key="ps_solve").disabled)
        self.assertTrue(app.button(key="ps_inspect").disabled)
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
