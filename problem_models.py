"""Input-to-model translation and adapters for existing solvers; no Streamlit."""

from dataclasses import dataclass
from math import fsum, isclose
from typing import Callable, Literal

from allocation_solver import make_allocation_problem, solve_allocation
from graph_algorithms import Traversal, make_graph, route_to, traverse
from solver import Result, audit_schedule, make_problem, solve


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
    kind: str
    parameters: tuple[tuple[str, str], ...]
    variables: tuple[Variable, ...]
    constraints: tuple[Constraint, ...]
    objective: str
    objective_expression: str
    objective_explanation: str
    assumptions: tuple[str, ...]
    supported: bool
    support_note: str
    problem: object  # Validated domain data, owned by the registered adapter.
    source: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class ResultTable:
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str | int | float, ...], ...]


@dataclass(frozen=True)
class Solution:
    status: Literal["solved", "infeasible", "limit", "unsupported"]
    explanation: str
    values: tuple[tuple[str, str | int], ...] = ()
    schedule: tuple[tuple[str, str], ...] = ()
    route: tuple[str, ...] = ()
    objective_value: int | float | None = None
    schedule_trace: Result | None = None
    traversal: Traversal | None = None
    tables: tuple[ResultTable, ...] = ()
    diagnostics: tuple[str, ...] = ()
    optimal: bool | None = None


@dataclass(frozen=True)
class ProblemType:
    """One supported formulation; the Studio lifecycle is shared by all types."""

    label: str
    description: str
    input_defaults: dict
    example: dict
    build_model: Callable[[dict], Model]
    solve: Callable[[Model], Solution]
    solver_name: str
    inspector: str | None = None
    inspector_label: str = "Inspect result"


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


def routing_model(nodes: list[str], edges: list[tuple[str, str]], source: str, target: str,
                  weights: dict[tuple[str, str], float] | None = None) -> Model:
    graph = make_graph(nodes, edges, weights)
    weighted = weights is not None
    costs = {frozenset(edge): cost for edge, cost in graph.costs().items()}
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
                   (("source", source), ("destination", target)) +
                   tuple((f"cost {ids[a]} ↔ {ids[b]}", f"{cost:.15g}") for (a, b), cost in graph.costs().items()),
        variables=variables, constraints=tuple(constraints),
        objective="Minimize total route cost" if weighted else "Minimize the number of connections",
        objective_expression="min " + (" + ".join(f"{costs[frozenset((a, b))]:.15g} · {_arc_symbol(a, b, ids)}" for a, b in arcs) or "0"),
        objective_explanation=("Multiply each selected arc by its connection cost and minimize their sum. Costs use one consistent unit. Zero-cost cycles may tie in the flow model; the solver returns a simple route without cycles."
                               if weighted else "Each selected arc costs one hop. Minimize their sum. Positive unit costs exclude cycles from an optimal route."),
        assumptions=("One source and one destination; connections work both ways with the same non-negative cost." if weighted else
                     "One source and one destination; all connections are undirected and have equal unit cost.",
                     "Each undirected connection becomes two directed binary arc variables. A value of 1 selects that direction.",
                     "One-way links, negative costs, capacities, and multiple simultaneous routes are not supported."),
        supported=True,
        support_note=("Supported by Dijkstra's algorithm in the shared graph module. It minimizes total cost, which may require more connections."
                      if weighted else "Supported by the existing BFS traversal. Its discovery tree gives a minimum-hop route in an unweighted graph."),
        problem=graph, source=source, target=target,
    )


def _solve_scheduling(model: Model) -> Solution:
    problem = model.problem
    result = solve(problem)
    if result.status == "infeasible":
        return Solution("infeasible", "The backtracking search exhausted all branches. No assignment satisfies these task conflicts with the supplied slots.", schedule_trace=result)
    if result.status == "limit":
        return Solution("limit", "The scheduler reached its search limit. Feasibility is unknown; no partial assignment is shown.", schedule_trace=result)
    if audit_schedule(problem, result.assignments):
        raise RuntimeError("The schedule failed independent verification.")
    slot_ids = {slot: f"s{index}" for index, slot in enumerate(problem.slots, 1)}
    return Solution("solved", f"All {len(problem.tasks)} tasks receive one listed slot, and all {len(problem.conflicts)} conflict pairs occupy different slots. The assignment was independently verified. This satisfies the feasibility objective; it does not prove the fewest slots.",
                    values=tuple((f"x[{index}]", slot_ids[result.assignments[task]])
                                 for index, task in enumerate(problem.tasks, 1)),
                    schedule=tuple(result.assignments.items()), objective_value=0, schedule_trace=result)


