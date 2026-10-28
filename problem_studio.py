"""Guided Problem Studio UI. All modelling and solving stays in problem_models."""

from copy import deepcopy
from html import escape
from itertools import combinations

import streamlit as st

from graph_algorithms import MAX_NODES
from graph_explorer import graph_markup, render_edge_costs
from problem_models import PROBLEM_TYPES, Model, Solution, input_lines as _lines, solve_model
from solver import MAX_SLOTS, MAX_TASKS
from workflow import SYLLABUS_AREAS, method_notes, open_inspector


GOALS = {"feasible": "Find a valid schedule", "fewest_slots": "Minimize used slots · model only"}
UNSUPPORTED_CHOICE = "Other / not supported yet"


def _state() -> dict:
    if "ps_data" not in st.session_state:
        st.session_state.ps_data = {
            "kind": None,
            "model": None, "solution": None, "dirty": False,
        }
    data = st.session_state.ps_data
    data.setdefault("description", "")
    for definition in PROBLEM_TYPES.values():
        for field, default in definition.input_defaults.items():
            data.setdefault(field, deepcopy(default))
    return data


def _save(field: str) -> None:
    data = _state()
    data[field] = st.session_state[f"_ps_{field}"]
    if field == "description":
        # Context is intentionally not interpreted as mathematical input.
        return
    if field == "kind":
        # Remounted widgets must pick up the saved draft, not frontend defaults.
        for definition in PROBLEM_TYPES.values():
            for input_field in definition.input_defaults:
                st.session_state.pop(f"_ps_{input_field}", None)
    data["dirty"] = data["dirty"] or data["model"] is not None
    data.update(model=None, solution=None)
    if field in ("tasks", "nodes"):
        names = _lines(data[field])
        pair_field = "conflicts" if field == "tasks" else "edges"
        kept = [pair for pair in data[pair_field] if all(name in names for name in pair)]
        removed = len(data[pair_field]) - len(kept)
        if removed:
            data["notice"] = f"Removed {removed} pair(s) referencing renamed or removed items. Review their replacements below."
        data[pair_field] = kept
        st.session_state[f"_ps_{pair_field}"] = kept
        if field == "nodes":
            for endpoint, default in (("source", names[0] if names else None),
                                      ("target", names[-1] if len(names) > 1 else None)):
                if data[endpoint] not in names:
                    data[endpoint] = default
                    st.session_state[f"_ps_{endpoint}"] = default


def _invalidate_costs() -> None:
    data = _state()
    data.update(dirty=data["dirty"] or data["model"] is not None, model=None, solution=None)


def _load_example() -> None:
    data = _state()
    definition = next((item for item in PROBLEM_TYPES.values() if item.label == data["kind"]), None)
    if definition is None:
        return
    values = deepcopy(definition.example)
    data.update(values)
    for field, value in values.items():
        st.session_state[f"_ps_{field}"] = value
    data.update(model=None, solution=None, dirty=False, notice="Example inputs loaded. Build the model to inspect their mathematical meaning.")


def _heading(number: str, title: str) -> None:
    st.html(f'<div class="wb-step"><span>{number}</span><h2>{title}</h2></div>')


def _pair_editor(field: str, names: list[str], maximum: int, label: str) -> None:
    data = _state()
    options = list(combinations(list(dict.fromkeys(names)), 2)) if len(names) <= maximum else []
    canonical = {frozenset(pair): pair for pair in options}
    selected = [canonical[frozenset(pair)] for pair in data[field] if frozenset(pair) in canonical]
    if selected != list(st.session_state[f"_ps_{field}"]):
        st.session_state[f"_ps_{field}"] = selected
    if len(names) <= maximum:
        data[field] = selected
    st.multiselect(label, options, key=f"_ps_{field}", format_func=lambda pair: f"{pair[0]}  ↔  {pair[1]}",
                   disabled=not options, on_change=_save, args=(field,))


def _scheduling_inputs(data: dict) -> None:
    _heading("01", "What needs a place?")
    tasks, slots = st.columns(2, gap="large")
    with tasks:
        st.text_area("Tasks · one per line", key="_ps_tasks", height=145, max_chars=4000,
                     placeholder="Review\nBuild\nDemo", on_change=_save, args=("tasks",),
                     help=f"Up to {MAX_TASKS} unique tasks.")
    with slots:
        st.text_area("Time slots · one per line", key="_ps_slots", height=145, max_chars=2000,
                     placeholder="Morning\nAfternoon", on_change=_save, args=("slots",),
                     help=f"Up to {MAX_SLOTS} distinct, non-overlapping time slots.")
    _heading("02", "What must stay apart?")
    names = _lines(data["tasks"])
    _pair_editor("conflicts", names, MAX_TASKS, "Tasks that cannot share a slot")
    st.caption("Each task occupies one slot. Tasks may run together unless a conflict is selected. Durations, deadlines, ordering, and capacity are not modelled.")
    _heading("03", "What counts as success?")
    st.selectbox("Scheduling objective", list(GOALS), format_func=GOALS.get, key="_ps_goal",
                 on_change=_save, args=("goal",))
    if data["goal"] == "fewest_slots":
        st.warning("Model only: you can inspect this optimization objective, but the current scheduler cannot prove a minimum. No solution will be generated for it.")


