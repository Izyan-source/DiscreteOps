"""Guided Problem Studio UI. All modelling and solving stays in problem_models."""

from copy import deepcopy
from html import escape
from itertools import combinations
import json
import os

import streamlit as st

from explanations import explain_model, render_explanation, solution_status
from ai_interpretation import DEFAULT_MODEL, InterpretationError, apply_proposal, interpret, parse_proposal, proposal_inputs
from allocation_solver import MAX_COST, MAX_RESOURCES, MAX_TASKS as MAX_ALLOCATION_TASKS, MAX_UNITS, validate_names
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
        st.session_state["_ai_reviewed"] = False
        # Editing prose alone never changes a structured model or runs AI.
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


def _invalidate_inputs() -> None:
    data = _state()
    data.update(dirty=data["dirty"] or data["model"] is not None, model=None, solution=None)


def _load_example() -> None:
    data = _state()
    definition = next((item for item in PROBLEM_TYPES.values() if item.label == data["kind"]), None)
    if definition is None:
        return
    # Examples must be reproducible even after an unsupported/custom objective.
    values = deepcopy({**definition.input_defaults, **definition.example})
    data.update(values)
    for field, value in values.items():
        st.session_state[f"_ps_{field}"] = value
    data.update(model=None, solution=None, dirty=False, notice="Example inputs loaded. Build the model to inspect their mathematical meaning.")


def _heading(number: str, title: str) -> None:
    st.html(f'<div class="wb-step"><span>{number}</span><h2>{title}</h2></div>')


def _choose_category(slug: str) -> None:
    st.session_state["_ps_kind"] = PROBLEM_TYPES[slug].label
    _save("kind")


def _supported_alternatives() -> None:
    st.write("Choose the closest supported decision below only if its rules fit. "
             "Your description is not automatically matched or simplified; requirements outside these scopes remain unsolved.")
    for slug, definition in PROBLEM_TYPES.items():
        if slug not in INPUT_RENDERERS:
            continue
        st.markdown(f"**{definition.label}**")
        st.write(definition.description)
        st.caption(definition.input_guidance)
        st.button(f"Use {definition.label}", key=f"ps_choose_{slug}", on_click=_choose_category, args=(slug,))


def _revise() -> None:
    _invalidate_inputs()
    _state()["notice"] = "Your inputs and description are kept. Edit the structured inputs above, then build and solve the revised model."


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
    _heading("3.1", "What needs a place?")
    tasks, slots = st.columns(2, gap="large")
    with tasks:
        st.text_area("Tasks · one per line", key="_ps_tasks", height=145, max_chars=4000,
                     placeholder="Review\nBuild\nDemo", on_change=_save, args=("tasks",),
                     help=f"Up to {MAX_TASKS} unique tasks.")
    with slots:
        st.text_area("Time slots · one per line", key="_ps_slots", height=145, max_chars=2000,
                     placeholder="Morning\nAfternoon", on_change=_save, args=("slots",),
                     help=f"Up to {MAX_SLOTS} distinct, non-overlapping time slots.")
    _heading("3.2", "What must stay apart?")
    names = _lines(data["tasks"])
    _pair_editor("conflicts", names, MAX_TASKS, "Tasks that cannot share a slot")
    st.caption("Each task occupies one slot. Tasks may run together unless a conflict is selected. Durations, deadlines, ordering, and capacity are not modelled.")
    _heading("3.3", "What counts as success?")
    st.selectbox("Scheduling objective", list(GOALS), format_func=GOALS.get, key="_ps_goal",
                 on_change=_save, args=("goal",))
    if data["goal"] == "fewest_slots":
        st.warning("Model only: you can inspect this optimization objective, but the current scheduler cannot prove a minimum. No solution will be generated for it.")


