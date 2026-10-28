"""Native Streamlit navigation and product views; animation stays in one iframe."""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from workbench import render_workbench_content
from graph_explorer import render_graph_explorer_content
from problem_studio import render_problem_studio_content
from workflow import close_inspector


ASSETS = Path(__file__).parent / "assets"


def navigate(page: str) -> None:
    handoff = st.session_state.get("studio_handoff")
    if handoff and page != handoff["page"]:
        close_inspector(st.session_state)
    st.session_state.page = page


def render_sidebar() -> None:
    with st.sidebar:
        st.html('''<div class="brand"><span>✳</span> DiscreteOps.</div>
            <p class="brand-subtitle">A SPACE FOR POSSIBLE THINGS</p>''')
        with st.container(key="navigation"):
            for slug, (label, _) in PAGES.items():
                st.button(label, key=f"nav_{slug}", width="stretch",
                          type="primary" if st.session_state.page == slug else "secondary",
                          on_click=navigate, args=(slug,))
        st.html('''<div class="sidebar-note"><span class="eyebrow">THINK IN RELATIONSHIPS</span>
            <p>Every possibility<br>has a shape.</p>
            <div class="edition"><span class="status-dot"></span> An evolving workspace <span>01</span></div></div>''')


def masthead(label: str, note: str) -> None:
    st.html(f'<div class="masthead"><span>DISCRETEOPS / {label}</span><span>{note}</span></div>')


def render_experience(mode: str = "explore") -> None:
    """Only trusted, local markup is embedded. No frontend build or dependencies."""
    masthead("EXPLORATION" if mode == "explore" else "VISUAL STUDIES", "AN INTERACTIVE FIELD OF POSSIBILITIES")
    source = (ASSETS / "experience.html").read_text(encoding="utf-8")
    with st.container(key="experience"):
        components.html(source.replace("__EXPERIENCE_MODE__", mode),
                        height=820, scrolling=False, tab_index=0)


def render_home() -> None:
    render_experience()


def render_visualizations() -> None:
    render_experience("visualizations")


def render_workbench() -> None:
    masthead("WORKBENCH", "FROM CONSTRAINTS TO A SCHEDULE")
    with st.container(key="workbench_page"):
        render_workflow_context("workbench")
        render_workbench_content()
        footer()


def render_graph_explorer() -> None:
    masthead("GRAPH EXPLORER", "FOLLOW THE CONNECTIONS, STEP BY STEP")
    with st.container(key="graph_page"):
        render_workflow_context("graphs")
        render_graph_explorer_content()
        footer()


def render_problem_studio() -> None:
    masthead("PROBLEM STUDIO", "FROM A QUESTION TO A MATHEMATICAL MODEL")
    with st.container(key="studio_page"):
        render_problem_studio_content()
        footer()


def render_workflow_context(page: str) -> None:
    handoff = st.session_state.get("studio_handoff")
    if not handoff or handoff["page"] != page:
        return
    st.button("← Return to Problem Studio", key="workflow_return", on_click=navigate, args=("studio",))
    st.caption("Inspecting your Studio problem. Input edits return to Studio when you leave this view and require a rebuilt model. Your earlier independent draft is preserved.")
    if page == "graphs":
        st.caption("This viewer shows the search, not the final route. BFS supports minimum-hop routing; DFS is exploratory. The route and its destination remain in Studio.")


def render_about() -> None:
    masthead("ABOUT", "THE THINKING BEHIND THE SPACE")
    with st.container(key="product_page"):
        st.html('''<section class="product-intro"><p class="eyebrow">A DIFFERENT POINT OF VIEW</p>
            <h1>Less abstraction.<br><em>More understanding.</em></h1></section>
            <div class="about-statement"><span class="eyebrow">01 / THE INTENTION</span>
            <p>Complex problems become approachable when you can see their parts—and the relationships between them.</p></div>
            <div class="about-columns"><h2>A workspace<br>for deliberate<br><em>thinking.</em></h2>
            <div><p>DiscreteOps connects real-world problems to mathematical models, supported solvers,
            visual inspection, and explainable results. Begin in Problem Studio; the Workbench and Graph Explorer help you inspect the same problem.</p>
            <p>The visual studies are authored illustrations; they do not compute solutions.
            The Constraint Workbench uses backtracking to generate and verify real schedules.</p></div></div>''')
        st.button("Start in Problem Studio ↗", key="about_studio", on_click=navigate, args=("studio",))
        footer()


def footer() -> None:
    st.html('<footer class="site-footer"><span>DiscreteOps.</span><span>Built on logic. Open to possibility.</span><span>Python / Streamlit</span></footer>')


PAGES = {
    "studio": ("Problem Studio", render_problem_studio),
    "explore": ("Explore", render_home),
    "workbench": ("Workbench", render_workbench),
    "graphs": ("Graph Explorer", render_graph_explorer),
    "visualizations": ("Visualizations", render_visualizations),
    "about": ("About", render_about),
}
