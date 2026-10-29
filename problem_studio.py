"""Guided Problem Studio UI. All modelling and solving stays in problem_models."""

from copy import deepcopy
from html import escape
from hashlib import sha256
from itertools import combinations
import json
import os

import pandas as pd
import streamlit as st

from explanations import explain_model, render_explanation, solution_status
from ai_interpretation import CATEGORY_ALIASES, DEFAULT_MODEL, InterpretationError, answer_proposal, converse, parse_proposal, proposal_inputs
from allocation_solver import MAX_COST, MAX_RESOURCES, MAX_TASKS as MAX_ALLOCATION_TASKS, MAX_UNITS, validate_names
from graph_algorithms import MAX_NODES
from graph_explorer import graph_markup, render_edge_costs
from problem_models import PROBLEM_TYPES, Model, Solution, input_lines as _lines, solve_model
from solver import MAX_SLOTS, MAX_TASKS
from workflow import SYLLABUS_AREAS, method_notes, open_inspector


GOALS = {"feasible": "Find a valid schedule", "fewest_slots": "Minimize used slots · model only"}
WORKFLOWS = ("Manual structured solving", "Natural-language solving")


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


def _revise() -> None:
    _invalidate_inputs()
    _state()["notice"] = "Your structured inputs are kept. Edit the structured inputs above, then build and solve the revised model."


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
    _heading("2.1", "What needs a place?")
    tasks, slots = st.columns(2, gap="large")
    with tasks:
        st.text_area("Tasks · one per line", key="_ps_tasks", height=145, max_chars=4000,
                     placeholder="Review\nBuild\nDemo", on_change=_save, args=("tasks",),
                     help=f"Up to {MAX_TASKS} unique tasks.")
    with slots:
        st.text_area("Time slots · one per line", key="_ps_slots", height=145, max_chars=2000,
                     placeholder="Morning\nAfternoon", on_change=_save, args=("slots",),
                     help=f"Up to {MAX_SLOTS} distinct, non-overlapping time slots.")
    _heading("2.2", "What must stay apart?")
    names = _lines(data["tasks"])
    _pair_editor("conflicts", names, MAX_TASKS, "Tasks that cannot share a slot")
    st.caption("Each task occupies one slot. Tasks may run together unless a conflict is selected. Durations, deadlines, ordering, and capacity are not modelled.")
    _heading("2.3", "What counts as success?")
    st.selectbox("Scheduling objective", list(GOALS), format_func=GOALS.get, key="_ps_goal",
                 on_change=_save, args=("goal",))
    if data["goal"] == "fewest_slots":
        st.warning("Model only: you can inspect this optimization objective, but the current scheduler cannot prove a minimum. No solution will be generated for it.")


def _routing_inputs(data: dict) -> None:
    _heading("2.1", "Define the network.")
    nodes, edges = st.columns([1, 1.5], gap="large")
    with nodes:
        st.text_area("Locations · one per line", key="_ps_nodes", height=145, max_chars=1000,
                     placeholder="Depot\nJunction\nAirport", on_change=_save, args=("nodes",),
                     help=f"Up to {MAX_NODES} unique nodes, 24 characters per name.")
    with edges:
        _pair_editor("edges", _lines(data["nodes"]), MAX_NODES, "Two-way connections")
        st.caption("Connections have the same cost in both directions. Isolated locations are allowed; they can make a route impossible.")
    render_edge_costs(data, "_ps_", _invalidate_inputs)
    _heading("2.2", "Where should the route go?")
    source, target = st.columns(2, gap="large")
    names = list(dict.fromkeys(_lines(data["nodes"])))
    with source:
        st.selectbox("Start", names, key="_ps_source", disabled=not names, on_change=_save, args=("source",))
    with target:
        st.selectbox("Destination", names, key="_ps_target", disabled=not names, on_change=_save, args=("target",))
    _heading("2.3", "Find the lowest total cost.")
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
    _heading("2.1", "Resources meet requirements.")
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
    _heading("2.2", "How much is available?")
    st.caption("New resources start with capacity 0. Enter available units for each resource.")
    columns = st.columns(2)
    for index, name in enumerate(resources):
        with columns[index % 2]:
            _allocation_quantity(data, "capacities", name, f"{name} · capacity", 0)
    _heading("2.3", "What does each task need?")
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
    _heading("2.4", "What counts as success?")
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