def _routing_inputs(data: dict) -> None:
    _heading("3.1", "Define the network.")
    nodes, edges = st.columns([1, 1.5], gap="large")
    with nodes:
        st.text_area("Locations · one per line", key="_ps_nodes", height=145, max_chars=1000,
                     placeholder="Depot\nJunction\nAirport", on_change=_save, args=("nodes",),
                     help=f"Up to {MAX_NODES} unique nodes, 24 characters per name.")
    with edges:
        _pair_editor("edges", _lines(data["nodes"]), MAX_NODES, "Two-way connections")
        st.caption("Connections have the same cost in both directions. Isolated locations are allowed; they can make a route impossible.")
    render_edge_costs(data, "_ps_", _invalidate_inputs)
    _heading("3.2", "Where should the route go?")
    source, target = st.columns(2, gap="large")
    names = list(dict.fromkeys(_lines(data["nodes"])))
    with source:
        st.selectbox("Start", names, key="_ps_source", disabled=not names, on_change=_save, args=("source",))
    with target:
        st.selectbox("Destination", names, key="_ps_target", disabled=not names, on_change=_save, args=("target",))
    _heading("3.3", "Find the lowest total cost.")
    st.caption("Minimize the sum of connection costs between two different locations. Costs must be finite, from 0 to 1 trillion. One-way links, negative costs, capacities, and multiple routes are unsupported. No costs are inferred from location names.")


def _save_allocation_value(field: str, name: str | tuple[str, str], key: str) -> None:
    _state()[field][name] = st.session_state[key]
    _invalidate_inputs()


def _allocation_quantity(data: dict, field: str, name: str, label: str, minimum: int) -> None:
    key = f"_ps_{field}_{name!r}"
    st.session_state[key] = data[field][name]
    st.number_input(label, min_value=minimum, max_value=MAX_UNITS, step=1, key=key,
                    on_change=_save_allocation_value, args=(field, name, key))


def _allocation_inputs(data: dict) -> None:
    _heading("3.1", "Resources meet requirements.")
    resources_column, tasks_column = st.columns(2, gap="large")
    with resources_column:
        st.text_area("Resources · one per line", key="_ps_allocation_resources", height=140, max_chars=1000,
                     placeholder="Team North\nTeam South", on_change=_save, args=("allocation_resources",),
                     help=f"Up to {MAX_RESOURCES} resources; 40 characters per name.")
    with tasks_column:
        st.text_area("Allocation tasks · one per line", key="_ps_allocation_tasks", height=140, max_chars=2000,
                     placeholder="Install\nInspect\nDocument", on_change=_save, args=("allocation_tasks",),
                     help=f"Up to {MAX_ALLOCATION_TASKS} tasks; 40 characters per name.")
    st.caption("Each task goes entirely to one eligible resource. Use whole units in one shared planning period. Tasks cannot be split; timing and simultaneous needs for different resource types are outside this model.")
    try:
        resources = validate_names(_lines(data["allocation_resources"]), "resource", MAX_RESOURCES)
        tasks = validate_names(_lines(data["allocation_tasks"]), "task", MAX_ALLOCATION_TASKS)
    except ValueError:
        return  # The shared model builder presents the validation message.
    data["capacities"] = {name: data["capacities"].get(name, 0) for name in resources}
    data["requirements"] = {name: data["requirements"].get(name, 1) for name in tasks}
    previous = data["eligible_resources"]
    data["eligible_resources"] = {name: [resource for resource in previous.get(name, resources) if resource in resources]
                                  for name in tasks}
    _heading("3.2", "How much is available?")
    st.caption("New resources start with capacity 0. Enter available units for each resource.")
    columns = st.columns(2)
    for index, name in enumerate(resources):
        with columns[index % 2]:
            _allocation_quantity(data, "capacities", name, f"{name} · capacity", 0)
    _heading("3.3", "What does each task need?")
    st.caption("New tasks start with requirement 1 and all current resources eligible. Review both values. An empty eligible set makes that task impossible to assign.")
    for name in tasks:
        demand, eligible = st.columns([1, 2], gap="large")
        with demand:
            _allocation_quantity(data, "requirements", name, f"{name} · requirement", 1)
        with eligible:
            key = f"_ps_eligible_resources_{name!r}"
            st.session_state[key] = data["eligible_resources"][name]
            st.multiselect(f"{name} · eligible resources", resources, key=key,
                           on_change=_save_allocation_value, args=("eligible_resources", name, key))
    _heading("3.4", "What counts as success?")
    st.selectbox("Allocation objective", ("feasible", "min_cost"), key="_ps_allocation_goal",
                 format_func=lambda value: "Find a feasible allocation" if value == "feasible" else "Minimize total allocation cost",
                 on_change=_save, args=("allocation_goal",))
    if data["allocation_goal"] == "min_cost":
        st.caption("Enter a cost for every eligible task–resource assignment, in one common cost unit. This is the full cost per task, not a per-unit rate. Blank means missing, not zero. Use non-negative costs with at most two decimal places.")
        columns = st.columns(2)
        pairs = [(task, resource) for task in tasks for resource in data["eligible_resources"][task]]
        for index, pair in enumerate(pairs):
            key = f"_ps_allocation_costs_{pair!r}"
            value = data["allocation_costs"].get(pair)
            st.session_state[key] = float(value) if value is not None else None
            with columns[index % 2]:
                st.number_input(f"{pair[0]} → {pair[1]} · assignment cost", min_value=0.0, max_value=float(MAX_COST),
                                value=None, step=0.5, format="%.2f", key=key,
                                on_change=_save_allocation_value, args=("allocation_costs", pair, key))