def _solve_routing(model: Model) -> Solution:
    graph = model.problem
    weighted = graph.weights is not None
    method = "Dijkstra" if weighted else "BFS"
    traversal = traverse(graph, model.source, method)
    path = route_to(traversal, model.target)
    if not path:
        return Solution("infeasible", f"{model.target} is disconnected from {model.source}. {method} exhausted all reachable locations without finding a route. Add a connection or choose another destination; no total cost is reported.", traversal=traversal)
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
    costs = {frozenset(edge): cost for edge, cost in graph.costs().items()}
    total = fsum(costs[frozenset(edge)] for edge in chosen)
    if weighted and not isclose(total, dict(traversal.steps[-1].distances)[model.target]):
        raise RuntimeError("The route cost failed verification.")
    explanation = ("Dijkstra settles the location with the smallest tentative cost and improves costs to its neighbors. With non-negative costs, settled distances are final, so no cheaper route exists. Equal-cost alternatives may exist."
                   if weighted else "BFS explores nodes in increasing hop distance, so no route with fewer connections exists.")
    return Solution("solved", explanation + " Every selected connection, the total cost, and all node flow balances were verified.",
                    values=tuple((_arc_symbol(a, b, ids), int((a, b) in chosen)) for a, b in arcs),
                    route=path, objective_value=total, traversal=traversal)


def allocation_model(resources: list[str], tasks: list[str], capacities: dict[str, int],
                     requirements: dict[str, int], eligible: dict[str, list[str]],
                     goal: str = "feasible", costs: dict | None = None) -> Model:
    if goal not in ("feasible", "min_cost"):
        raise ValueError("Choose feasibility or minimum allocation cost.")
    optimize = goal == "min_cost"
    problem = make_allocation_problem(resources, tasks, capacities, requirements, eligible,
                                      (costs or {}) if optimize else None)
    symbols = {(task.name, resource.name): f"a[{i},{j}]"
               for i, task in enumerate(problem.tasks, 1) for j, resource in enumerate(problem.resources, 1)
               if resource.name in task.eligible}
    variables = tuple(Variable(symbol, "{0, 1}", f"1 assigns the whole task {task} to {resource}; otherwise 0.")
                      for (task, resource), symbol in symbols.items())
    constraints = [Constraint(f"Assign {task.name} once",
                              (" + ".join(symbols[(task.name, resource)] for resource in task.eligible) or "0") + " = 1",
                              "Assign the entire task to exactly one eligible resource. No splitting or dropping tasks.")
                   for task in problem.tasks]
    constraints.extend(Constraint(f"Capacity of {resource.name}",
                                  (" + ".join(f"{task.requirement} · {symbols[(task.name, resource.name)]}"
                                              for task in problem.tasks if resource.name in task.eligible) or "0") + f" ≤ {resource.capacity}",
                                  "The total requirements assigned here cannot exceed this resource's capacity.")
                       for resource in problem.resources)
    return Model(
        kind="allocation",
        parameters=tuple((f"resource {i}", f"{resource.name}: capacity {resource.capacity}")
                         for i, resource in enumerate(problem.resources, 1)) +
                   tuple((f"task {i}", f"{task.name}: requires {task.requirement}")
                         for i, task in enumerate(problem.tasks, 1)),
        variables=variables, constraints=tuple(constraints),
        objective="Minimize total allocation cost" if optimize else "Find a feasible allocation",
        objective_expression=("min " + (" + ".join(f"{cost / 100:.2f} · {symbols[(task, resource)]}"
                                                   for task, resource, cost in problem.costs) or "0")
                              if optimize else "min 0  subject to all constraints"),
        objective_explanation=("Sum the full cost of assigning each task to its chosen resource. Costs are per whole assignment, not per capacity unit. A result is optimal only when the search proves no cheaper feasible allocation exists."
                               if optimize else "All complete allocations satisfying eligibility and capacity constraints are equally acceptable. This does not minimize cost or balance workloads."),
        assumptions=("Each whole task uses exactly one eligible resource. A task cannot be split across resources.",
                     "Capacities and requirements are whole numbers in one common unit, over one shared planning period.",
                     "All tasks are mandatory. No timing, sequencing, or simultaneous requirements for different resource types are modelled."),
        supported=True, support_note="Supported by exact branch and bound with capacity and cost pruning. Search limits never imply optimality or infeasibility.",
        problem=problem,
    )


