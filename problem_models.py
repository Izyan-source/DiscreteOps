"""Input-to-model translation and adapters for existing solvers; no Streamlit."""

from dataclasses import dataclass
from typing import Literal

from graph_algorithms import Graph, make_graph, traverse
from solver import Problem, audit_schedule, make_problem, solve


@dataclass(frozen=True)
class Variable:
    symbol: str
    domain: str
    meaning: str


@dataclass(frozen=True)
class Constraint:
    name: str
    expression: str
    meaning: str


@dataclass(frozen=True)
class Model:
    kind: Literal["scheduling", "routing"]
    parameters: tuple[tuple[str, str], ...]
    variables: tuple[Variable, ...]
    constraints: tuple[Constraint, ...]
    objective: str
    objective_expression: str
    objective_explanation: str
    assumptions: tuple[str, ...]
    supported: bool
    support_note: str
    problem: Problem | Graph
    source: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class Solution:
    status: Literal["solved", "infeasible", "limit", "unsupported"]
    explanation: str
    values: tuple[tuple[str, str | int], ...] = ()
    schedule: tuple[tuple[str, str], ...] = ()
    route: tuple[str, ...] = ()
    objective_value: int | None = None


def scheduling_model(tasks: list[str], slots: list[str], conflicts: list[tuple[str, str]],
                     goal: str = "feasible") -> Model:
    problem = make_problem(tasks, slots, conflicts)
    if goal not in ("feasible", "fewest_slots"):
        raise ValueError("Unsupported scheduling goal. Choose feasibility or fewest slots.")
    task_ids = {task: index for index, task in enumerate(problem.tasks, 1)}
    slot_ids = tuple(f"s{index}" for index in range(1, len(problem.slots) + 1))
    domain = "{" + ", ".join(slot_ids) + "}"
    variables = tuple(Variable(f"x[{index}]", domain, f"Slot assigned to {task}")
                      for index, task in enumerate(problem.tasks, 1))
    constraints = [Constraint(f"Assign {task}", f"x[{index}] ∈ {domain}",
                              "One slot-valued variable gives this task exactly one listed slot.")
                   for index, task in enumerate(problem.tasks, 1)]
    constraints.extend(Constraint(f"{a} / {b}", f"x[{task_ids[a]}] ≠ x[{task_ids[b]}]",
                                  "These tasks must occupy different slots.") for a, b in problem.conflicts)
    feasible = goal == "feasible"
    return Model(
        kind="scheduling",
        parameters=tuple((f"task {index}", task) for index, task in enumerate(problem.tasks, 1)) +
                   tuple(zip(slot_ids, problem.slots)),
        variables=variables, constraints=tuple(constraints),
        objective="Find a valid schedule" if feasible else "Minimize used slots",
        objective_expression="min 0  subject to all constraints" if feasible else
                             "min |{" + ", ".join(variable.symbol for variable in variables) + "}|",
        objective_explanation=("This is a feasibility problem. Any assignment satisfying all constraints is acceptable; no schedule is preferred over another."
                               if feasible else "Minimize the number of distinct slot values used by the tasks. The bars count distinct values, not tasks."),
        assumptions=("Each task occupies one complete slot. Non-conflicting tasks may share a slot.",
                     "Slots are labels for distinct, non-overlapping periods; clock times are not parsed.",
                     "Durations, deadlines, precedence, and resource capacities are outside this model."),
        supported=feasible,
        support_note=("Supported by the existing backtracking scheduler. A search limit is inconclusive."
                      if feasible else "Model only — the current scheduler finds a valid schedule but cannot prove the fewest slots. Solving this objective is not supported."),
        problem=problem,
    )


def _arc_symbol(a: str, b: str, ids: dict[str, int]) -> str:
    return f"f[{ids[a]},{ids[b]}]"


