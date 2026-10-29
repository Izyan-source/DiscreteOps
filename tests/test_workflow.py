from copy import deepcopy
import unittest
import json
import os
from dataclasses import replace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from problem_models import scheduling_model
from workflow import open_inspector, close_inspector
from ai_interpretation import proposal_inputs
from problem_models import solve_model
from test_ai_interpretation import proposal


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


class NaturalHandoffTests(unittest.TestCase):
    def chat(self, app, candidate):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"})
        env.start()
        self.addCleanup(env.stop)
        api = patch("problem_studio.converse", return_value={"reply": "Review this proposed model.", "proposal": candidate})
        api.start()
        self.addCleanup(api.stop)
        app.radio(key="_ps_workflow").set_value("Natural-language solving").run()
        app.chat_input(key="ai_chat_input").set_value("Plan this problem").run()
        app.button(key="ai_review_model").click().run()
        self.assertFalse(any(item.key == "ai_inspect" for item in app.button))
        app.checkbox(key="_ai_reviewed").check().run()
        self.assertFalse(any(item.key == "ai_inspect" for item in app.button))
        app.button(key="ai_solve").click().run()
        return app

    def test_schedule_playback_and_edits_preserve_manual_and_independent_drafts(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.button(key="ps_example").click().run()
        manual = deepcopy(app.session_state["ps_data"])
        app.button(key="nav_workbench").click().run()
        app.button(key="wb_load").click().run()
        app.button(key="wb_solve").click().run()
        independent = deepcopy(app.session_state["wb_data"])
        app.button(key="nav_studio").click().run()
        candidate = proposal()
        candidate["assumptions"] = ["One period per task"]
        self.chat(app, candidate)
        solution = app.session_state["ai_solution"]
        app.button(key="ai_inspect").click().run()
        self.assertEqual(app.session_state["studio_handoff"]["origin"], "natural")
        self.assertEqual(app.session_state["wb_data"]["result"][1], solution.schedule_trace)
        self.assertEqual(app.text_area(key="_wb_tasks").value, "Review\nDemo")
        app.button(key="workflow_return").click().run()
        self.assertEqual(app.radio(key="_ps_workflow").value, "Natural-language solving")
        self.assertEqual(app.session_state["ai_solution"], solution)
        self.assertTrue(app.checkbox(key="_ai_reviewed").value)
        self.assertEqual(app.session_state["wb_data"], independent)
        app.button(key="ai_inspect").click().run()
        app.text_area(key="_wb_slots").set_value("AM\nPM\nEvening").run()
        app.button(key="wb_solve").click().run()
        app.button(key="workflow_return").click().run()
        updated = json.loads(app.session_state["ai_proposal_text"])
        self.assertEqual(updated["scheduling"]["slots"], ["AM", "PM", "Evening"])
        self.assertEqual(updated["assumptions"], candidate["assumptions"])
        self.assertEqual(updated["scheduling"]["goal"], "feasible")
        self.assertNotIn("ai_solution", app.session_state)
        self.assertTrue(app.button(key="ai_solve").disabled)
        self.assertFalse(any(item.key == "ai_inspect" for item in app.button))
        self.assertEqual(app.session_state["ps_data"], manual)
        self.assertEqual(app.session_state["wb_data"], independent)
        app.checkbox(key="_ai_reviewed").check().run()
        app.button(key="ai_solve").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.button(key="ai_inspect").disabled)

    def test_route_trace_and_sidebar_return_edit_chat_target_and_costs_only(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        manual = deepcopy(app.session_state["ps_data"])
        app.button(key="nav_graphs").click().run()
        app.radio(key="_gx_method").set_value("DFS").run()
        app.button(key="gx_run").click().run()
        independent = deepcopy(app.session_state["gx_data"])
        app.button(key="nav_studio").click().run()
        self.chat(app, proposal("routing"))
        solution = app.session_state["ai_solution"]
        app.button(key="ai_inspect").click().run()
        self.assertEqual(app.session_state["gx_data"]["result"][1], solution.traversal)
        self.assertEqual(app.radio(key="_gx_method").value, "Dijkstra")
        self.assertEqual(app.selectbox(key="_gx_start").value, "Depot")
        app.button(key="gx_next").click().run()
        app.button(key="workflow_return").click().run()
        self.assertEqual(app.session_state["ai_solution"], solution)
        self.assertEqual(app.session_state["gx_data"], independent)
        app.button(key="ai_inspect").click().run()
        app.number_input(key="_gx_cost_('Depot', 'Hub')").set_value(9.0).run()
        app.text_area(key="_gx_nodes").set_value("Depot\nHub").run()
        app.button(key="nav_about").click().run()
        self.assertEqual(app.session_state["gx_data"], independent)
        app.button(key="nav_studio").click().run()
        updated = json.loads(app.session_state["ai_proposal_text"])["routing"]
        self.assertEqual(updated["nodes"], ["Depot", "Hub"])
        self.assertEqual(updated["connections"], [{"first": "Depot", "second": "Hub", "cost": 9.0}])
        self.assertIsNone(updated["target"])
        self.assertNotIn("ai_solution", app.session_state)
        self.assertTrue(app.button(key="ai_solve").disabled)
        self.assertEqual(app.session_state["ps_data"], manual)
        self.assertFalse(app.exception)

    def state(self, kind="scheduling"):
        candidate = proposal(kind)
        _, model = proposal_inputs(candidate)
        solution = solve_model(model)
        text = json.dumps(candidate)
        return {"ai_proposal_text": text, "ai_solution_proposal": text, "ai_solution": solution,
                "_ai_reviewed": True, "ai_source": "context", "ps_chat_context": "context"}, model, solution

    def test_guard_rejects_unreviewed_stale_failed_and_inconclusive_handoffs(self):
        base, model, solution = self.state()
        variants = [dict(base, _ai_reviewed=False), dict(base, ai_solution_proposal="stale"),
                    dict(base, ps_chat_context="changed"), dict(base, ai_chat_error="request failed")]
        for status in ("infeasible", "limit"):
            variants.append(dict(base, ai_solution=replace(solution, status=status)))
        variants.append(dict(base, ai_solution=replace(solution, schedule_trace=None)))
        for state in variants:
            before = deepcopy(state)
            with self.subTest(state=state), self.assertRaises(ValueError):
                open_inspector(state, model, state["ai_solution"], origin="natural")
            self.assertEqual(state, before)
        with self.assertRaises(ValueError):
            open_inspector(base, scheduling_model(["Other"], ["AM"], []), solution, origin="natural")
        state, model, solution = self.state("allocation")
        with self.assertRaises(ValueError):
            open_inspector(state, model, solution, origin="natural")

    def test_return_never_overwrites_a_newer_chat_proposal(self):
        state, model, solution = self.state()
        original = {"tasks": "Independent", "slots": "Later", "conflicts": [], "result": None}
        state["wb_data"] = deepcopy(original)
        open_inspector(state, model, solution, origin="natural")
        newer = proposal()
        newer["unsupported_requirements"] = ["Room capacity"]
        newer["questions"] = ["Which room?"]
        state["ai_proposal_text"] = json.dumps(newer)
        state["wb_data"]["slots"] = "Changed inspector slot"
        close_inspector(state)
        self.assertEqual(json.loads(state["ai_proposal_text"]), newer)
        self.assertNotIn("ai_solution", state)
        self.assertFalse(state["_ai_reviewed"])
        self.assertEqual(state["wb_data"], original)

    def test_only_successful_relevant_results_show_inspector_action(self):
        for kind, slots in (("allocation", None), ("scheduling", ["Only period"])):
            with self.subTest(kind=kind):
                candidate = proposal(kind)
                if slots:
                    candidate["scheduling"]["slots"] = slots
                app = AppTest.from_file("app.py", default_timeout=60).run()
                self.chat(app, candidate)
                self.assertFalse(any(item.key == "ai_inspect" for item in app.button))
                self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
