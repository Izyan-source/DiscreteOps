"""Presentation-only explanations derived from existing models and recorded results."""

from dataclasses import dataclass
from math import prod

from graph_algorithms import Graph, Traversal
from problem_models import PROBLEM_TYPES, Model, Solution, scheduling_model
from solver import Problem, Result


SYLLABUS_AREAS = (
    "Logic and Proofs", "Basic Counting", "Advanced Combinatorial Techniques",
    "Recurrence Relations and Generating Functions", "Modular Arithmetic", "Graph Theory",
)


@dataclass(frozen=True)
class Explanation:
    model: str
    objective: str
    constraints: tuple[str, ...]
    algorithm: str
    validity: str
    limitations: tuple[str, ...]
    concepts: tuple[tuple[str, str], ...]


def method_notes(model: Model) -> dict[str, str]:
    """Name only specific concepts actually present; do not infer unit coverage."""
    if model.kind not in ("scheduling", "routing", "allocation"):
        return {}
    notes = {"Logic and Proofs": "The model is a conjunction of constraints: every rule must hold. A valid assignment is a witness of feasibility; failure to find one before a limit is not a proof of impossibility."}
    if model.kind == "scheduling":
        problem = model.problem
        notes["Basic Counting"] = (f"Product rule: {len(problem.slots)} choices for each of {len(problem.tasks)} tasks give "
                                   f"{len(problem.slots) ** len(problem.tasks):,} assignments before conflict constraints. This counts candidates, not valid schedules or actual search steps.")
        notes["Graph Theory"] = "Tasks are vertices and conflict pairs are edges. Slots act as colours; adjacent vertices must receive different colours. Feasibility does not establish the chromatic number."
    elif model.kind == "allocation":
        choices = [len(task.eligible) for task in model.problem.tasks]
        notes["Basic Counting"] = ("Product rule: multiplying eligible-resource choices per task (" + " × ".join(map(str, choices)) +
                                   f") gives {prod(choices):,} assignments before capacity constraints. This is not a count of feasible allocations.")
    else:
        notes["Graph Theory"] = "Locations and connections form an undirected graph. Reachability, predecessor trees, and shortest paths connect the input network to the routing model."
        notes["Logic and Proofs"] = ("Flow conservation states the route constraints. Dijkstra's correctness invariant is that settling the smallest tentative distance makes it final when edge costs are non-negative."
                                     if model.problem.weights is not None else
                                     "Flow conservation states the route constraints. BFS's distance-layer invariant establishes shortest paths by number of edges.")
    return notes