def _inspect(model: Model, solution: Solution | None, origin="manual") -> None:
    open_inspector(st.session_state, model, solution, origin=origin)


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
    st.session_state.pop("ai_solution", None)
    st.session_state.pop("ai_solution_proposal", None)


def _edit_ai_proposal() -> None:
    st.session_state["ai_proposal_text"] = st.session_state["_ai_proposal_editor"]
    _reset_ai_review()



def _proposal_facts(proposal: dict) -> tuple[list[dict], list[str]]:
    """Display-only facts and questions derived from validated structured inputs."""
    kind = CATEGORY_ALIASES.get(proposal["category"])
    section = proposal.get(kind) if kind else None
    rows, questions = [], []

    def fact(label, value, question):
        if value is None or value == "" or value == []:
            questions.append(question)
        else:
            rows.append({"Fact": label, "Extracted input": str(value)})

    if section is None:
        if kind:
            questions.append("What are the structured inputs for this problem? Complete its input section in the technical details.")
        return rows, questions
    if kind == "scheduling":
        fact("Sessions / tasks", ", ".join(section["tasks"]), "What are the names of each session or task?")
        fact("Available time periods", ", ".join(section["slots"]), "Which non-overlapping time periods are available? Classroom names are not time periods.")
        fact("Tasks that cannot overlap", None if section["conflicts"] is None else
             "; ".join(f"{pair['first']} and {pair['second']}" for pair in section["conflicts"]) or "No conflicting pairs declared",
             "Which sessions share a professor or otherwise cannot run at the same time?")
        fact("Objective", GOALS.get(section["goal"]), "Do you need any valid schedule or the fewest time slots (model only)?")
    elif kind == "routing":
        fact("Locations", ", ".join(section["nodes"]), "Which locations belong to the network?")
        fact("Start", section["source"], "Where should the route start?")
        fact("Destination", section["target"], "What is the destination?")
        for edge in section["connections"]:
            label = f"{edge['first']} ↔ {edge['second']}"
            fact(label + " cost", edge["cost"], f"What is the cost of the connection {label}?")
        if not section["connections"]:
            rows.append({"Fact": "Connections", "Extracted input": "No connections supplied"})
        rows.append({"Fact": "Objective", "Extracted input": "Find a route with the lowest total connection cost"})
    elif kind == "allocation":
        if not section["resources"]:
            questions.append("Which resources are available, and what is each capacity?")
        for resource in section["resources"]:
            fact(f"{resource['name']} capacity", resource["capacity"], f"What is the capacity of {resource['name']}?")
        if not section["tasks"]:
            questions.append("Which tasks need resources, and how much does each require?")
        for task in section["tasks"]:
            fact(f"{task['name']} requirement", task["requirement"], f"How much capacity does {task['name']} require?")
            fact(f"{task['name']} eligible resources", None if task["eligible"] is None else
                 ", ".join(task["eligible"]) or "None declared", f"Which resources can handle {task['name']}?")
        for cost in section["costs"]:
            fact(f"{cost['task']} → {cost['resource']} cost", cost["cost"],
                 f"What is the cost of assigning {cost['task']} to {cost['resource']}?")
        fact("Objective", {"feasible": "Find any feasible allocation", "min_cost": "Minimize total allocation cost"}.get(section["goal"]),
             "Do you need any feasible allocation or the lowest total cost?")
        if section["goal"] == "min_cost":
            supplied = {(row["task"], row["resource"]) for row in section["costs"]}
            for task in section["tasks"]:
                for resource in task["eligible"] or []:
                    if (task["name"], resource) not in supplied:
                        questions.append(f"What is the cost of assigning {task['name']} to {resource}?")
    return rows, questions


