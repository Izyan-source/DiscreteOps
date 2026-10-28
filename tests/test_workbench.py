import unittest

from streamlit.testing.v1 import AppTest


class WorkbenchTests(unittest.TestCase):
    def test_examples_edits_and_navigation(self):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        app.button(key="nav_workbench").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key="wb_solve").disabled)
        app.button(key="wb_load").click().run()
        app.button(key="wb_solve").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["wb_data"]["result"][1].status, "solved")
        app.button(key="nav_explore").click().run()
        app.button(key="nav_workbench").click().run()
        self.assertTrue(app.text_area(key="_wb_tasks").value.startswith("Design review"))
        self.assertEqual(app.session_state["wb_data"]["result"][1].status, "solved")
        app.selectbox(key="_wb_example").select("Two-slot bottleneck").run()
        app.button(key="wb_load").click().run()
        self.assertIsNone(app.session_state["wb_data"]["result"])
        app.button(key="wb_solve").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["wb_data"]["result"][1].status, "infeasible")
        app.text_area(key="_wb_slots").set_value("Morning\nAfternoon\nEvening").run()
        self.assertIsNone(app.session_state["wb_data"]["result"])
        app.button(key="wb_solve").click().run()
        self.assertEqual(app.session_state["wb_data"]["result"][1].status, "solved")
        self.assertFalse(any("Inputs changed" in item.value for item in app.info))
        app.text_area(key="_wb_tasks").set_value("Design review\nAPI workshop").run()
        self.assertEqual(len(app.session_state["wb_data"]["conflicts"]), 1)
        self.assertIsNone(app.session_state["wb_data"]["result"])
        self.assertTrue(any("Removed 2 conflict" in item.value for item in app.info))
        app.text_area(key="_wb_tasks").set_value("Duplicate\nduplicate").run()
        self.assertTrue(app.button(key="wb_solve").disabled)
        self.assertTrue(app.warning)
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