def explain_model(model: Model, result: Solution | Result | None = None) -> Explanation:
    definition = PROBLEM_TYPES.get(model.kind)
    algorithm = definition.solver_name if definition else "No algorithm registered for this model."
    limits = list(model.assumptions)
    if model.kind == "scheduling":
        algorithm = "Backtracking: try the most-conflicted tasks first, reject conflicting slots, and undo earlier choices when a later task cannot be placed."
        limits.append("The scheduler finds feasibility, not the fewest slots or balanced workloads. Attempt/time limits can leave feasibility unknown.")
    elif model.kind == "routing":
        algorithm = ("Dijkstra: repeatedly settle the lowest tentative cost and relax neighboring connections; reconstruct the route from the recorded predecessor tree."
                     if model.problem.weights is not None else
                     "Breadth-first search (BFS): explore a queue in distance layers, then reconstruct the minimum-hop route from discovery edges.")
        limits.append("Only the entered graph is solved; real-world travel costs are not inferred. Equal-cost routes can exist. Graph Explorer's search tree covers more than the selected route.")
    elif model.kind == "allocation":
        if model.problem.costs is None:
            algorithm = "Exact backtracking: try constrained/larger tasks first, reject capacity violations, and prune repeated remaining-capacity states. Stop at the first complete feasible allocation."
            limits.append("Feasibility mode does not minimize cost or balance workloads.")
        else:
            algorithm = "Exact branch and bound: retain the cheapest complete allocation, bound remaining cost using independent cheapest eligible assignments, and prune dominated repeated capacity states. Costs use exact integer hundredths."
            limits.append("Cost is per whole task–resource assignment, not per requirement unit. Every eligible pair needs a non-negative cost with at most two decimal places.")
        limits.append("A search limit can leave feasibility or optimality unknown. Only a complete verified allocation may be displayed; no partial assignment is a solution.")

    if not model.supported:
        algorithm = "Not run — this objective has no supported solver. " + model.support_note
        validity = "Model only. No solution or optimality claim is available for this objective."
    elif result is None:
        algorithm = "Available, not run yet — " + algorithm
        validity = "Not solved yet. The model describes the rules; no result has been verified."
    elif result.status == "limit":
        validity = "Search incomplete. No complete solution was found before the limit, and infeasibility has not been proved."
    elif result.status == "unsupported":
        validity = "No supported solver ran for this model. No solution is claimed."
    elif result.status == "infeasible":
        validity = ("No route exists: the search exhausted the start's connected component without reaching the destination."
                    if model.kind == "routing" else
                    "No feasible assignment exists: a necessary constraint failed or the exact search exhausted all remaining possibilities. This is a joint infeasibility result, not necessarily a minimal conflicting constraint set.")
    elif model.kind == "scheduling":
        validity = (f"Verified feasible: all {len(model.problem.tasks)} tasks have a listed slot, and all "
                    f"{len(model.problem.conflicts)} conflict pairs have different slots. The independent schedule audit checks these conditions. No minimum-slot claim is made.")
    elif model.kind == "routing":
        validity = ("Verified shortest route: every selected connection exists, node flow balances hold, and the route cost is checked. " +
                    ("Dijkstra's non-negative-cost invariant proves minimum total cost." if model.problem.weights is not None else
                     "BFS's layer order proves minimum hop count; it does not minimize unequal connection costs."))
    elif model.kind == "allocation":
        validity = "Verified feasible: every task is assigned once to an eligible resource, and independently summed requirements fit every capacity. "
        if result.optimal is True:
            validity += "Minimum cost proven: all potentially cheaper branches were explored or safely pruned. The chosen assignment costs are independently summed."
        elif result.optimal is False:
            validity += "Search limit reached: this is the best complete allocation found, not a proven minimum. Its total cost is an upper bound on the unknown optimum."
        else:
            validity += "Cost optimization was not requested; this is a feasibility witness only."
    else:
        validity = result.explanation
    if isinstance(result, Solution) and result.explanation and result.status != "solved":
        validity += " " + result.explanation
    domains = ", ".join(dict.fromkeys(variable.domain for variable in model.variables)) or "No decision variables"
    formulation = {
        "scheduling": "Each x[t] is the slot assigned to task t; conflicting tasks require unequal slots.",
        "routing": "Each binary f[i,j] selects a directed arc. Unit flow runs from source to destination; minimize the sum of selected arc costs.",
        "allocation": "Each binary x[t,r] assigns a whole task to an eligible resource. For each task, sum(x[t,r]) = 1; for each resource, sum(requirement[t] × x[t,r]) ≤ capacity[r].",
    }.get(model.kind, "")
    return Explanation(
        f"{formulation} {model.objective}. {len(model.variables)} decision variables; domains: {domains}. Variable definitions and input symbols are in the model inspector.",
        model.objective_expression,
        tuple(f"{constraint.name}: {constraint.expression} — {constraint.meaning}" for constraint in model.constraints),
        algorithm, validity, tuple(limits), tuple(method_notes(model).items()),
    )