def _render_clarification_form(proposal: dict, stale: bool) -> dict | None:
    kind = CATEGORY_ALIASES.get(proposal["category"])
    if kind is None:
        return
    section = deepcopy(proposal[kind])
    if section is None:
        section = {"scheduling": {"tasks": [], "slots": [], "conflicts": None, "goal": None},
                   "routing": {"nodes": [], "connections": [], "source": None, "target": None},
                   "allocation": {"resources": [], "tasks": [], "costs": [], "goal": None}}[kind]
    # A changed proposal/source gets fresh controls; old form values never overwrite JSON edits.
    version = sha256((st.session_state["ai_proposal_text"] + st.session_state.get("ai_source", "")).encode()).hexdigest()[:12]
    prefix = "ai_answers_" + version
    def key(name):
        return prefix + "_" + name
    def names(label, values, name):
        return _lines(st.text_area(label + " (one per line)", value="\n".join(values), key=key(name)))
    def choice(label, values, current, name, labels=None):
        return st.selectbox(label, values, index=values.index(current) if current in values else None,
                            format_func=lambda value: (labels or {}).get(value, value), key=key(name))
    def rows(label, values, columns, name):
        st.caption(label + " · add or delete rows as needed; blank cells stay unknown")
        frame = pd.DataFrame({column: pd.Series([row.get(column) for row in values],
                                              dtype="Float64" if column in ("cost", "capacity", "requirement") else "string")
                              for column in columns})
        edited = st.data_editor(frame,
                                column_order=columns, num_rows="dynamic", hide_index=True,
                                column_config={column: (st.column_config.NumberColumn(column.title(), step=1 if column in ("capacity", "requirement") else None)
                                                        if column in ("cost", "capacity", "requirement") else
                                                        st.column_config.TextColumn(column.replace("_", " ").title()))
                                               for column in columns}, key=key(name))
        result = edited.astype(object).where(pd.notna(edited), None).to_dict("records")
        for row in result:
            for column in ("capacity", "requirement"):
                value = row.get(column)
                if type(value) is float and value.is_integer():
                    row[column] = int(value)
        return result


    with st.expander("Answer questions / edit extracted facts", expanded=bool(proposal["questions"] or _proposal_facts(proposal)[1])):
        st.caption("Enter facts in the fields below and submit to refresh the proposal. No AI call or solver runs. "
                   "For new resources or tasks, save their names first, then fill the eligibility controls. "
                   "A free-text answer alone does not add a constraint to the solver.")
        with st.form(key("form")):
            if kind == "scheduling":
                section["tasks"] = names("Sessions / tasks", section["tasks"], "tasks")
                section["slots"] = names("Available time periods", section["slots"], "slots")
                section["goal"] = choice("Scheduling objective", ["feasible", "fewest_slots"], section["goal"], "goal", GOALS)
                status = choice("Conflict information", ["Unknown", "Enter conflicting pairs", "Confirmed: no conflicting pairs"],
                                "Unknown" if section["conflicts"] is None else "Enter conflicting pairs" if section["conflicts"] else "Confirmed: no conflicting pairs", "conflict_status")
                pairs = rows("Tasks that cannot overlap (include every shared-professor pair)", section["conflicts"] or [], ["first", "second"], "conflicts")
                if status == "Confirmed: no conflicting pairs":
                    section["conflicts"] = []
                elif status == "Enter conflicting pairs":
                    section["conflicts"] = pairs or None
                else:
                    section["conflicts"] = None
                st.caption("If professor assignments are missing, keep conflicts unknown. Enter named pairs only after identifying which sessions share a professor. "
                           "Room assignment and minimizing slots remain outside the current solver.")
            elif kind == "routing":
                section["nodes"] = names("Locations", section["nodes"], "nodes")
                section["source"] = st.text_input("Starting location", value=section["source"] or "", key=key("source")).strip() or None
                section["target"] = st.text_input("Destination", value=section["target"] or "", key=key("target")).strip() or None
                section["connections"] = rows("Two-way connections and costs (one shared unit)", section["connections"], ["first", "second", "cost"], "connections")
            else:
                section["resources"] = rows("Resources and whole-unit capacities", section["resources"], ["name", "capacity"], "resources")
                task_rows = rows("Tasks and whole-unit requirements", [{"name": row["name"], "requirement": row["requirement"]} for row in section["tasks"]], ["name", "requirement"], "tasks")
                known = {row["name"]: row["eligible"] for row in section["tasks"]}
                resources = [row["name"] for row in section["resources"] if row.get("name")]
                tasks = []
                for index, task in enumerate(task_rows):
                    if not task.get("name"):
                        tasks.append({**task, "eligible": None})
                        continue
                    existing = known.get(task["name"])
                    eligible = st.multiselect(f"Eligible resources for {task['name']}", list(dict.fromkeys(resources + (existing or []))),
                                              default=existing or [], key=key(f"eligible_{index}"))
                    confirmed = st.checkbox(f"Eligibility for {task['name']} is complete", value=existing is not None, key=key(f"eligibility_known_{index}"))
                    tasks.append({**task, "eligible": eligible if confirmed else None})
                section["tasks"] = tasks
                section["goal"] = choice("Allocation objective", ["feasible", "min_cost"], section["goal"], "goal",
                                         {"feasible": "Any feasible allocation", "min_cost": "Minimum total cost"})
                section["costs"] = rows("Cost for each eligible task–resource assignment (required for minimum cost)", section["costs"], ["task", "resource", "cost"], "costs")
            resolved = {}
            for index, question in enumerate(proposal["questions"]):
                st.text(question)
                answer = st.text_input("Your answer", key=key(f"answer_{index}"))
                if st.checkbox("This answer is fully reflected in the structured fields above", key=key(f"resolved_{index}")):
                    resolved[index] = answer
            st.caption("Unconfirmed questions and all unsupported requirements remain in the proposal. Do not mark a question resolved if the fields cannot represent its rule.")
            submitted = st.form_submit_button("Update proposal", disabled=stale)
        if submitted:
            try:
                if stale:
                    raise InterpretationError("The conversation changed. Send a follow-up before updating this model.")
                updated = answer_proposal(proposal, section, resolved)
                # Partial, schema-valid answers can be saved; model validation still gates solving.
                text = json.dumps(updated, indent=2, ensure_ascii=False)
                parse_proposal(text)
                st.session_state["ai_proposal_text"] = text
                st.session_state["_ai_proposal_editor"] = text
                _reset_ai_review()
                st.session_state.pop("ai_error", None)
                return updated
            except ValueError as exc:
                st.error("Answers were not applied: " + str(exc))


