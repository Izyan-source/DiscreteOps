"""Native Streamlit navigation and product views; animation stays in one iframe."""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


ASSETS = Path(__file__).parent / "assets"


def navigate(page: str) -> None:
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
    masthead("WORKBENCH", "SPACE BEFORE SOLUTION")
    with st.container(key="product_page"):
        st.html('''<section class="product-intro"><p class="eyebrow">START WITH A QUESTION</p>
            <h1>Make room<br>for <em>what if.</em></h1>
            <p class="lede">The next chapter of DiscreteOps: a place to shape a problem,<br>
            set its boundaries, and explore what could work.</p></section>
            <div class="workbench-preview"><span class="eyebrow">WORKSPACE PREVIEW</span>
            <div class="empty-mark" aria-hidden="true">[ &nbsp; · &nbsp; ]</div>
            <h2>The question comes first.</h2><p>Interactive problem building is on the horizon.<br>
            For now, explore how a field of possibilities becomes a space of choices.</p></div>''')
        st.button("Explore the visual study ↗", key="workbench_explore",
                  on_click=navigate, args=("visualizations",))
        footer()


def render_about() -> None:
    masthead("ABOUT", "THE THINKING BEHIND THE SPACE")
    with st.container(key="product_page"):
        st.html('''<section class="product-intro"><p class="eyebrow">A DIFFERENT POINT OF VIEW</p>
            <h1>Less abstraction.<br><em>More understanding.</em></h1></section>
            <div class="about-statement"><span class="eyebrow">01 / THE INTENTION</span>
            <p>Complex problems become approachable when you can see their parts—and the relationships between them.</p></div>
            <div class="about-columns"><h2>A workspace<br>for deliberate<br><em>thinking.</em></h2>
            <div><p>DiscreteOps brings discrete mathematics and optimization into a visual, exploratory workspace.
            It begins with curiosity, gives ideas a shape, and makes room for a more precise question.</p>
            <p>This first chapter establishes the interface. The visual studies are authored illustrations;
            they do not compute solutions. Python-powered tools will come later.</p></div></div>''')
        st.button("Return to Explore ↗", key="about_explore", on_click=navigate, args=("explore",))
        footer()


def footer() -> None:
    st.html('<footer class="site-footer"><span>DiscreteOps.</span><span>Built on logic. Open to possibility.</span><span>Python / Streamlit</span></footer>')


PAGES = {
    "explore": ("Explore", render_home),
    "workbench": ("Workbench", render_workbench),
    "visualizations": ("Visualizations", render_visualizations),
    "about": ("About", render_about),
}