def explain_schedule(problem: Problem, result: Result) -> Explanation:
    # Reuse the existing model translation; never run or modify a solver here.
    model = scheduling_model(list(problem.tasks), list(problem.slots), list(problem.conflicts))
    explanation = explain_model(model, result)
    return Explanation(
        f"One slot-valued variable x[t] per task. x[t] belongs to the {len(problem.slots)} listed slots; "
        f"x[a] ≠ x[b] for each of {len(problem.conflicts)} conflict pairs. Find any feasible assignment.",
        explanation.objective, ("Each task receives exactly one of: " + ", ".join(problem.slots),) +
        tuple(f"{a} and {b} must occupy different slots." for a, b in problem.conflicts),
        explanation.algorithm, explanation.validity,
        explanation.limitations, explanation.concepts,
    )


def explain_traversal(graph: Graph, result: Traversal, index: int) -> Explanation:
    step = result.steps[index]
    method = result.method
    algorithm = {
        "BFS": "Breadth-first search uses a FIFO queue and explores hop-distance layers.",
        "DFS": "Depth-first search follows an unvisited neighbor recursively, then backtracks when that branch is exhausted.",
        "Dijkstra": "Dijkstra settles the smallest tentative cost, relaxes neighbors, and updates the predecessor tree.",
    }[method]
    invariant = {
        "BFS": "Marking nodes when discovered prevents repeated visits in cycles; FIFO order gives minimum-hop discovery paths.",
        "DFS": "The visited set prevents cycles from causing repeated first visits. Recursive return explores the remaining reachable branches; it does not prove shortest paths.",
        "Dijkstra": "With non-negative edge costs, the smallest tentative distance is final when settled. Unsettled distances remain tentative.",
    }[method]
    validity = (f"Complete traversal: {len(result.order)} reachable nodes were visited; {len(result.unreachable)} are unreachable from the chosen start. "
                if step.action == "Complete" else
                f"Playback step {index} of {len(result.steps) - 1}: this is an intermediate snapshot, not the completed result. ") + invariant
    return Explanation(
        f"G = (V, E): {len(graph.nodes)} locations and {len(graph.edges)} undirected connections. Start: {result.start}.",
        "Find minimum cost from the start to each reachable node" if method == "Dijkstra" else "Explore the start's reachable component",
        ("Follow only supplied connections; never record a second first visit to a node.",
         "Costs must be non-negative; distance(start) = 0." if method == "Dijkstra" else "The visited set prevents repeated exploration around cycles."),
        algorithm, validity,
        ("This panel explains the displayed search snapshot, not a separate source–destination allocation or route result.",
         "BFS minimizes hop count, not weighted cost; DFS proves no shortest-path objective. Both ignore edge costs." if method != "Dijkstra" else
         "Directed links and negative costs are unsupported. Equal-cost predecessor trees may differ.",
         "The traversal covers only the start's connected component; returning to Studio keeps the selected destination and route there."),
        (("Logic and Proofs", invariant), ("Graph Theory", "Reachability, connected components, and a search tree describe exploration of the input graph.")),
    )


def render_explanation(explanation: Explanation) -> None:
    import streamlit as st

    with st.expander("Solution explanation"):
        for title, value in (("Mathematical model", explanation.model), ("Objective", explanation.objective)):
            st.markdown(f"**{title}**")
            st.write(value)
        st.markdown("**Key constraints**")
        for constraint in explanation.constraints:
            st.write("• " + constraint)
        st.markdown("**Algorithm used**")
        st.write(explanation.algorithm)
        st.markdown("**Why this result is valid / what is established**")
        st.write(explanation.validity)
        st.markdown("**Limitations**")
        for limitation in explanation.limitations:
            st.write("• " + limitation)
        st.markdown("**Relevant syllabus concepts**")
        for area, detail in explanation.concepts:
            st.markdown(f"**{area}**")
            st.write(detail)
        unused = "; ".join(area for area in SYLLABUS_AREAS if area not in dict(explanation.concepts))
        st.caption(f"No coverage claimed here: {unused}. Naming a relevant concept does not claim coverage of its whole syllabus unit. Recursion alone is not a recurrence-relation or generating-function analysis.")