def _new_ai_conversation():
    for key in ("ai_chat_messages", "ai_chat_error", "ai_proposal_text", "ai_source", "ai_error", "_ai_proposal_editor", "ai_review_open", "ai_inspector_notice"):
        st.session_state.pop(key, None)
    st.session_state["ps_chat_context"] = ""
    _reset_ai_review()


def _render_ai_chat(data):
    st.markdown("**Talk through your problem**")
    st.caption("Gemini helps explain and model your problem. Chat is not a verified solver result. "
               "Sending a message shares this conversation and its current structured proposal with Google Gemini.")
    messages = st.session_state.setdefault("ai_chat_messages", [])
    if messages or "ai_proposal_text" in st.session_state:
        st.button("New conversation", key="ai_new_chat", on_click=_new_ai_conversation)
    key = _ai_setting("GEMINI_API_KEY")
    if not key:
        st.info("Configure GEMINI_API_KEY to enable chat. Manual structured solving remains available.")
    # Reserve history above the input; rendering it after submission shows the new reply without a second rerun.
    history_area = st.container()
    message = st.chat_input("Describe your problem or answer a follow-up question", key="ai_chat_input", disabled=not key)
    if message:
        try:
            previous = parse_proposal(st.session_state["ai_proposal_text"]) if "ai_proposal_text" in st.session_state else None
            with st.spinner("Thinking through your problem…"):
                response = converse(messages + [{"role": "user", "content": message}], key,
                                    _ai_setting("DISCRETEOPS_AI_MODEL", DEFAULT_MODEL), previous)
            messages.extend([{"role": "user", "content": message}, {"role": "assistant", "content": response["reply"]}])
            st.session_state["ai_proposal_text"] = json.dumps(response["proposal"], indent=2, ensure_ascii=False)
            data["description"] = "\n\n".join(item["content"] for item in messages if item["role"] == "user")
            st.session_state["ps_chat_context"] = data["description"]
            st.session_state["ai_source"] = data["description"]
            st.session_state.pop("_ai_proposal_editor", None)
            st.session_state.pop("ai_chat_error", None)
            st.session_state["ai_review_open"] = False
            _reset_ai_review()
        except InterpretationError as exc:
            st.session_state["ai_chat_error"] = str(exc)
            _reset_ai_review()
    with history_area:
        for item in messages:
            with st.chat_message(item["role"]):
                st.text(item["content"])
    if st.session_state.get("ai_chat_error"):
        st.error(st.session_state["ai_chat_error"])
        st.caption("The message was not added to the conversation. Resend it to retry; your previous inputs are preserved.")
    if messages and "ai_proposal_text" in st.session_state and not st.session_state.get("ai_review_open"):
        try:
            proposal = parse_proposal(st.session_state["ai_proposal_text"])
            pending = list(dict.fromkeys(proposal["questions"] + _proposal_facts(proposal)[1]))
            if pending:
                st.caption("Before solving: " + " ".join(pending))
            if proposal["unsupported_requirements"]:
                st.warning("The current tools cannot satisfy these requirements: " + "; ".join(proposal["unsupported_requirements"]))
        except ValueError:
            st.warning("The edited structured inputs need correction. Open model review to repair them before continuing.")


