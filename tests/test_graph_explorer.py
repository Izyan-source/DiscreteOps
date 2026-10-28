import unittest

from streamlit.testing.v1 import AppTest

from graph_algorithms import make_graph, traverse
from graph_explorer import graph_markup


class TraversalTests(unittest.TestCase):
    def test_bfs_and_dfs_on_a_cycle(self):
        graph = make_graph(list("ABCDE"), [("A", "B"), ("A", "C"), ("B", "D"),
                                              ("D", "E"), ("E", "C")])
        bfs = traverse(graph, "A", "BFS")
        dfs = traverse(graph, "A", "DFS")
        self.assertEqual(bfs.order, tuple("ABCDE"))
        self.assertEqual(dfs.order, tuple("ABDEC"))
        self.assertEqual(bfs.steps[1].frontier, ("B", "C"))
        self.assertEqual(dfs.steps[3].frontier, ("A", "B", "D"))
        self.assertEqual(dfs.steps[6].action, "Backtrack")
        self.assertEqual(dfs.steps[6].current, "E")
        for result in (bfs, dfs):
            self.assertEqual(len(result.order), len(set(result.order)))
            self.assertEqual(result.steps[-1].visited, result.order)
            self.assertEqual(len(result.steps[-1].tree_edges), 4)
            self.assertEqual(result.steps[-1].frontier, ())

    def test_disconnected_and_isolated_starts(self):
        graph = make_graph(list("ABCD"), [("A", "B")])
        for method in ("BFS", "DFS"):
            result = traverse(graph, "A", method)
            self.assertEqual(result.order, ("A", "B"))
            self.assertEqual(result.unreachable, ("C", "D"))
            isolated = traverse(graph, "D", method)
            self.assertEqual(isolated.order, ("D",))
            self.assertEqual(isolated.unreachable, ("A", "B", "C"))

    def test_validation_and_duplicate_edges(self):
        for nodes, edges in [([], []), (["A", "a"], []), (["A"], [("A", "B")]),
                             (["A"], [("A", "A")]), (["x" * 25], [])]:
            with self.assertRaises(ValueError):
                make_graph(nodes, edges)
        graph = make_graph(["A", "B"], [("A", "B"), ("B", "A")])
        self.assertEqual(graph.edges, (("A", "B"),))
        with self.assertRaises(ValueError):
            traverse(graph, "missing")
        with self.assertRaises(ValueError):
            traverse(graph, "A", "invalid")

    def test_user_labels_are_escaped_in_svg(self):
        graph = make_graph(["<img src=x>", "B & C"], [])
        markup = graph_markup(graph)
        self.assertNotIn("<img src=x>", markup)
        self.assertIn("&lt;img src=x&gt;", markup)
        self.assertIn("B &amp; C", markup)


class GraphExplorerTests(unittest.TestCase):
    def test_run_step_edit_and_navigate(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.button(key="nav_graphs").click().run()
        app.button(key="gx_run").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["gx_data"]["result"][1].order, tuple("ABCDEFG"))
        app.button(key="gx_next").click().run()
        self.assertEqual(app.session_state["gx_data"]["step"], 2)
        app.slider(key="_gx_step").set_value(0).run()
        self.assertTrue(app.button(key="gx_previous").disabled)
        app.button(key="nav_workbench").click().run()
        app.button(key="nav_graphs").click().run()
        self.assertEqual(app.session_state["gx_data"]["step"], 0)
        app.radio(key="_gx_method").set_value("DFS").run()
        self.assertIsNone(app.session_state["gx_data"]["result"])
        app.button(key="gx_run").click().run()
        self.assertEqual(app.session_state["gx_data"]["result"][1].order, tuple("ABDEGFC"))
        app.selectbox(key="_gx_example").select("Disconnected islands").run()
        app.button(key="gx_load").click().run()
        app.selectbox(key="_gx_start").select("D").run()
        app.button(key="gx_run").click().run()
        app.button(key="gx_finish").click().run()
        self.assertTrue(any("Unreachable from D" in item.value for item in app.info))
        app.selectbox(key="_gx_example").select("Blank graph").run()
        app.button(key="gx_load").click().run()
        self.assertTrue(app.button(key="gx_run").disabled)
        app.text_area(key="_gx_nodes").set_value("Custom\nNeighbor").run()
        app.multiselect(key="_gx_edges").set_value([("Custom", "Neighbor")]).run()
        app.button(key="gx_run").click().run()
        self.assertEqual(app.session_state["gx_data"]["result"][1].order, ("Custom", "Neighbor"))
        app.text_area(key="_gx_nodes").set_value("Neighbor").run()
        self.assertIsNone(app.session_state["gx_data"]["result"])
        self.assertEqual(app.session_state["gx_data"]["edges"], [])
        self.assertEqual(app.selectbox(key="_gx_start").value, "Neighbor")
        app.text_area(key="_gx_nodes").set_value("Duplicate\nduplicate").run()
        self.assertTrue(app.button(key="gx_run").disabled)
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