# Domain-specific fields only. Model building, solving, and results are shared.
INPUT_RENDERERS = {"scheduling": _scheduling_inputs, "routing": _routing_inputs, "allocation": _allocation_inputs}


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
    if not model.supported:
        render_explanation(explain_model(model))


def _render_solution(solution: Solution, model: Model) -> None:
    st.html('<div class="ps-result-label"><span class="eyebrow">SOLVER RESULT</span></div>')
    if solution.status != "solved":
        st.warning(solution_status(solution) + ". " + solution.explanation)
        for issue in solution.diagnostics:
            st.write(issue)
        if model.kind == "routing":
            st.image(graph_markup(model.problem), width="stretch")
        render_explanation(explain_model(model, solution))
        return
    if solution.optimal is False:
        st.warning(solution_status(solution))
    else:
        st.success(solution_status(solution))
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
        if solution.optimal is not None:
            label = "Minimum total allocation cost" if solution.optimal else "Best total allocation cost found · not proven minimum"
            st.markdown(f"**{label}: {solution.objective_value:,.2f}**")
        else:
            st.caption(f"Objective value: {solution.objective_value}")
    for table in solution.tables:
        st.markdown(f"**{table.title}**")
        st.dataframe([dict(zip(table.columns, row)) for row in table.rows], hide_index=True, width="stretch")
    st.write(solution.explanation)
    render_explanation(explain_model(model, solution))
    with st.expander("Inspect the solved variable values"):
        st.dataframe([{"Variable": variable, "Value": value} for variable, value in solution.values],
                     hide_index=True, width="stretch")


def _inspect(model: Model, solution: Solution | None) -> None:
    open_inspector(st.session_state, model, solution)


def _ai_setting(name: str, default="") -> str:
    value = os.environ.get(name)
    if value is None:
        try:
            value = st.secrets.get(name, default)
        except (FileNotFoundError, KeyError):
            value = default
    return value.strip() if isinstance(value, str) else default


def _reset_ai_review() -> None:
    st.session_state["_ai_reviewed"] = False


def _edit_ai_proposal() -> None:
    st.session_state["ai_proposal_text"] = st.session_state["_ai_proposal_editor"]
    _reset_ai_review()


