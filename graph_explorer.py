"""Graph Explorer presentation. Traversal decisions live in graph_algorithms.py."""

from html import escape
from itertools import combinations
from math import cos, pi, sin

import streamlit as st

from graph_algorithms import MAX_NODES, Graph, Step, Traversal, make_graph, traverse


EXAMPLES = {
    "Branching paths": {
        "nodes": "A\nB\nC\nD\nE\nF\nG",
        "edges": [("A", "B"), ("A", "C"), ("B", "D"), ("B", "E"),
                  ("C", "F"), ("D", "E"), ("E", "G"), ("F", "G")],
    },
    "Disconnected islands": {
        "nodes": "A\nB\nC\nD\nE\nF",
        "edges": [("A", "B"), ("B", "C"), ("A", "C"), ("D", "E")],
    },
    "Blank graph": {"nodes": "", "edges": []},
}


def _names(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _state() -> dict:
    if "gx_data" not in st.session_state:
        sample = EXAMPLES["Branching paths"]
        st.session_state.gx_data = {
            "nodes": sample["nodes"], "edges": list(sample["edges"]),
            "start": "A", "method": "BFS", "result": None, "step": 0, "dirty": False,
        }
    return st.session_state.gx_data


def _save(field: str) -> None:
    data = _state()
    data[field] = st.session_state[f"_gx_{field}"]
    data["dirty"] = data["dirty"] or data["result"] is not None
    data.update(result=None, step=0)
    if field == "nodes":
        names = _names(data["nodes"])
        kept = [pair for pair in data["edges"] if all(node in names for node in pair)]
        removed = len(data["edges"]) - len(kept)
        if removed:
            data["notice"] = f"Removed {removed} connection(s) to renamed or removed nodes. Add replacement connections in the editor."
        data["edges"] = kept
        st.session_state._gx_edges = kept
        if data["start"] not in names:
            data["start"] = names[0] if names else None
            st.session_state._gx_start = data["start"]


def _load_example() -> None:
    data = _state()
    sample = EXAMPLES[st.session_state._gx_example]
    names = _names(sample["nodes"])
    data.update(nodes=sample["nodes"], edges=list(sample["edges"]),
                start=names[0] if names else None, result=None, step=0, dirty=False)
    for field in ("nodes", "edges", "start"):
        st.session_state[f"_gx_{field}"] = data[field]
    data["notice"] = "Graph loaded. Edit the connections or run a traversal." if names else "Add nodes and connections in the editor below."


def _move_step(delta: int | None = None) -> None:
    data = _state()
    last = len(data["result"][1].steps) - 1
    data["step"] = last if delta is None else max(0, min(last, data["step"] + delta))
    st.session_state._gx_step = data["step"]


def _scrub() -> None:
    _state()["step"] = st.session_state._gx_step


def graph_markup(graph: Graph, step: Step | None = None) -> str:
    """Draw only supplied graph/step data; escape user labels before embedding."""
    count = len(graph.nodes)
    positions = {node: (320 + 224 * cos(-pi / 2 + index * 2 * pi / count),
                        224 + 160 * sin(-pi / 2 + index * 2 * pi / count))
                 for index, node in enumerate(graph.nodes)}
    if count == 1:
        positions[graph.nodes[0]] = (320, 224)
    visited = step.visited if step else ()
    frontier = step.frontier if step else ()
    tree = {frozenset(edge) for edge in step.tree_edges} if step else set()
    current = step.current if step else None
    lines = []
    for a, b in graph.edges:
        x1, y1 = positions[a]
        x2, y2 = positions[b]
        traced = " ge-edge-traced" if frozenset((a, b)) in tree else ""
        lines.append(f'<line class="ge-edge{traced}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    nodes = []
    for node, (x, y) in positions.items():
        state = "current" if node == current else "visited" if node in visited else "unseen"
        ring = (f'<circle class="ge-node-ring" cx="{x:.1f}" cy="{y:.1f}" r="29"/>'
                if node in frontier else "")
        ordinal = str(visited.index(node) + 1) if node in visited else "·"
        label_lines = [node[offset:offset + 12] for offset in range(0, len(node), 12)]
        label = "".join(f'<tspan x="{x:.1f}" dy="{0 if index == 0 else 14}">{escape(line)}</tspan>'
                        for index, line in enumerate(label_lines))
        detail = f"{node}: visit {ordinal}" if node in visited else f"{node}: not visited"
        nodes.append(f'<g class="ge-node ge-node-{state}"><title>{escape(detail)}</title>{ring}'
                     f'<circle cx="{x:.1f}" cy="{y:.1f}" r="23"/>'
                     f'<text class="ge-ordinal" x="{x:.1f}" y="{y + 5:.1f}" text-anchor="middle">{ordinal}</text>'
                     f'<text class="ge-node-label" x="{x:.1f}" y="{y + 43:.1f}" text-anchor="middle">{label}</text></g>')
    # st.html strips SVG in the installed Streamlit version. Render as an image
    # with its own presentation styles, keeping all controls native Streamlit.
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 460" '
            'role="img" aria-label="Graph with numbered visits. Traversal order and step details follow below.">'
            '<title>Graph traversal</title><style>'
            '.ge-edge{stroke:#cbd0c1;stroke-width:1.4}'
            '.ge-edge-traced{stroke:#6e8156;stroke-width:2.5}'
            '.ge-node>circle{fill:#f5f3ec;stroke:#bac1ae;stroke-width:1.5}'
            '.ge-node-visited>circle{fill:#dce5cc;stroke:#7f9465}'
            '.ge-node-current>circle{fill:#293124;stroke:#293124}'
            '.ge-node>.ge-node-ring{fill:none;stroke:#7f9465;stroke-width:1.5;stroke-dasharray:3 3}'
            '.ge-ordinal{fill:#737e68;font:14px monospace}'
            '.ge-node-current .ge-ordinal{fill:#f5f3ec}'
            '.ge-node-visited .ge-ordinal{fill:#35452a}'
            '.ge-node-label{fill:#454e3c;font:13px Helvetica,Arial,sans-serif}'
            '</style><rect width="640" height="460" fill="#eeeee4"/>' + "".join(lines + nodes) + '</svg>')


def _tokens(names: tuple[str, ...], numbered: bool = False) -> str:
    return "".join(f'<span class="ge-token">{f"<b>{index:02d}</b>" if numbered else ""}{escape(node)}</span>'
                   for index, node in enumerate(names, 1)) or '<span class="ge-muted">Empty</span>'


def _render_stage(graph: Graph, result: Traversal | None, index: int, method: str) -> None:
    step = result.steps[index] if result else None
    drawing, notes = st.columns([1.65, 1], gap="large", vertical_alignment="center")
    with drawing:
        st.image(graph_markup(graph, step), width="stretch")
        frontier_label = "Queued" if method == "BFS" else "Active path"
        st.html(f'<div class="ge-legend"><span><i class="ge-key-current"></i>Current</span>'
                f'<span><i class="ge-key-visited"></i>Visited</span><span><i class="ge-key-frontier"></i>{frontier_label}</span>'
                '<span><i class="ge-key-unseen"></i>Unvisited</span></div>')
        st.caption("Numbers show first-visit order. Dark edges show discovery connections. Node names appear below each node.")
    with notes:
        if step:
            heading = (f"At {escape(step.current)}." if step.current else
                       "A complete picture." if step.action == "Complete" else "Ready to explore.")
            st.html(f'<div class="ge-step-note"><span class="eyebrow">{index:02d} / {len(result.steps) - 1:02d} · {step.action.upper()}</span>'
                    f'<h2>{heading}</h2><p>{escape(step.explanation)}</p></div>')
            label = "QUEUE · NEXT ON THE LEFT" if method == "BFS" else "ACTIVE PATH · CURRENT ON THE RIGHT"
            st.html(f'<div class="ge-frontier"><p class="eyebrow">{label}</p><div class="ge-tokens">{_tokens(step.frontier)}</div></div>')
            st.caption(f"{len(step.visited)} / {len(graph.nodes)} nodes visited · {len(step.tree_edges)} discovery edges")
        else:
            st.html('<div class="ge-step-note"><span class="eyebrow">YOUR GRAPH / LIVE PREVIEW</span>'
                    '<h2>One connection.<br><em>Then another.</em></h2>'
                    '<p>Choose a starting node and run a traversal. Move through the steps to see exactly how the graph is explored.</p></div>')
        st.html('<div class="ge-method-note">' +
                ('<strong>Breadth-first search</strong><p>A queue explores nearby nodes before moving farther out.</p>' if method == "BFS" else
                 '<strong>Depth-first search</strong><p>A recursive path explores a branch fully before backtracking.</p>') +
                '<p>When there is a choice, neighbors follow the order of your node list.</p></div>')
    if step:
        st.html(f'<div class="ge-order"><span class="eyebrow">VISIT ORDER / SO FAR</span><div class="ge-tokens">{_tokens(step.visited, numbered=True)}</div></div>')
        if step.action == "Complete" and result.unreachable:
            st.info("Unreachable from " + result.start + ": " + ", ".join(result.unreachable) +
                    ". Choose a starting node in another component, or add a connection and run again.")


def render_graph_explorer_content() -> None:
    data = _state()
    for field in ("nodes", "edges", "start", "method"):
        if f"_gx_{field}" not in st.session_state:
            st.session_state[f"_gx_{field}"] = data[field]
    st.html('<section class="ge-intro"><p class="eyebrow">GRAPH EXPLORER / 02</p>'
            '<h1>Follow every <em>connection.</em></h1>'
            '<p>Two ways to explore the same world. Build a graph, choose a beginning, and follow the logic.</p></section>')

    with st.container(key="gx_examples"):
        example, load = st.columns([3, 1], vertical_alignment="bottom")
        with example:
            st.selectbox("Start with an example", list(EXAMPLES), key="_gx_example")
        with load:
            st.button("Load graph", key="gx_load", on_click=_load_example, width="stretch")
    if notice := data.pop("notice", None):
        st.info(notice)

    with st.expander("Edit nodes & connections", expanded=not bool(_names(data["nodes"]))):
        node_column, edge_column = st.columns([1, 1.5], gap="large")
        with node_column:
            st.text_area("Nodes · one per line", key="_gx_nodes", height=180, max_chars=1000,
                         placeholder="A\nB\nC", help=f"Up to {MAX_NODES} unique nodes; names can have up to 24 characters. Blank lines are ignored.",
                         on_change=_save, args=("nodes",))
        names = _names(data["nodes"])
        options = list(combinations(list(dict.fromkeys(names)), 2)) if len(names) <= MAX_NODES else []
        canonical = {frozenset(pair): pair for pair in options}
        selected = [canonical[frozenset(pair)] for pair in data["edges"] if frozenset(pair) in canonical]
        if selected != list(st.session_state._gx_edges):
            st.session_state._gx_edges = selected
        if len(names) <= MAX_NODES:
            data["edges"] = selected
        with edge_column:
            st.multiselect("Connections · two-way", options, key="_gx_edges",
                           format_func=lambda edge: f"{edge[0]}  —  {edge[1]}",
                           placeholder="Choose pairs to connect", disabled=not options,
                           on_change=_save, args=("edges",))
            st.caption("Connections work in both directions and have no weights. Nodes can be isolated. Cycles are welcome; each node is visited only once.")

    graph = None
    try:
        graph = make_graph(names, data["edges"])
    except ValueError as exc:
        st.warning(str(exc))
    st.caption(f"{len(names)} / {MAX_NODES} nodes · {len(data['edges'])} connections · Undirected / unweighted")
    start, method, run = st.columns([1, 1.2, 1], gap="medium", vertical_alignment="bottom")
    with start:
        st.selectbox("Starting node", list(dict.fromkeys(names)), key="_gx_start",
                     disabled=graph is None, on_change=_save, args=("start",))
    with method:
        st.radio("Traversal", ["BFS", "DFS"], key="_gx_method", horizontal=True,
                 on_change=_save, args=("method",))
    with run:
        generate = st.button("Run traversal ↗", key="gx_run", type="primary", width="stretch", disabled=graph is None)
    if generate and graph is not None:
        result = traverse(graph, data["start"], data["method"])
        data.update(result=(graph, result), step=1, dirty=False)
        st.session_state._gx_step = 1
    if data["dirty"]:
        st.info("Inputs changed. Run again to explore the current graph.")

    result = data["result"][1] if data["result"] and data["result"][0] == graph else None
    with st.container(key="gx_stage"):
        if result:
            st.session_state._gx_step = data["step"]
            st.slider("Traversal step", min_value=0, max_value=len(result.steps) - 1,
                      key="_gx_step", on_change=_scrub)
            previous, following, finish = st.columns(3)
            with previous:
                st.button("← Previous", key="gx_previous", on_click=_move_step, args=(-1,),
                          disabled=data["step"] == 0, width="stretch")
            with following:
                st.button("Next →", key="gx_next", on_click=_move_step, args=(1,),
                          disabled=data["step"] == len(result.steps) - 1, width="stretch")
            with finish:
                st.button("Show result", key="gx_finish", on_click=_move_step,
                          disabled=data["step"] == len(result.steps) - 1, width="stretch")
        if graph:
            _render_stage(graph, result, data["step"], data["method"])
        else:
            st.html('<p class="ge-empty">Every graph begins with a node.<br><span>Add your nodes in the editor, or load an example above.</span></p>')
