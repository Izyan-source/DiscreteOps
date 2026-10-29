"""Small session-state bridge from Studio to the existing inspection views."""

from copy import deepcopy
import json

from explanations import SYLLABUS_AREAS, method_notes
from problem_models import PROBLEM_TYPES, Model, Solution, input_lines
from ai_interpretation import parse_proposal, proposal_inputs


def _clear_widgets(state, prefix: str) -> None:
    for key in list(state):
        if key.startswith(prefix):
            del state[key]


def open_inspector(state, model: Model, solution: Solution | None, *, origin="manual") -> None:
    """Carry the exact inputs and recorded run, preserving any independent draft."""
    if origin not in ("manual", "natural"):
        raise ValueError("Unknown Studio workflow.")
    if origin == "natural":
        text = state.get("ai_proposal_text")
        if (not state.get("_ai_reviewed") or not text or text != state.get("ai_solution_proposal")
                or state.get("ai_source") != state.get("ps_chat_context") or state.get("ai_chat_error")
                or solution is None or solution != state.get("ai_solution") or solution.status != "solved"
                or solution.optimal is False):
            raise ValueError("Review and successfully solve the current chat proposal before inspecting it.")
        proposal = parse_proposal(text)
        if proposal["questions"] or proposal["unsupported_requirements"] or proposal_inputs(proposal)[1] != model:
            raise ValueError("The inspector requires the exact reviewed, validated model.")
        if ((model.kind == "scheduling" and (solution.schedule_trace is None or solution.schedule_trace.status != "solved"))
                or (model.kind == "routing" and solution.traversal is None)):
            raise ValueError("The recorded solver trace is missing.")
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
                               "previous": deepcopy(state.get(key)), "inputs": deepcopy(inputs), "model": model,
                               "origin": origin}
    if origin == "natural":
        state["studio_handoff"].update(proposal_text=text, source=state["ai_source"], solution=solution)
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
    if handoff.get("origin") == "natural":
        _return_natural_inputs(state, handoff, inputs)
    elif inputs != handoff["inputs"]:
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


def _return_natural_inputs(state, handoff, inputs):
    """Return inspector edits to the chat proposal, never to the manual draft."""
    current = (state.get("ai_proposal_text") == handoff["proposal_text"]
               and state.get("ai_solution_proposal") == handoff["proposal_text"]
               and state.get("ai_source") == handoff["source"] == state.get("ps_chat_context")
               and not state.get("ai_chat_error"))
    edited = inputs != handoff["inputs"]
    if current and edited:
        proposal = parse_proposal(handoff["proposal_text"])
        if handoff["page"] == "workbench":
            proposal["scheduling"].update(tasks=input_lines(inputs["tasks"]), slots=input_lines(inputs["slots"]),
                                          conflicts=[{"first": a, "second": b} for a, b in inputs["conflicts"]])
        else:
            nodes = input_lines(inputs["nodes"])
            weights = inputs["weights"] or {}
            proposal["routing"].update(nodes=nodes, source=inputs["start"],
                target=proposal["routing"]["target"] if proposal["routing"]["target"] in nodes else None,
                connections=[{"first": a, "second": b, "cost": weights.get((a, b), weights.get((b, a)))}
                             for a, b in inputs["edges"]])
        # Keep even incomplete edits; Studio will validate them before any new solve.
        # Questions, unsupported requirements, assumptions and objective are preserved.
        proposal["summary"] = "Inputs updated in the inspector. Review the revised facts, constraints and objective before solving again."
        state["ai_proposal_text"] = json.dumps(proposal, indent=2, ensure_ascii=False)
        state.pop("_ai_proposal_editor", None)
    if edited or not current or state.get("ai_solution") != handoff["solution"]:
        state.pop("ai_solution", None)
        state.pop("ai_solution_proposal", None)
        state["_ai_reviewed"] = False
        state["ai_inspector_notice"] = ("Inspector inputs returned to this chat model. Review the changes and solve again; the previous result has been cleared."
                                        if current else "The chat proposal changed while inspecting. Its newer inputs were kept; review and solve again.")
    else:
        # Streamlit discards unmounted widget state; retain explicit review on playback-only visits.
        state["_ai_reviewed"] = True
    state["ai_review_open"] = True
    state["ps_workflow"] = "Natural-language solving"