def _solve_allocation(model: Model) -> Solution:
    problem = model.problem
    result = solve_allocation(problem)
    if result.status != "solved":
        explanation = ("No feasible allocation exists for these inputs." if result.status == "infeasible" else
                       "No feasible allocation was found before the search limit; this is not a proof of infeasibility.")
        return Solution(result.status, explanation, diagnostics=result.issues)
    assigned, used = dict(result.assignments), dict(result.used)
    costs = {(task, resource): cost for task, resource, cost in problem.costs or ()}
    quality = ("Minimum total cost proven: every remaining branch was exhausted or ruled out by a valid lower bound."
               if result.optimal is True else "Search limit reached. This complete allocation is feasible, but its cost is not proven optimal."
               if result.optimal is False else "This is a feasible allocation; cost minimization was not requested.")
    columns = ("Task", "Resource", "Requirement", "Assignment check") + (("Assignment cost",) if problem.costs is not None else ())
    return Solution(
        "solved", f"All {len(problem.tasks)} tasks were assigned exactly once to eligible resources. Every capacity was independently checked; no constraints are unsatisfied. The search tried {result.attempts} placements. {quality}",
        values=tuple((f"a[{i},{j}]", int(assigned[task.name] == resource.name))
                     for i, task in enumerate(problem.tasks, 1) for j, resource in enumerate(problem.resources, 1)
                     if resource.name in task.eligible), objective_value=result.total_cost / 100 if result.total_cost is not None else 0,
        optimal=result.optimal,
        tables=(ResultTable("Task allocation", columns,
                            tuple((task.name, assigned[task.name], task.requirement, "Satisfied · eligible, assigned once") +
                                  ((f"{costs[(task.name, assigned[task.name])] / 100:.2f}",) if problem.costs is not None else ())
                                  for task in problem.tasks)),
                ResultTable("Resource capacity", ("Resource", "Capacity", "Used", "Remaining", "Capacity check"),
                            tuple((resource.name, resource.capacity, used[resource.name], resource.capacity - used[resource.name], "Satisfied")
                                  for resource in problem.resources))),
    )


def input_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


PROBLEM_TYPES = {
    "scheduling": ProblemType(
        label="Task scheduling",
        description="Assign activities to non-overlapping slots while keeping conflicting pairs apart. Useful for workshops, meetings, or shared-resource activities with explicit pairwise conflicts.",
        input_defaults={"tasks": "", "slots": "", "conflicts": [], "goal": "feasible"},
        example={"tasks": "Review\nBuild\nDemo", "slots": "Morning\nAfternoon",
                 "conflicts": [("Review", "Demo"), ("Build", "Demo")]},
        build_model=lambda data: scheduling_model(input_lines(data["tasks"]), input_lines(data["slots"]), data["conflicts"], data["goal"]),
        solve=_solve_scheduling,
        solver_name="Backtracking — valid schedules only; slot minimization is model-only",
        inspector="workbench", inspector_label="Inspect in Workbench ↗",
    ),
    "routing": ProblemType(
        label="Network routing",
        description="Find the lowest-cost route between locations. Enter two-way connections and a cost for each: distance, travel time, or expense, using the same unit throughout.",
        input_defaults={"nodes": "", "edges": [], "weights": {}, "source": None, "target": None},
        example={"nodes": "Depot\nJunction\nHarbour\nAirport",
                 "edges": [("Depot", "Junction"), ("Depot", "Harbour"), ("Depot", "Airport"), ("Junction", "Airport"), ("Harbour", "Airport")],
                 "weights": {("Depot", "Junction"): 3.0, ("Depot", "Harbour"): 1.0, ("Depot", "Airport"): 12.0,
                             ("Junction", "Airport"): 2.0, ("Harbour", "Airport"): 7.0},
                 "source": "Depot", "target": "Airport"},
        build_model=lambda data: routing_model(input_lines(data["nodes"]), data["edges"], data["source"], data["target"], data["weights"]),
        solve=_solve_routing, solver_name="Dijkstra — minimum total cost with non-negative connections",
        inspector="graphs", inspector_label="Visualize in Graph Explorer ↗",
    ),
    "allocation": ProblemType(
        label="Resource allocation",
        description="Assign whole tasks to eligible resources without exceeding their capacities. Use one shared unit, such as available work hours across teams, for both capacities and task requirements.",
        input_defaults={"allocation_resources": "", "allocation_tasks": "", "capacities": {}, "requirements": {}, "eligible_resources": {},
                        "allocation_goal": "feasible", "allocation_costs": {}},
        example={"allocation_resources": "Team North\nTeam South", "allocation_tasks": "Install\nInspect\nDocument\nHandover",
                 "capacities": {"Team North": 8, "Team South": 6},
                 "requirements": {"Install": 6, "Inspect": 4, "Document": 3, "Handover": 1},
                 "eligible_resources": {task: ["Team North", "Team South"] for task in ("Install", "Inspect", "Document", "Handover")},
                 "allocation_costs": {(task, resource): cost for task, north, south in
                                      (("Install", 40, 30), ("Inspect", 20, 25), ("Document", 12.5, 15), ("Handover", 5, 6))
                                      for resource, cost in (("Team North", north), ("Team South", south))}},
        build_model=lambda data: allocation_model(input_lines(data["allocation_resources"]), input_lines(data["allocation_tasks"]),
                                                  data["capacities"], data["requirements"], data["eligible_resources"],
                                                  data.get("allocation_goal", "feasible"), data.get("allocation_costs")),
        solve=_solve_allocation, solver_name="Exact branch and bound — feasibility or minimum total allocation cost",
    ),
}


def solve_model(model: Model) -> Solution:
    """Dispatch explicitly; unknown types never fall through to another solver."""
    definition = PROBLEM_TYPES.get(model.kind)
    if definition is None:
        return Solution("unsupported", "No solver is registered for this problem type.")
    if not model.supported:
        return Solution("unsupported", model.support_note)
    return definition.solve(model)
