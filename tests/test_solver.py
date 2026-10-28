import itertools
import unittest

from solver import InvalidProblem, audit_schedule, make_problem, solve


class SchedulerTests(unittest.TestCase):
    def test_no_conflicts_can_share_one_slot(self):
        problem = make_problem(["A", "B", "C"], ["Morning"], [])
        result = solve(problem)
        self.assertEqual(result.status, "solved")
        self.assertEqual(set(result.assignments.values()), {"Morning"})
        self.assertFalse(audit_schedule(problem, result.assignments))

    def test_conflicts_are_normalized_and_deduplicated(self):
        problem = make_problem([" A ", "B"], ["1", "2"], [("B", "A"), ("A", "B")])
        self.assertEqual(problem.conflicts, (("A", "B"),))
        result = solve(problem)
        self.assertNotEqual(result.assignments["A"], result.assignments["B"])
        self.assertTrue(result.collisions)
        self.assertEqual(result.collisions[0].slot, "1")

    def test_triangle_is_impossible_with_two_slots(self):
        problem = make_problem(["A", "B", "C"], ["1", "2"], [("A", "B"), ("B", "C"), ("C", "A")])
        result = solve(problem)
        self.assertEqual(result.status, "infeasible")
        self.assertEqual(result.assignments, {})
        self.assertGreater(result.backtracks, 0)
        self.assertGreater(result.rejected, 0)

    def test_limits_are_not_reported_as_impossible(self):
        problem = make_problem(["A", "B"], ["1", "2"], [("A", "B")])
        for limits in ({"max_attempts": 1}, {"time_limit": 0}):
            with self.subTest(limits=limits):
                result = solve(problem, **limits)
                self.assertEqual(result.status, "limit")
                self.assertEqual(result.assignments, {})

    def test_success_can_require_undoing_an_earlier_choice(self):
        problem = make_problem(list("ABCDEFGH"), ["AM", "PM"],
                               [("A", "B"), ("B", "C"), ("C", "D"),
                                ("A", "E"), ("A", "F"), ("D", "G"), ("D", "H")])
        result = solve(problem)
        self.assertEqual(result.status, "solved")
        self.assertGreater(result.backtracks, 0)
        self.assertFalse(audit_schedule(problem, result.assignments))

    def test_audit_detects_bad_assignments(self):
        problem = make_problem(["A", "B"], ["Morning"], [("A", "B")])
        self.assertTrue(audit_schedule(problem, {"A": "Morning", "B": "Morning"}))
        self.assertTrue(audit_schedule(problem, {"A": "Not a slot"}))
        self.assertTrue(audit_schedule(problem, {"A": "Morning", "B": "Morning", "C": "Morning"}))

    def test_invalid_inputs(self):
        cases = [([], ["1"], []), (["A"], [], []), (["A", "a"], ["1"], []),
                 (["A"], ["1", "1"], []), ([" "], ["1"], []),
                 (["A"], ["1"], [("A", "A")]), (["A"], ["1"], [("A", "B")]),
                 (["A"], ["1"], [("A",)]), (["x" * 81], ["1"], []),
                 ([str(i) for i in range(25)], ["1"], []), (["A"], [str(i) for i in range(13)], [])]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(InvalidProblem):
                make_problem(*args)

    def test_matches_exhaustive_oracle_for_every_four_task_graph(self):
        tasks = ("A", "B", "C", "D")
        pairs = list(itertools.combinations(tasks, 2))
        for mask in range(1 << len(pairs)):
            conflicts = [pair for i, pair in enumerate(pairs) if mask & (1 << i)]
            for count in (1, 2, 3):
                slots = tuple(str(i) for i in range(count))
                expected = any(all(candidate[tasks.index(a)] != candidate[tasks.index(b)]
                                   for a, b in conflicts)
                               for candidate in itertools.product(slots, repeat=len(tasks)))
                problem = make_problem(tasks, slots, conflicts)
                result = solve(problem)
                with self.subTest(mask=mask, slots=count):
                    self.assertEqual(result.status == "solved", expected)
                    self.assertNotEqual(result.status, "limit")
                    if expected:
                        self.assertFalse(audit_schedule(problem, result.assignments))
                    else:
                        self.assertFalse(result.assignments)

    def test_deterministic_and_does_not_modify_inputs(self):
        problem = make_problem(["Alpha ↔ Beta", "<Review>", "Résumé"], ["AM", "PM"], [("<Review>", "Résumé")])
        original = problem
        self.assertEqual(solve(problem).assignments, solve(problem).assignments)
        self.assertEqual(problem, original)


if __name__ == "__main__":
    unittest.main()