def _accept_ai() -> None:
    try:
        if not st.session_state.get("_ai_reviewed"):
            raise InterpretationError("Review the proposal before accepting it.")
        apply_proposal(st.session_state, st.session_state["ai_proposal_text"], st.session_state["ai_source"])
    except ValueError as exc:
        st.session_state["ai_error"] = str(exc)
    else:
        for key in ("ai_proposal_text", "ai_source", "ai_error", "_ai_reviewed", "_ai_proposal_editor"):
            st.session_state.pop(key, None)


def _render_ai_intake(data: dict) -> None:
    with st.expander("AI-assisted interpretation · optional"):
        st.caption("Interpret with AI sends only this description to OpenAI. It proposes inputs, not solutions. "
                   "Nothing is sent on typing or navigation. Review extracted facts and assumptions before loading them.")
        key = _ai_setting("OPENAI_API_KEY")
        if not key:
            st.info("To enable AI, configure OPENAI_API_KEY in the server environment or .streamlit/secrets.toml. Manual entry remains available.")
        if st.button("Interpret with AI", key="ai_interpret", disabled=not key or not data["description"].strip()):
            for field in ("ai_proposal_text", "ai_source", "ai_error", "_ai_proposal_editor"):
                st.session_state.pop(field, None)
            _reset_ai_review()
            try:
                with st.spinner("Extracting a proposal for your review…"):
                    proposal = interpret(data["description"], key, _ai_setting("DISCRETEOPS_AI_MODEL", DEFAULT_MODEL))
                st.session_state["ai_proposal_text"] = json.dumps(proposal, indent=2, ensure_ascii=False)
                st.session_state["ai_source"] = data["description"]
            except InterpretationError as exc:
                st.session_state["ai_error"] = str(exc)
        if st.session_state.get("ai_error"):
            st.error(st.session_state["ai_error"])
    if "ai_proposal_text" not in st.session_state:
        return
    st.markdown("**AI proposal · not a solver result**")
    stale = st.session_state.get("ai_source") != data["description"]
    if stale:
        st.warning("The description changed. Interpret it again; this earlier proposal cannot be accepted.")
    with st.expander("Review / edit extracted inputs (JSON)"):
        st.caption("Correct facts here, or clarify the description and interpret again. Resolve questions explicitly; "
                   "do not remove an unsupported requirement merely to make the model solve. You can also enter inputs manually below.")
        if "_ai_proposal_editor" not in st.session_state:
            st.session_state["_ai_proposal_editor"] = st.session_state["ai_proposal_text"]
        st.text_area("Proposed structured inputs", key="_ai_proposal_editor", height=300,
                     max_chars=50000, on_change=_edit_ai_proposal)
    ready = False
    try:
        proposal = parse_proposal(st.session_state["ai_proposal_text"])
        st.text(proposal["summary"])
        st.caption("Proposed category: " + proposal["category"])
        for title, field in (("Assumptions to review", "assumptions"), ("Questions to resolve", "questions"),
                             ("Unsupported requirements", "unsupported_requirements")):
            if proposal[field]:
                st.markdown(f"**{title}**")
                for detail in proposal[field]:
                    st.text("• " + detail)
        _, model = proposal_inputs(proposal)
        st.info("Proposed mathematical model, generated locally from these inputs. Review its variables, constraints, objective and assumptions; no solver has run for this proposal.")
        _render_model(model)
        ready = model.supported and not proposal["questions"] and not proposal["unsupported_requirements"]
        if not ready:
            st.warning("This proposal needs clarification or uses unsupported rules. Revise it before loading; the manual workflows remain available below.")
    except ValueError as exc:
        st.warning("Proposal needs attention: " + str(exc))
    st.checkbox("I reviewed the extracted facts, objective and assumptions against my real problem.", key="_ai_reviewed")
    st.button("Load reviewed proposal into Studio", key="ai_accept", on_click=_accept_ai,
              disabled=stale or not ready or not st.session_state.get("_ai_reviewed"))
    st.caption("Loading replaces only this category's inputs and clears its prior result. Other category drafts stay intact. Edit the form, build the model, then choose Solve explicitly.")