def routing_model(nodes: list[str], edges: list[tuple[str, str]], source: str, target: str) -> Model:
    graph = make_graph(nodes, edges)
    if source not in graph.nodes or target not in graph.nodes:
        raise ValueError("Choose an existing source and destination node.")
    if source == target:
        raise ValueError("Choose different source and destination nodes for this routing model.")
    ids = {node: index for index, node in enumerate(graph.nodes, 1)}
    arcs = [(a, b) for edge in graph.edges for a, b in (edge, edge[::-1])]
    variables = tuple(Variable(_arc_symbol(a, b, ids), "{0, 1}", f"1 if the route uses {a} → {b}; otherwise 0")
                      for a, b in arcs)
    constraints = []
    for node in graph.nodes:
        outgoing = " + ".join(_arc_symbol(a, b, ids) for a, b in arcs if a == node) or "0"
        incoming = " + ".join(_arc_symbol(a, b, ids) for a, b in arcs if b == node) or "0"
        balance = 1 if node == source else -1 if node == target else 0
        meaning = ("Send one net unit from the source." if node == source else
                   "Receive one net unit at the destination." if node == target else
                   "Incoming flow equals outgoing flow.")
        constraints.append(Constraint(f"Flow at {node}", f"({outgoing}) − ({incoming}) = {balance}", meaning))
    return Model(
        kind="routing",
        parameters=tuple((f"node {index}", node) for index, node in enumerate(graph.nodes, 1)) +
                   (("source", source), ("destination", target)),
        variables=variables, constraints=tuple(constraints),
        objective="Minimize the number of connections",
        objective_expression="min " + (" + ".join(variable.symbol for variable in variables) or "0"),
        objective_explanation="Each selected arc costs one hop. Minimize their sum. Positive unit costs exclude cycles from an optimal route.",
        assumptions=("One source and one destination; all connections are undirected and have equal unit cost.",
                     "Each undirected connection becomes two directed binary arc variables. A value of 1 selects that direction.",
                     "Weighted costs, one-way links, capacities, and multiple simultaneous routes are not supported."),
        supported=True,
        support_note="Supported by the existing BFS traversal. Its discovery tree gives a minimum-hop route in an unweighted graph.",
        problem=graph, source=source, target=target,
    )


def solve_model(model: Model) -> Solution:
    """Execute only supported models; never downgrade an optimization request."""
    if not model.supported:
        return Solution("unsupported", model.support_note)
    if model.kind == "scheduling":
        problem = model.problem
        result = solve(problem)
        if result.status == "infeasible":
            return Solution("infeasible", "The backtracking search exhausted all branches. No assignment satisfies these task conflicts with the supplied slots.")
        if result.status == "limit":
            return Solution("limit", "The scheduler reached its search limit. Feasibility is unknown; no partial assignment is shown.")
        if audit_schedule(problem, result.assignments):
            raise RuntimeError("The schedule failed independent verification.")
        slot_ids = {slot: f"s{index}" for index, slot in enumerate(problem.slots, 1)}
        return Solution("solved", f"All {len(problem.tasks)} tasks receive one listed slot, and all {len(problem.conflicts)} conflict pairs occupy different slots. The assignment was independently verified. This satisfies the feasibility objective; it does not prove the fewest slots.",
                        values=tuple((f"x[{index}]", slot_ids[result.assignments[task]])
                                     for index, task in enumerate(problem.tasks, 1)),
                        schedule=tuple(result.assignments.items()), objective_value=0)

    graph = model.problem
    traversal = traverse(graph, model.source, "BFS")
    if model.target not in traversal.order:
        return Solution("infeasible", "BFS exhausted the source's connected component without reaching the destination. No route satisfies the flow constraints.")
    parents = {child: parent for parent, child in traversal.steps[-1].tree_edges}
    path = [model.target]
    while path[-1] != model.source:
        path.append(parents[path[-1]])
    path.reverse()
    chosen = set(zip(path, path[1:]))
    ids = {node: index for index, node in enumerate(graph.nodes, 1)}
    arcs = [(a, b) for edge in graph.edges for a, b in (edge, edge[::-1])]
    if not chosen.issubset(set(arcs)) or len(set(path)) != len(path):
        raise RuntimeError("The reconstructed route failed verification.")
    for node in graph.nodes:
        balance = sum(a == node for a, b in chosen) - sum(b == node for a, b in chosen)
        expected = 1 if node == model.source else -1 if node == model.target else 0
        if balance != expected:
            raise RuntimeError("The route failed flow conservation verification.")
    return Solution("solved", "BFS explores nodes in increasing hop distance. This route follows its discovery tree to the destination, so no route with fewer connections exists. Every selected arc is an existing connection, and all node flow balances were verified.",
                    values=tuple((_arc_symbol(a, b, ids), int((a, b) in chosen)) for a, b in arcs),
                    route=tuple(path), objective_value=len(path) - 1)
