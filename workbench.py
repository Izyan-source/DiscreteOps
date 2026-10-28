"""The Constraint Workbench view. All scheduling logic lives in solver.py."""

from html import escape
from itertools import combinations

import streamlit as st

from explanations import explain_schedule, render_explanation
from solver import MAX_SLOTS, MAX_TASKS, InvalidProblem, Problem, Result, audit_schedule, make_problem, solve


# Examples are inputs only. Both use the same solver as user-defined problems.
EXAMPLES = {
    "Team workshop": {
        "tasks": "Design review\nAPI workshop\nClient demo\nPlanning\nQA session\nRetrospective",
        "slots": "09:00–10:00\n10:00–11:00\n11:00–12:00",
        "conflicts": [("Design review", "API workshop"), ("Design review", "Client demo"),
                      ("API workshop", "Client demo"), ("API workshop", "QA session"),
                      ("Client demo", "QA session"), ("Design review", "Planning"),
                      ("Planning", "QA session"), ("Planning", "Retrospective")],
    },
    "Two-slot bottleneck": {
        "tasks": "Design review\nAPI workshop\nClient demo",
        "slots": "Morning\nAfternoon",
        "conflicts": [("Design review", "API workshop"), ("Design review", "Client demo"),
                      ("API workshop", "Client demo")],
    },
}


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _state() -> dict:
    if "wb_data" not in st.session_state:
        st.session_state.wb_data = {"tasks": "", "slots": "", "conflicts": [], "result": None, "dirty": False}
    return st.session_state.wb_data


def _save(field: str) -> None:
    data = _state()
    data[field] = st.session_state[f"_wb_{field}"]
    if data["result"] is not None:
        data["dirty"] = True
    data["result"] = None
    if field == "tasks":
        names = _lines(data["tasks"])
        kept = [tuple(pair) for pair in data["conflicts"] if all(name in names for name in pair)]
        removed = len(data["conflicts"]) - len(kept)
        if removed:
            data["notice"] = f"Removed {removed} conflict pair(s) referencing tasks you renamed or removed. Add their replacements below."
        data["conflicts"] = kept
        st.session_state["_wb_conflicts"] = kept


def _load_example() -> None:
    example = EXAMPLES[st.session_state._wb_example]
    data = _state()
    for field in ("tasks", "slots", "conflicts"):
        value = list(example[field]) if field == "conflicts" else example[field]
        data[field] = value
        st.session_state[f"_wb_{field}"] = value
    data.update(result=None, dirty=False, notice="Example loaded. Generate a schedule to run the solver.")


def render_workbench_content() -> None:
    data = _state()
    for field in ("tasks", "slots", "conflicts"):
        if f"_wb_{field}" not in st.session_state:
            st.session_state[f"_wb_{field}"] = data[field]
    st.html('''<section class="wb-intro"><p class="eyebrow">CONSTRAINT WORKBENCH / 01</p>
        <h1>A place for<br><em>every task.</em></h1>
        <p>Define what needs to happen, when it can happen,<br>and what must stay apart.</p></section>''')
    with st.container(key="wb_examples"):
        choice, action = st.columns([3, 1], vertical_alignment="bottom")
        with choice:
            st.selectbox("Start with an example", list(EXAMPLES), key="_wb_example")
        with action:
            st.button("Load example", key="wb_load", on_click=_load_example, width="stretch")
    if notice := data.pop("notice", None):
        st.info(notice)

    st.html('''<div class="wb-rule"><span>THE RULE</span><p>Each task gets one slot. Tasks may share a slot unless you mark them as conflicting.
        Slots are distinct labels; durations, overlaps, and capacity are not inferred.</p></div>''')
    tasks_column, slots_column = st.columns(2, gap="large")
    with tasks_column:
        st.html('<div class="wb-step"><span>01</span><h2>Define the tasks.</h2></div>')
        st.text_area("Tasks · one per line", key="_wb_tasks", height=180,
                     placeholder="Design review\nAPI workshop\nClient demo", max_chars=4000,
                     help=f"Use unique names, up to {MAX_TASKS} tasks. Blank lines are ignored.",
                     on_change=_save, args=("tasks",))
    with slots_column:
        st.html('<div class="wb-step"><span>02</span><h2>Make some time.</h2></div>')
        st.text_area("Time slots · one per line", key="_wb_slots", height=180,
                     placeholder="Morning\nAfternoon", max_chars=2000,
                     help=f"Use distinct, non-overlapping slots, up to {MAX_SLOTS}. Their names are labels, not parsed times.",
                     on_change=_save, args=("slots",))

    tasks, slots = _lines(data["tasks"]), _lines(data["slots"])
    st.caption(f"{len(tasks)} / {MAX_TASKS} tasks  ·  {len(slots)} / {MAX_SLOTS} time slots")
    st.html('<div class="wb-step"><span>03</span><h2>Keep these apart.</h2></div>')
    # Widgets use task pairs as values, so punctuation in names is never parsed.
    options = list(combinations(list(dict.fromkeys(tasks)), 2)) if len(tasks) <= MAX_TASKS else []
    canonical = {frozenset(pair): pair for pair in options}
    selected = [canonical[frozenset(pair)] for pair in data["conflicts"] if frozenset(pair) in canonical]
    if selected != list(st.session_state._wb_conflicts):
        st.session_state._wb_conflicts = selected
    # Don't silently discard constraints if a temporary oversized input hides the editor.
    if len(tasks) <= MAX_TASKS:
        data["conflicts"] = selected
    st.multiselect("Conflicting task pairs", options, key="_wb_conflicts",
                   format_func=lambda pair: f"{pair[0]}  ↔  {pair[1]}",
                   placeholder="Select tasks that cannot share a slot", disabled=not options,
                   on_change=_save, args=("conflicts",))
    st.caption("Choose every pair that must run separately. Leave empty to allow all tasks to run together.")

    problem = None
    issues = ()
    try:
        problem = make_problem(tasks, slots, data["conflicts"])
    except InvalidProblem as exc:
        issues = exc.issues
    if tasks or slots:
        for issue in issues:
            st.warning(issue)
    with st.container(key="wb_generate"):
        generate = st.button("Generate schedule ↗", key="wb_solve", type="primary",
                             disabled=problem is None, width="stretch")
    if generate and problem is not None:
        with st.spinner("Finding a schedule that respects every constraint…"):
            data["result"] = (problem, solve(problem))
        data["dirty"] = False
    if data["dirty"]:
        st.info("Inputs changed. Generate again to see a schedule for the current constraints.")
    if data["result"]:
        saved_problem, result = data["result"]
        if saved_problem == problem:
            render_result(saved_problem, result)
    elif not data["dirty"]:
        st.html('<p class="wb-empty">Your schedule will appear here.<br><span>Start with your own tasks, or load an example above.</span></p>')