def _routing_inputs(data: dict) -> None:
    _heading("01", "Define the network.")
    nodes, edges = st.columns([1, 1.5], gap="large")
    with nodes:
        st.text_area("Locations · one per line", key="_ps_nodes", height=145, max_chars=1000,
                     placeholder="Depot\nJunction\nAirport", on_change=_save, args=("nodes",),
                     help=f"Up to {MAX_NODES} unique nodes, 24 characters per name.")
    with edges:
        _pair_editor("edges", _lines(data["nodes"]), MAX_NODES, "Two-way connections")
        st.caption("Connections have the same cost in both directions. Isolated locations are allowed; they can make a route impossible.")
    render_edge_costs(data, "_ps_", _invalidate_costs)
    _heading("02", "Where should the route go?")
    source, target = st.columns(2, gap="large")
    names = list(dict.fromkeys(_lines(data["nodes"])))
    with source:
        st.selectbox("Start", names, key="_ps_source", disabled=not names, on_change=_save, args=("source",))
    with target:
        st.selectbox("Destination", names, key="_ps_target", disabled=not names, on_change=_save, args=("target",))
    _heading("03", "Find the lowest total cost.")
    st.caption("Minimize the sum of connection costs between two different locations. Costs must be finite, from 0 to 1 trillion. One-way links, negative costs, capacities, and multiple routes are unsupported. No costs are inferred from location names.")


# Domain-specific fields only. Model building, solving, and results are shared.
INPUT_RENDERERS = {"scheduling": _scheduling_inputs, "routing": _routing_inputs}


def _render_model(model: Model) -> None:
    st.html('<div class="ps-model-heading"><span class="eyebrow">THE MATHEMATICAL MODEL</span>'
            '<h2>Your inputs.<br><em>Made explicit.</em></h2></div>')
    status = "READY TO SOLVE" if model.supported else "MODEL ONLY / SOLVING UNSUPPORTED"
    st.html(f'<div class="ps-support"><span>{status}</span><p>{escape(model.support_note)}</p></div>')
    definition = PROBLEM_TYPES.get(model.kind)
    solver_name = definition.solver_name if definition and model.supported else "None for this model / objective"
    st.caption(f"Available solver: {solver_name}")
    st.caption(f"{len(model.variables)} decision variables · {len(model.constraints)} explicit constraints · Variable domains apply throughout")
    with st.expander("Input symbols & modelling assumptions"):
        st.dataframe([{"Symbol": symbol, "Your input": name} for symbol, name in model.parameters],
                     hide_index=True, width="stretch")
        for assumption in model.assumptions:
            st.write(assumption)

    with st.expander("Methods behind this workflow"):
        notes = method_notes(model)
        for area, explanation in notes.items():
            st.markdown(f"**{area}** — {explanation}")
        unused = "; ".join(area for area in SYLLABUS_AREAS if area not in notes)
        st.caption(f"Not applied in this workflow: {unused}. These are underlying methods, not separate product modules; this does not imply full syllabus coverage.")

    variables, constraints, objective = st.tabs(["Variables", "Constraints", "Objective"])
    with variables:
        st.caption("These are the decisions the solver would make. Their domains define the allowed values.")
        if model.variables:
            st.dataframe([{"Variable": item.symbol, "Allowed values": item.domain, "Meaning": item.meaning}
                          for item in model.variables], hide_index=True, width="stretch")
        else:
            st.info("This model has no decision variables. Inspect its constraints to determine feasibility.")
        if model.kind == "scheduling":
            slots = " · ".join(f"s{index} = {escape(slot)}" for index, slot in enumerate(model.problem.slots, 1))
            st.html(f'<p class="ps-symbols">{slots}</p>')
        elif model.kind == "routing":
            st.caption("Indices follow your node-list order. Each two-way connection creates two binary variables, one for each direction.")
    with constraints:
        st.caption("Every rule below is instantiated from your inputs. All variable domains must also hold.")
        st.dataframe([{"Rule": item.name, "Expression": item.expression, "Meaning": item.meaning}
                      for item in model.constraints], hide_index=True, width="stretch")
    with objective:
        st.markdown(f"**{model.objective}**")
        st.html(f'<div class="ps-equation">{escape(model.objective_expression)}</div>')
        st.write(model.objective_explanation)


