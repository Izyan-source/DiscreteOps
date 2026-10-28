import unittest
from unittest.mock import patch

from allocation_solver import solve_allocation
from explanations import explain_model, explain_schedule, explain_traversal, method_notes
from graph_algorithms import make_graph, traverse
from problem_models import allocation_model, routing_model, scheduling_model, solve_model
from solver import solve


class ExplanationTests(unittest.TestCase):
    def test_schedule_status_and_product_rule(self):
        model = scheduling_model(["A", "B"], ["Morning", "Evening"], [("A", "B")])
        explanation = explain_model(model, solve_model(model))
        self.assertIn("Verified feasible", explanation.validity)
        self.assertIn("4 assignments", dict(explanation.concepts)["Basic Counting"])
        self.assertEqual(set(method_notes(model)), {"Logic and Proofs", "Basic Counting", "Graph Theory"})
        standalone = explain_schedule(model.problem, solve(model.problem))
        self.assertIn("A and B", standalone.constraints[-1])
        self.assertIn("Morning", standalone.constraints[0])
        limited = explain_schedule(model.problem, solve(model.problem, max_attempts=0))
        self.assertIn("infeasibility has not been proved", limited.validity)
        impossible = scheduling_model(["A", "B"], ["Morning"], [("A", "B")])
        self.assertIn("No feasible assignment", explain_model(impossible, solve_model(impossible)).validity)
        unsupported = scheduling_model(["A"], ["Morning"], [], "fewest_slots")
        self.assertIn("Not run", explain_model(unsupported).algorithm)
        self.assertIn("Model only", explain_model(unsupported).validity)
        self.assertIn("not run yet", explain_model(model).algorithm)

    def test_route_algorithm_and_disconnected_destination(self):
        for weights, algorithm in ((None, "BFS"), ({("A", "B"): 2}, "Dijkstra")):
            model = routing_model(["A", "B", "C"], [("A", "B")], "A", "B", weights=weights)
            explanation = explain_model(model, solve_model(model))
            self.assertIn(algorithm, explanation.algorithm)
            self.assertIn("Verified shortest route", explanation.validity)
            self.assertEqual(set(method_notes(model)), {"Logic and Proofs", "Graph Theory"})
            disconnected = routing_model(["A", "B", "C"], [("A", "B")], "A", "C", weights=weights)
            self.assertIn("No route exists", explain_model(disconnected, solve_model(disconnected)).validity)

    def test_allocation_quality_and_limits(self):
        args = (["A", "B"], ["X", "Y"], {"A": 1, "B": 1},
                {"X": 1, "Y": 1}, {"X": ["A", "B"], "Y": ["A", "B"]})
        feasible = allocation_model(*args)
        self.assertIn("feasibility witness only", explain_model(feasible, solve_model(feasible)).validity)
        self.assertEqual(set(method_notes(feasible)), {"Logic and Proofs", "Basic Counting"})
        costs = {("X", "A"): 1, ("X", "B"): 2, ("Y", "A"): 1, ("Y", "B"): 100}
        model = allocation_model(*args, "min_cost", costs)
        self.assertIn("Minimum cost proven", explain_model(model, solve_model(model)).validity)
        for attempts, phrase in ((3, "not a proven minimum"), (0, "infeasibility has not been proved")):
            limited = solve_allocation(model.problem, max_attempts=attempts)
            with patch("problem_models.solve_allocation", return_value=limited):
                explanation = explain_model(model, solve_model(model))
            self.assertIn(phrase, explanation.validity)
        impossible = allocation_model(["A"], ["X"], {"A": 0}, {"X": 1}, {"X": ["A"]})
        self.assertIn("No feasible assignment", explain_model(impossible, solve_model(impossible)).validity)

    def test_traversal_explanation_tracks_snapshot(self):
        graph = make_graph(["A", "B", "C"], [("A", "B")], {("A", "B"): 2})
        for method in ("BFS", "DFS", "Dijkstra"):
            result = traverse(graph, "A", method)
            self.assertIn("intermediate snapshot", explain_traversal(graph, result, 1).validity)
            complete = explain_traversal(graph, result, len(result.steps) - 1)
            self.assertIn("1 are unreachable", complete.validity)
            self.assertEqual(set(dict(complete.concepts)), {"Logic and Proofs", "Graph Theory"})
            if method == "DFS":
                self.assertIn("does not prove shortest paths", complete.validity)


if __name__ == "__main__":
    unittest.main()