def render_problem_studio_content() -> None:
    data = _state()
    fields = {"kind", "description"} | {field for item in PROBLEM_TYPES.values() for field in item.input_defaults}
    for field in fields:
        if f"_ps_{field}" not in st.session_state:
            st.session_state[f"_ps_{field}"] = data[field]
    st.html('<section class="ps-intro"><p class="eyebrow">PROBLEM STUDIO / START HERE</p>'
            '<h1>Give the problem<br><em>a precise shape.</em></h1>'
            '<p>Describe the decision you need to make. Choose a supported problem type, structure the data, and follow the model through to an explained result.</p></section>')
    st.caption("01 Describe → 02 Choose category → 03 Structure inputs → 04 Review model → 05 Solve → 06 Inspect & revise")
    _heading("01", "Describe the decision.")
    st.text_area("Describe your problem (optional)", key="_ps_description", height=100, max_chars=2000,
                 placeholder="What decision are you trying to make, and what matters for a useful result?",
                 on_change=_save, args=("description",))
    st.caption("Your description stays context unless you explicitly request AI interpretation and accept its reviewed inputs. Solvers use only the structured inputs and rules below.")
    _render_ai_intake(data)
    _heading("02", "Choose the problem category.")
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
        st.caption(definition.input_guidance)
        st.caption(f"Type solver: {definition.solver_name}")
        if definition.example_context:
            st.caption("Example scenario: " + definition.example_context + " Load example replaces this category's inputs; your description and other category drafts stay intact.")
        _heading("03", "Structure your inputs.")
        with st.container(key="ps_inputs"):
            render_inputs(data)
        try:
            candidate = definition.build_model(data)
        except ValueError as exc:
            st.warning("Before building the model: " + str(exc))
            st.caption("Complete or correct these inputs, or load the example to see a complete formulation. No solver has run for this draft.")
    elif data["kind"] is None:
        st.info("Choose a supported type to see its data requirements and solver. You can start with the form or keep a description as context.")
    else:
        st.warning("This problem type is not supported. You can keep your description, but no model or solution will be generated. Choose a supported type only if its stated assumptions fit your problem.")
        _supported_alternatives()
    if definition:
        _heading("04", "Review the model and assumptions.")
        st.caption("Build from the current inputs, then review Variables, Constraints, Objective, and modelling assumptions before solving. Rules mentioned only in your description are not included.")
    if st.button("Build model ↗", key="ps_build", type="primary", disabled=candidate is None):
        data.update(model=candidate, solution=None, dirty=False)
    if data["dirty"] and definition:
        st.info("Inputs changed. Build the model again to inspect the current problem.")
    model = data["model"]
    if definition and model is not None and model == candidate:
        _render_model(model)
        _heading("05", "Solve the structured problem.")
        if st.button("Solve this model ↗", key="ps_solve", type="primary", disabled=not model.supported):
            with st.spinner("Running the existing solver and checking the result…"):
                data["solution"] = solve_model(model)
        if data["solution"] is not None:
            _heading("06", "Inspect the result and revise.")
            if data["description"].strip():
                with st.expander("Your real-world context"):
                    st.text(data["description"])
                    st.caption("The result below applies only to the structured model. Check that its assumptions cover your real decision; prose is not an additional constraint.")
            _render_solution(data["solution"], model)
            st.caption("To revise: " + definition.revision_hint)
        if definition.inspector:
            st.button(definition.inspector_label, key="ps_inspect", on_click=_inspect, args=(model, data["solution"]), disabled=not model.supported)
            st.caption("Continue with these inputs and the same recorded solver run, when available. Your existing inspection-page draft is kept; edits made there return to this Studio problem.")
        st.button("Revise inputs ↺", key="ps_revise", on_click=_revise)
    elif definition and not data["dirty"]:
        st.html('<div class="ps-empty">A model you can read.<br><span>Build your model to inspect every decision and rule before solving.</span></div>')
