"""Small session-state bridge from Studio to the existing inspection views."""

from copy import deepcopy

from problem_models import PROBLEM_TYPES, Model, Solution


SYLLABUS_AREAS = (
    "Logic and Proofs", "Basic Counting", "Advanced Combinatorial Techniques",
    "Recurrence Relations and Generating Functions", "Modular Arithmetic", "Graph Theory",
)


def method_notes(model: Model) -> dict[str, str]:
    notes = {
        "Logic and Proofs": "Constraints express the rules. Supported solver results are checked against those rules before they are shown.",
        "Basic Counting": f"The model contains {len(model.variables)} decision variables and {len(model.constraints)} explicit constraints. Variable domains define the choices.",
    }
    if model.kind == "scheduling":
        if model.supported:
            notes["Advanced Combinatorial Techniques"] = "The existing backtracking search rejects conflicting placements and revisits earlier choices. It finds feasibility, not a proven minimum."
        notes["Graph Theory"] = "Tasks and conflict pairs form a conflict graph. Assigning different slots to adjacent tasks is a graph-colouring formulation."
    elif model.kind == "routing":
        notes["Graph Theory"] = ("Connections form a weighted, undirected graph. Dijkstra settles locations in increasing total cost; its predecessor tree supplies a minimum-cost route."
                                 if model.problem.weights is not None else
                                 "Connections form an undirected graph. BFS explores distance layers; its discovery tree supplies a minimum-hop route.")
    elif model.kind == "allocation":
        notes["Advanced Combinatorial Techniques"] = "Exact search assigns whole tasks to eligible resources, prunes capacity violations, and remembers failed remaining-capacity states. It finds feasibility, not an optimized workload balance."
    return notes


def _clear_widgets(state, prefix: str) -> None:
    for key in list(state):
        if key.startswith(prefix):
            del state[key]


def open_inspector(state, model: Model, solution: Solution | None) -> None:
    """Carry the exact inputs and recorded run, preserving any independent draft."""
    if not model.supported:
        raise ValueError("This objective cannot be handed to a solver that does not support it.")
    definition = PROBLEM_TYPES.get(model.kind)
    if definition is None or definition.inspector not in ("workbench", "graphs"):
        raise ValueError("No inspection tool is registered for this problem type.")
    close_inspector(state)
    if definition.inspector == "workbench":
        page, key, prefix = "workbench", "wb_data", "_wb_"
        inputs = {"tasks": "\n".join(model.problem.tasks), "slots": "\n".join(model.problem.slots),
                  "conflicts": list(model.problem.conflicts)}
        trace = solution.schedule_trace if solution else None
        data = {**inputs, "result": (model.problem, trace) if trace is not None else None, "dirty": False}
    else:
        page, key, prefix = "graphs", "gx_data", "_gx_"
        inputs = {"nodes": "\n".join(model.problem.nodes), "edges": list(model.problem.edges), "start": model.source,
                  "weights": model.problem.costs() if model.problem.weights is not None else None}
        trace = solution.traversal if solution else None
        data = {**inputs, "method": "Dijkstra" if model.problem.weights is not None else "BFS", "step": 1 if trace else 0,
                "result": (model.problem, trace) if trace else None, "dirty": False}
    state["studio_handoff"] = {"page": page, "key": key, "prefix": prefix,
                               "previous": deepcopy(state.get(key)), "inputs": deepcopy(inputs), "model": model}
    _clear_widgets(state, prefix)
    state[key] = data
    state["page"] = page


def close_inspector(state) -> None:
    """Return edited inputs to Studio, then restore the inspection page's draft.

    Playback-only changes do not invalidate a model. Input changes always do;
    a schedule or traversal computed against edited inputs is never shown as
    the solution to Studio's previous model.
    """
    handoff = state.pop("studio_handoff", None)
    if not handoff:
        return
    data = state[handoff["key"]]
    inputs = {field: deepcopy(data[field]) for field in handoff["inputs"]}
    if inputs != handoff["inputs"]:
        studio = state["ps_data"]
        if handoff["page"] == "graphs":
            inputs["source"] = inputs.pop("start")
            nodes = [line.strip() for line in inputs["nodes"].splitlines() if line.strip()]
            if studio["target"] not in nodes:
                inputs["target"] = None
        studio.update(inputs)
        studio.update(model=None, solution=None, dirty=True,
                      notice="Your inspection edits are now in this Studio problem. Review the inputs and rebuild the model before solving again.")
    # Rehydrate every Studio widget on return, even after playback-only visits.
    # A browser can retain an empty widget value after its page was unmounted.
    _clear_widgets(state, "_ps_")
    _clear_widgets(state, handoff["prefix"])
    if handoff["previous"] is None:
        state.pop(handoff["key"], None)
    else:
        state[handoff["key"]] = handoff["previous"]