def _render_ai_intake(data: dict) -> None:
    st.caption("Understand → Clarify → Build model → Review → Solve → Explain")
    _render_ai_chat(data)
    if "ai_proposal_text" not in st.session_state:
        return
    if not st.session_state.get("ai_review_open", False):
        if not st.button("Build model for review", key="ai_review_model", type="primary",
                         disabled=bool(st.session_state.get("ai_chat_error"))):
            return
        st.session_state["ai_review_open"] = True
    if notice := st.session_state.pop("ai_inspector_notice", None):
        st.info(notice)
    _heading("03–04", "Review your mathematical model.")
    st.markdown("**AI proposal · not a solver result**")
    stale = st.session_state.get("ai_source") != data["description"]
    if stale:
        st.warning("The conversation changed. Send a follow-up to refresh this model before solving.")
    ready = False
    model = None
    try:
        proposal = parse_proposal(st.session_state["ai_proposal_text"])
        summary_area = st.container()
        proposal = _render_clarification_form(proposal, stale) or proposal
        with summary_area:
            kind = CATEGORY_ALIASES.get(proposal["category"])
            st.markdown("**How we understood your problem**")
            st.text(proposal["summary"].strip() or "No explanation was supplied. Review the extracted inputs below.")
            st.caption("Proposed category: " + (PROBLEM_TYPES[kind].label if kind else "Unsupported problem"))
            facts, missing_questions = _proposal_facts(proposal)
            st.markdown("**Extracted facts · check against your description**")
            if facts:
                st.table(facts)
            else:
                st.text("No structured facts are available yet.")
            st.markdown("**Assumptions to review**")
            for assumption in proposal["assumptions"]:
                st.text("• " + assumption)
            if not proposal["assumptions"]:
                st.text("No assumptions were listed by the interpreter.")
            questions = list(dict.fromkeys(proposal["questions"] + missing_questions))
            if questions:
                st.markdown("**Missing information · questions to answer**")
                for question in questions:
                    st.text("• " + question)
                st.warning("Answer the questions in chat or the form below, then review the updated model. Confirm only questions you have resolved.")
            if proposal["unsupported_requirements"]:
                st.markdown("**Unsupported requirements**")
                st.warning("Solving is blocked by the unsupported requirements below. Keep them in the proposal; the existing solver cannot satisfy the full problem.")
                for requirement in proposal["unsupported_requirements"]:
                    st.text("• " + requirement)
            if kind == "scheduling":
                st.caption("The model uses the recorded sessions, periods, conflict pairs and objective. "
                           "Room assignment and classroom capacity are not handled. Minimum-slot optimization is model-only.")
        _, model = proposal_inputs(proposal)
        ready = model.supported and not questions and not proposal["unsupported_requirements"] and not st.session_state.get("ai_chat_error")
        if not model.supported:
            st.warning(model.support_note)
    except ValueError as exc:
        st.warning("Proposal needs attention: " + str(exc))
    with st.expander("View technical details (JSON)", expanded=False):
        st.caption("Edit the structured inputs here, then review the refreshed summary. Solving uses only validated structured fields, never the summary text. "
                   "Resolve questions explicitly; do not remove unsupported requirements merely to make the model solve.")
        if "_ai_proposal_editor" not in st.session_state:
            st.session_state["_ai_proposal_editor"] = st.session_state["ai_proposal_text"]
        st.text_area("Proposed structured inputs", key="_ai_proposal_editor", height=300,
                     max_chars=50000, on_change=_edit_ai_proposal)
    if model is not None:
        _render_model(model)
    st.checkbox("I reviewed the extracted facts, objective and assumptions against my real problem.", key="_ai_reviewed")
    can_solve = bool(ready and not stale and st.session_state.get("_ai_reviewed"))
    _heading("05", "Solve the reviewed model.")
    if st.button("Solve reviewed model", key="ai_solve", type="primary", disabled=not can_solve) and can_solve:
        # The same dispatcher and local model used by manual solving; prose is never an input.
        with st.spinner("Running the existing solver and checking the result…"):
            st.session_state["ai_solution"] = solve_model(model)
            st.session_state["ai_solution_proposal"] = st.session_state["ai_proposal_text"]
    if (can_solve and st.session_state.get("ai_solution") is not None
            and st.session_state.get("ai_solution_proposal") == st.session_state["ai_proposal_text"]):
        _heading("06", "What the result means.")
        solution = st.session_state["ai_solution"]
        _render_natural_solution(solution, model)
        definition = PROBLEM_TYPES[model.kind]
        if (definition.inspector and solution.status == "solved" and solution.optimal is not False
                and (solution.schedule_trace is not None or solution.traversal is not None)):
            st.button(definition.inspector_label, key="ai_inspect", on_click=_inspect, args=(model, solution, "natural"))
            st.caption("Inspect the same recorded solver run. Input edits return to this chat proposal and require review and a new solve; independent inspector drafts are preserved.")