def _render_solution(solution: Solution, model: Model) -> None:
    st.html('<div class="ps-result-label"><span class="eyebrow">SOLVER RESULT</span></div>')
    if solution.status != "solved":
        label = {"infeasible": "No feasible solution", "limit": "Search limit · inconclusive", "unsupported": "Solving is unsupported"}[solution.status]
        st.warning(label + ". " + solution.explanation)
        if model.kind == "routing":
            st.image(graph_markup(model.problem), width="stretch")
        return
    st.success("Verified solution for the structured model")
    if solution.schedule:
        st.dataframe([{"Task": task, "Assigned slot": slot} for task, slot in solution.schedule],
                     hide_index=True, width="stretch")
        st.caption("Objective value: 0 (feasibility). All valid schedules have the same objective value.")
    elif solution.route:
        route = '<span class="ps-route-arrow">→</span>'.join(f'<span>{escape(node)}</span>' for node in solution.route)
        st.html(f'<div class="ps-route">{route}</div>')
        st.caption(f"Minimum total cost: {solution.objective_value:.15g} · {len(solution.route) - 1} connections · in your chosen cost unit")
        drawing, breakdown = st.columns([1.5, 1], gap="large", vertical_alignment="center")
        with drawing:
            st.image(graph_markup(model.problem, route=solution.route), width="stretch")
            st.caption("Highlighted edges form the shortest route. Numbers show route order; edge labels show costs.")
        with breakdown:
            costs = {frozenset(edge): cost for edge, cost in model.problem.costs().items()}
            st.dataframe([{"From": a, "To": b, "Cost": costs[frozenset((a, b))]}
                          for a, b in zip(solution.route, solution.route[1:])], hide_index=True, width="stretch")
    elif solution.objective_value is not None:
        st.caption(f"Objective value: {solution.objective_value}")
    st.write(solution.explanation)
    with st.expander("Inspect the solved variable values"):
        st.dataframe([{"Variable": variable, "Value": value} for variable, value in solution.values],
                     hide_index=True, width="stretch")


def _inspect(model: Model, solution: Solution | None) -> None:
    open_inspector(st.session_state, model, solution)


def render_problem_studio_content() -> None:
    data = _state()
    fields = {"kind", "description"} | {field for item in PROBLEM_TYPES.values() for field in item.input_defaults}
    for field in fields:
        if f"_ps_{field}" not in st.session_state:
            st.session_state[f"_ps_{field}"] = data[field]
    st.html('<section class="ps-intro"><p class="eyebrow">PROBLEM STUDIO / START HERE</p>'
            '<h1>Give the problem<br><em>a precise shape.</em></h1>'
            '<p>Describe the decision you need to make. Choose a supported problem type, structure the data, and follow the model through to an explained result.</p></section>')
    st.caption("Your workflow: problem → mathematical model → solver → visual inspection → explanation")
    st.text_area("Describe your problem (optional)", key="_ps_description", height=100, max_chars=2000,
                 placeholder="What decision are you trying to make, and what matters for a useful result?",
                 on_change=_save, args=("description",))
    st.caption("Your description is saved as context only. It is not interpreted automatically. Solvers use only the structured inputs and rules below.")
    labels = {definition.label: slug for slug, definition in PROBLEM_TYPES.items()}
    kind, sample = st.columns([2, 1], vertical_alignment="bottom")
    with kind:
        st.radio("Choose a supported problem type", [*labels, UNSUPPORTED_CHOICE], key="_ps_kind",
                 index=None, horizontal=True, on_change=_save, args=("kind",))
    slug = labels.get(data["kind"])
    definition = PROBLEM_TYPES.get(slug)
    render_inputs = INPUT_RENDERERS.get(slug)
    with sample:
        st.button("Load example", key="ps_example", on_click=_load_example, width="stretch", disabled=definition is None or render_inputs is None)
    if notice := data.pop("notice", None):
        st.info(notice)

    candidate = None
    if definition and render_inputs:
        st.write(definition.description)
        st.caption(f"Type solver: {definition.solver_name}")
        with st.container(key="ps_inputs"):
            render_inputs(data)
        try:
            candidate = definition.build_model(data)
        except ValueError as exc:
            if any(data[field] != default for field, default in definition.input_defaults.items()):
                st.warning(str(exc))
            else:
                st.caption("Enter structured data, or load an example, to build the model.")
    elif data["kind"] is None:
        st.info("Choose a supported type to see its data requirements and solver. You can start with the form or keep a description as context.")
    else:
        st.warning("This problem type is not supported. You can keep your description, but no model or solution will be generated. Choose a supported type only if its stated assumptions fit your problem.")
    if st.button("Build model ↗", key="ps_build", type="primary", disabled=candidate is None):
        data.update(model=candidate, solution=None, dirty=False)
    if data["dirty"] and definition:
        st.info("Inputs changed. Build the model again to inspect the current problem.")
    model = data["model"]
    if definition and model is not None and model == candidate:
        _render_model(model)
        if st.button("Solve this model ↗", key="ps_solve", type="primary", disabled=not model.supported):
            with st.spinner("Running the existing solver and checking the result…"):
                data["solution"] = solve_model(model)
        if data["solution"] is not None:
            _render_solution(data["solution"], model)
        if definition.inspector:
            st.button(definition.inspector_label, key="ps_inspect", on_click=_inspect, args=(model, data["solution"]), disabled=not model.supported)
            st.caption("Continue with these inputs and the same recorded solver run, when available. Your existing inspection-page draft is kept; edits made there return to this Studio problem.")
    elif definition and not data["dirty"]:
        st.html('<div class="ps-empty">A model you can read.<br><span>Build your model to inspect every decision and rule before solving.</span></div>')
