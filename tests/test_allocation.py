import unittest
from itertools import product
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from allocation_solver import audit_allocation, make_allocation_problem, solve_allocation
from problem_models import PROBLEM_TYPES, allocation_model, solve_model


class AllocationTests(unittest.TestCase):
    def test_minimum_cost_is_not_first_feasible_and_limit_preserves_incumbent(self):
        costs = {("X", "A"): 1, ("X", "B"): 2, ("Y", "A"): 1, ("Y", "B"): 100}
        problem = make_allocation_problem(["A", "B"], ["X", "Y"], {"A": 1, "B": 1},
                                           {"X": 1, "Y": 1}, {"X": ["A", "B"], "Y": ["A", "B"]}, costs)
        limited = solve_allocation(problem, max_attempts=3)
        self.assertEqual(limited.status, "solved")
        self.assertIs(limited.optimal, False)
        self.assertEqual(limited.total_cost, 10100)
        self.assertEqual(audit_allocation(problem, dict(limited.assignments))[0], ())
        result = solve_allocation(problem)
        self.assertIs(result.optimal, True)
        self.assertEqual(result.total_cost, 300)
        self.assertEqual(dict(result.assignments), {"X": "B", "Y": "A"})
        unknown = solve_allocation(problem, max_attempts=0)
        self.assertEqual(unknown.status, "limit")
        self.assertIsNone(unknown.total_cost)
        self.assertIsNone(unknown.optimal)

    def test_optimization_matches_small_enumeration_with_decimal_and_zero_costs(self):
        resources, tasks = ["A", "B", "C"], ["W", "X", "Y", "Z"]
        capacities = {"A": 3, "B": 3, "C": 2}
        demands = {"W": 2, "X": 2, "Y": 1, "Z": 1}
        eligible = {task: resources for task in tasks}
        # Exact hundredths are summed, rather than floating-point approximations.
        costs = {(task, resource): value for task, values in zip(tasks, ((0, 1.25, 4), (2.5, 0, 1), (0.1, 0.2, 0.3), (0.2, 0.1, 0)))
                 for resource, value in zip(resources, values)}
        problem = make_allocation_problem(resources, tasks, capacities, demands, eligible, costs)
        cents = {(task, resource): amount for task, resource, amount in problem.costs}
        possible = []
        for choices in product(resources, repeat=len(tasks)):
            assignment = dict(zip(tasks, choices))
            if not audit_allocation(problem, assignment)[0]:
                possible.append(sum(cents[(task, assignment[task])] for task in tasks))
        result = solve_allocation(problem)
        self.assertIs(result.optimal, True)
        self.assertEqual(result.total_cost, min(possible))

    def test_optimization_cost_validation_and_infeasibility(self):
        for value in (None, -1, float("inf"), float("nan"), 0.001, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                make_allocation_problem(["A"], ["X"], {"A": 2}, {"X": 1}, {"X": ["A"]}, {("X", "A"): value})
        with self.assertRaisesRegex(ValueError, "Missing allocation cost"):
            allocation_model(["A"], ["X"], {"A": 2}, {"X": 1}, {"X": ["A"]}, "min_cost", {})
        problem = make_allocation_problem(["A"], ["X"], {"A": 0}, {"X": 1}, {"X": ["A"]}, {("X", "A"): 0})
        result = solve_allocation(problem)
        self.assertEqual(result.status, "infeasible")
        self.assertEqual(result.assignments, ())
        self.assertIsNone(result.total_cost)

    def test_backtracking_finds_complete_allocation_and_audits_capacity(self):
        model = PROBLEM_TYPES["allocation"].build_model(PROBLEM_TYPES["allocation"].example)
        result = solve_allocation(model.problem)
        self.assertEqual(result.status, "solved")
        self.assertEqual(dict(result.assignments)["Install"], "Team South")
        self.assertEqual(dict(result.used), {"Team North": 8, "Team South": 6})
        self.assertGreater(result.attempts, len(model.problem.tasks))
        self.assertEqual(audit_allocation(model.problem, dict(result.assignments))[0], ())
        bad = dict(result.assignments, Install="Team North")
        self.assertTrue(any("exceeds capacity" in issue for issue in audit_allocation(model.problem, bad)[0]))

    def test_infeasibility_certificates_and_indivisible_packing(self):
        cases = [
            ({"A": 1, "B": 1}, {"X": 2, "Y": 1}, {"X": ["A", "B"], "Y": ["A", "B"]}, "Total task demand"),
            ({"A": 5}, {"X": 1}, {"X": []}, "no eligible resource"),
            ({"A": 6, "B": 6}, {"X": 4, "Y": 4, "Z": 4}, {name: ["A", "B"] for name in "XYZ"}, "constraints conflict jointly"),
            ({"A": 2, "B": 10}, {"X": 2, "Y": 2}, {"X": ["A"], "Y": ["A"]}, "constraints conflict jointly"),
        ]
        for capacities, requirements, eligible, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                problem = make_allocation_problem(list(capacities), list(requirements), capacities, requirements, eligible)
                result = solve_allocation(problem)
                self.assertEqual(result.status, "infeasible")
                self.assertEqual(result.assignments, ())
                self.assertEqual(result.used, ())
                self.assertTrue(any(diagnostic in issue for issue in result.issues))

    def test_limits_do_not_claim_infeasibility_or_return_partial_assignments(self):
        problem = make_allocation_problem(["A"], ["X", "Y"], {"A": 3}, {"X": 1, "Y": 1}, {"X": ["A"], "Y": ["A"]})
        for options in ({"max_attempts": 0}, {"max_attempts": 1}, {"time_limit": 0}):
            result = solve_allocation(problem, **options)
            self.assertEqual(result.status, "limit")
            self.assertEqual(result.assignments, ())
            self.assertEqual(result.used, ())

    def test_validation_and_eligibility_audit(self):
        for capacity in (-1, 0.5, float("nan"), True):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                make_allocation_problem(["A"], ["X"], {"A": capacity}, {"X": 1}, {"X": ["A"]})
        with self.assertRaises(ValueError):
            make_allocation_problem(["A", "a"], ["X"], {"A": 1, "a": 1}, {"X": 1}, {"X": ["A"]})
        with self.assertRaises(ValueError):
            make_allocation_problem(["A"], ["X"], {"A": 1}, {"X": 1}, {"X": ["Unknown"]})
        with self.assertRaises(ValueError):
            make_allocation_problem(["A"], ["X"], {"A": 1}, {"X": 0}, {"X": ["A"]})
        problem = make_allocation_problem(["A", "B"], ["X"], {"A": 0, "B": 2}, {"X": 1}, {"X": ["B"]})
        self.assertEqual(dict(solve_allocation(problem).assignments), {"X": "B"})
        self.assertTrue(any("cannot use" in issue for issue in audit_allocation(problem, {"X": "A"})[0]))

    def test_shared_model_dispatch_and_results(self):
        model = allocation_model(["A", "B"], ["X"], {"A": 2, "B": 3}, {"X": 2}, {"X": ["A"]})
        self.assertEqual(len(model.variables), 1)
        self.assertEqual(model.constraints[0].expression, "a[1,1] = 1")
        self.assertEqual(model.constraints[1].expression, "2 · a[1,1] ≤ 2")
        with patch("problem_models.solve_allocation", wraps=solve_allocation) as solver:
            solution = solve_model(model)
            solver.assert_called_once_with(model.problem)
        self.assertEqual(solution.status, "solved")
        self.assertEqual(solution.tables[1].rows[1], ("B", 3, 0, 3, "Satisfied"))
        self.assertEqual(dict(solution.values), {"a[1,1]": 1})
        self.assertEqual(solution.diagnostics, ())


class AllocationStudioTests(unittest.TestCase):
    def test_cost_objective_result_missing_cost_and_feasible_limit_labels(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.radio(key="_ps_kind").set_value("Resource allocation").run()
        app.button(key="ps_example").click().run()
        app.selectbox(key="_ps_allocation_goal").select("min_cost").run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        result = app.session_state["ps_data"]["solution"]
        self.assertIs(result.optimal, True)
        self.assertEqual(result.objective_value, 67.5)
        self.assertTrue(any("minimum cost proven" in item.value for item in app.success))
        app.number_input(key="_ps_allocation_costs_('Install', 'Team South')").set_value(None).run()
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        self.assertTrue(app.button(key="ps_build").disabled)
        self.assertTrue(any("Missing allocation cost" in item.value for item in app.warning))
        app.selectbox(key="_ps_allocation_goal").select("feasible").run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertIsNone(app.session_state["ps_data"]["solution"].optimal)
        self.assertFalse(app.exception)

        model = allocation_model(["A", "B"], ["X", "Y"], {"A": 1, "B": 1}, {"X": 1, "Y": 1},
                                 {"X": ["A", "B"], "Y": ["A", "B"]}, "min_cost",
                                 {("X", "A"): 1, ("X", "B"): 2, ("Y", "A"): 1, ("Y", "B"): 100})
        with patch("problem_models.solve_allocation", side_effect=lambda problem: solve_allocation(problem, max_attempts=3)):
            incumbent = solve_model(model)
        self.assertIs(incumbent.optimal, False)
        self.assertEqual(incumbent.objective_value, 101)
        self.assertIn("not proven optimal", incumbent.explanation)
        # Exercise the shared result renderer with a real limited-search result.
        preview = AppTest.from_string("from problem_studio import _render_solution\nimport streamlit as st\n_render_solution(st.session_state.solution, st.session_state.model)")
        preview.session_state["solution"] = incumbent
        preview.session_state["model"] = model
        preview.run()
        self.assertTrue(any("optimality not proven" in item.value for item in preview.warning))
        self.assertFalse(preview.success)
        self.assertFalse(preview.exception)

    def test_edit_solve_infeasible_navigation_and_drafts(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.radio(key="_ps_kind").set_value("Resource allocation").run()
        self.assertTrue(app.button(key="ps_build").disabled)
        app.button(key="ps_example").click().run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertEqual(app.session_state["ps_data"]["solution"].status, "solved")
        self.assertFalse(any(button.key == "ps_inspect" for button in app.button))
        app.button(key="nav_graphs").click().run()
        app.button(key="nav_studio").click().run()
        self.assertEqual(app.number_input(key="_ps_capacities_'Team North'").value, 8)
        self.assertEqual(app.session_state["ps_data"]["solution"].status, "solved")
        app.number_input(key="_ps_capacities_'Team North'").set_value(0).run()
        self.assertIsNone(app.session_state["ps_data"]["solution"])
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertEqual(app.session_state["ps_data"]["solution"].status, "infeasible")
        self.assertEqual(app.session_state["ps_data"]["solution"].tables, ())
        self.assertTrue(any("No feasible allocation" in warning.value for warning in app.warning))
        app.button(key="ps_example").click().run()
        self.assertEqual(app.number_input(key="_ps_capacities_'Team North'").value, 8)
        app.multiselect(key="_ps_eligible_resources_'Install'").set_value([]).run()
        app.button(key="ps_build").click().run()
        app.button(key="ps_solve").click().run()
        self.assertTrue(any("no eligible resource" in text for text in app.session_state["ps_data"]["solution"].diagnostics))
        app.radio(key="_ps_kind").set_value("Task scheduling").run()
        app.button(key="ps_example").click().run()
        app.radio(key="_ps_kind").set_value("Resource allocation").run()
        self.assertEqual(app.multiselect(key="_ps_eligible_resources_'Install'").value, [])
        self.assertEqual(app.text_area(key="_ps_allocation_tasks").value, "Install\nInspect\nDocument\nHandover")
        app.text_area(key="_ps_allocation_resources").set_value("Team North").run()
        self.assertEqual(app.multiselect(key="_ps_eligible_resources_'Inspect'").value, ["Team North"])
        app.text_area(key="_ps_allocation_tasks").set_value("Duplicate\nduplicate").run()
        self.assertTrue(app.button(key="ps_build").disabled)
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