def _render_natural_solution(solution: Solution, model: Model) -> None:
    """Explain verified solver data in prose, without another Gemini call."""
    if solution.status == "solved" and solution.optimal is not False:
        st.success(solution_status(solution))
    else:
        st.warning(solution_status(solution))
    st.write(solution.explanation)
    if solution.schedule:
        st.text("The schedule assigns " + "; ".join(f"{task} to {slot}" for task, slot in solution.schedule) + ".")
    if solution.route:
        st.text("The route is " + " → ".join(solution.route) + f", with total cost {solution.objective_value:g} in your chosen unit.")
    if model.kind == "allocation":
        if solution.optimal is not None and solution.objective_value is not None:
            st.text(f"The total allocation cost is {solution.objective_value:g} in your chosen unit.")
        for table in solution.tables:
            if table.title == "Task allocation":
                st.text("The allocation assigns " + "; ".join(f"{row[0]} to {row[1]}" for row in table.rows) + ".")
    for issue in solution.diagnostics:
        st.text(issue)
    st.caption("This result applies only to the reviewed structured model and its assumptions. It was computed by the local solver, not Gemini.")
    with st.expander("Solution details and mathematical explanation", expanded=False):
        _render_solution(solution, model)


def _save_workflow():
    st.session_state["ps_workflow"] = st.session_state["_ps_workflow"]