def render_result(problem: Problem, result: Result) -> None:
    st.html('<div class="wb-result-divider"><span class="eyebrow">THE RESULT</span></div>')
    if result.status == "solved":
        violations = audit_schedule(problem, result.assignments)
        if violations:
            st.error("The result failed verification. No schedule will be displayed.")
            return
        used = len(set(result.assignments.values()))
        st.html(f'<div class="wb-result-heading"><h2>A valid <em>schedule.</em></h2><span>{len(problem.tasks)} TASKS · {used} SLOTS USED · 0 VIOLATIONS</span></div>')
        for index, slot in enumerate(problem.slots, 1):
            assigned = [task for task in problem.tasks if result.assignments[task] == slot]
            labels = "".join(f'<span class="wb-task">{escape(task)}</span>' for task in assigned)
            if not labels:
                labels = '<span class="wb-unused">Available · no task assigned</span>'
            st.html(f'<div class="wb-slot"><div><span class="wb-slot-index">{index:02d}</span><strong>{escape(slot)}</strong></div><div class="wb-slot-tasks">{labels}</div></div>')
        st.markdown("**Why this schedule works**")
        st.write(f"All {len(problem.tasks)} tasks are assigned exactly once to one of your {len(problem.slots)} defined slots. "
                 f"Every one of the {len(problem.conflicts)} conflict pairs has different slots. "
                 "Tasks sharing a slot have no declared conflict with one another.")
        st.caption("This is the first valid schedule found, not a guarantee of the fewest slots or balanced workloads.")
        if problem.conflicts:
            with st.expander(f"Verify all {len(problem.conflicts)} conflict pairs"):
                st.dataframe([{"Task": a, "Slot": result.assignments[a], "Conflicts with": b,
                               "Other slot": result.assignments[b], "Check": "Different slots ✓"}
                              for a, b in problem.conflicts], hide_index=True, width="stretch")
    elif result.status == "infeasible":
        st.html('<div class="wb-result-heading"><h2>No valid <em>schedule.</em></h2><span>SEARCH COMPLETE</span></div>')
        st.warning(f"There is no assignment of these {len(problem.tasks)} tasks to {len(problem.slots)} slots "
                   "that keeps every conflicting pair apart. Backtracking exhausted all possible branches.")
        st.write("Add a distinct time slot, or remove a conflict only if those tasks can actually run together. Then generate again.")
    else:
        st.html('<div class="wb-result-heading"><h2>More room to <em>search.</em></h2><span>SEARCH LIMIT REACHED</span></div>')
        st.warning("The search reached its " + ("50,000-attempt" if result.limit_reason == "attempts" else "2-second") +
                   " limit before finding or ruling out a schedule. This does not prove the schedule is impossible.")
        st.write("Try more slots, a smaller task set, or fewer conflicts that are genuinely required. No partial schedule is shown.")

    st.html(f'<div class="wb-search-stats"><span>{result.attempts:,} placements tried</span><span>{result.rejected:,} collisions rejected</span><span>{result.backtracks:,} backtracks</span><span>{result.elapsed_ms:.1f} ms</span></div>')
    with st.expander("Detected collisions & search explanation"):
        st.write("The solver tries the most connected tasks first. For each task, it tries your slots in order. "
                 "A placement is rejected if a conflicting task already occupies that slot. "
                 "When a later task has no valid placement, it undoes an earlier assignment and tries another slot.")
        if result.collisions:
            st.caption(f"Showing the first {len(result.collisions)} of {result.rejected:,} rejected placements from this run. "
                       "These are rejected search attempts, not violations in a displayed schedule.")
            st.dataframe([{"Attempt": item.attempt, "Task": item.task, "Tried slot": item.slot,
                           "Already in that slot": ", ".join(item.blocking_tasks)}
                          for item in result.collisions], hide_index=True, width="stretch")
        else:
            st.write("No conflicting placement was encountered during this search.")
    render_explanation(explain_schedule(problem, result))
