"""Native Streamlit navigation and product views; animation stays in one iframe."""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from workbench import render_workbench_content, render_result
from graph_explorer import render_graph_explorer_content, _render_stage
from problem_studio import render_problem_studio_content, _render_solution
from ai_interpretation import parse_proposal, proposal_inputs
from problem_models import PROBLEM_TYPES, input_lines
from solver import make_problem
from graph_algorithms import make_graph
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


def render_experience(mode: str = "explore", *, show_masthead: bool = True) -> None:
    """Only trusted, local markup is embedded. No frontend build or dependencies."""
    if show_masthead:
        masthead("EXPLORATION" if mode == "explore" else "VISUAL STUDIES", "AN INTERACTIVE FIELD OF POSSIBILITIES")
    source = (ASSETS / "experience.html").read_text(encoding="utf-8")
    with st.container(key="experience"):
        components.html(source.replace("__EXPERIENCE_MODE__", mode),
                        height=820, scrolling=False, tab_index=0)


def render_home() -> None:
    render_experience()


def visualization_results(state) -> dict:
    """Read current recorded outputs, never solve or change a source draft.

    Rebuilding models here validates inputs only. The AI solve snapshot is durable
    review evidence; its checkbox widget is removed when leaving Studio.
    """
    results = {}
    data = state.get("ps_data", {})
    model, solution = data.get("model"), data.get("solution")
    if model is not None and solution is not None and not data.get("dirty"):
        try:
            definition = PROBLEM_TYPES[model.kind]
            if (model.supported and data.get("kind") == definition.label
                    and definition.build_model(data) == model):
                results["studio"] = ("Problem Studio · " + definition.label, "studio", model, solution)
        except (ValueError, KeyError, TypeError):
            pass  # An incomplete or edited draft must not expose an old result.
    text = state.get("ai_proposal_text")
    if (text and state.get("ai_solution") is not None
            and state.get("ai_solution_proposal") == text
            and state.get("ai_source") == state.get("ps_chat_context")
            and not state.get("ai_chat_error")):
        try:
            proposal = parse_proposal(text)
            _, model = proposal_inputs(proposal)
            if model.supported and not proposal["questions"] and not proposal["unsupported_requirements"]:
                results["chat"] = ("Natural-language Studio · " + PROBLEM_TYPES[model.kind].label,
                                   "studio", model, state["ai_solution"])
        except (ValueError, KeyError, TypeError):
            pass
    for key, renderer, label in (("wb_data", "workbench", "Constraint Workbench · Schedule"),
                                 ("gx_data", "graph", "Graph Explorer · Traversal")):
        data = state.get(key, {})
        if not data.get("result") or data.get("dirty"):
            continue
        try:
            problem, result = data["result"]
            if renderer == "workbench":
                current = make_problem(input_lines(data["tasks"]), input_lines(data["slots"]), data["conflicts"])
            else:
                current = make_graph(input_lines(data["nodes"]), data["edges"], data.get("weights"))
                if data["start"] != result.start or data["method"] != result.method or not result.steps:
                    continue
            if current == problem:
                results[key] = (label, renderer, problem, result)
        except (ValueError, KeyError, TypeError):
            pass
    return results


def render_visualizations() -> None:
    masthead("VISUAL STUDIES", "AN INTERACTIVE FIELD OF POSSIBILITIES")
    results = visualization_results(st.session_state)
    labels = {key: value[0] for key, value in results.items()}
    labels["illustration"] = "Decorative study · illustrative only"
    with st.container(key="studio_page"):
        if st.session_state.get("viz_source") not in labels:
            st.session_state["viz_source"] = next(iter(labels))
        source = st.selectbox("Visualization source", list(labels), format_func=labels.get, key="viz_source")
        if not results:
            st.info("No current computed results are available. Solve a problem in Studio or Workbench, or run a Graph Explorer traversal. Edited or incomplete inputs require a new run.")
        if source != "illustration":
            _, renderer, problem, result = results[source]
            st.caption("Actual recorded solver output · matches the current inputs. No solver is run by this view.")
            if renderer == "studio":
                _render_solution(result, problem)
            elif renderer == "workbench":
                render_result(problem, result)
            else:
                index = st.slider("Traversal step", 0, len(result.steps) - 1, len(result.steps) - 1,
                                  key=f"viz_step_{hash((problem, result))}")
                _render_stage(problem, result, index, result.method)
        else:
            st.caption("Authored animation · these nodes and connections are decorative, not computed solver results.")
    if source == "illustration":
        render_experience("visualizations", show_masthead=False)


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
        st.caption("Replay the same search here. Dijkstra minimizes weighted cost; BFS and DFS explore connectivity and ignore costs. The selected route, destination, and total cost remain in Studio.")


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