def render_problem_studio_content() -> None:
    data = _state()
    st.html('<section class="ps-intro"><p class="eyebrow">PROBLEM STUDIO</p>'
            '<h1>Give the problem<br><em>a precise shape.</em></h1>'
            '<p>Enter the facts yourself, or talk through the problem. Both paths lead to a model you can review and a result you can verify.</p></section>')
    if "_ps_workflow" not in st.session_state:
        st.session_state["_ps_workflow"] = st.session_state.get("ps_workflow", WORKFLOWS[0])
    workflow = st.radio("Choose your workflow", WORKFLOWS, key="_ps_workflow", horizontal=True, on_change=_save_workflow)
    if workflow == WORKFLOWS[1]:
        st.session_state.setdefault("ps_chat_context", st.session_state.get("ai_source", ""))
        _render_ai_intake({"description": st.session_state["ps_chat_context"]})
    else:
        _render_manual_workflow(data)


def _render_manual_workflow(data: dict) -> None:
    if data["kind"] not in {item.label for item in PROBLEM_TYPES.values()}:
        data["kind"] = None
        st.session_state.pop("_ps_kind", None)
    fields = {"kind"} | {field for item in PROBLEM_TYPES.values() for field in item.input_defaults}
    for field in fields:
        if f"_ps_{field}" not in st.session_state:
            st.session_state[f"_ps_{field}"] = data[field]
    st.caption("Choose category → Enter inputs → Build model → Review → Solve → Explain")

    _heading("01", "Choose the problem category.")
    labels = {definition.label: slug for slug, definition in PROBLEM_TYPES.items()}
    kind, sample = st.columns([2, 1], vertical_alignment="bottom")
    with kind:
        st.radio("Choose a supported problem type", list(labels), key="_ps_kind",
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
            st.caption("Example scenario: " + definition.example_context + " Load example replaces this category's inputs; other category drafts stay intact.")
        _heading("02", "Structure your inputs.")
        with st.container(key="ps_inputs"):
            render_inputs(data)
        try:
            candidate = definition.build_model(data)
        except ValueError as exc:
            st.warning("Before building the model: " + str(exc))
            st.caption("Complete or correct these inputs, or load the example to see a complete formulation. No solver has run for this draft.")
    elif data["kind"] is None:
        st.info("Choose a supported category to enter its inputs, review a model, and solve.")
    if definition:
        _heading("03", "Review the model and assumptions.")
        st.caption("Build from the current inputs, then review Variables, Constraints, Objective, and modelling assumptions before solving. Only the structured rules shown here are included.")
    if st.button("Build model ↗", key="ps_build", type="primary", disabled=candidate is None):
        data.update(model=candidate, solution=None, dirty=False)
    if data["dirty"] and definition:
        st.info("Inputs changed. Build the model again to inspect the current problem.")
    model = data["model"]
    if definition and model is not None and model == candidate:
        _render_model(model)
        _heading("04", "Solve the structured problem.")
        if st.button("Solve this model ↗", key="ps_solve", type="primary", disabled=not model.supported):
            with st.spinner("Running the existing solver and checking the result…"):
                data["solution"] = solve_model(model)
        if data["solution"] is not None:
            _heading("05", "Inspect the result and revise.")
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
