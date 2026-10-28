"""Exact, capacity-constrained assignment of whole tasks; no UI dependencies."""

from dataclasses import dataclass
from time import perf_counter
from typing import Literal, Mapping, Sequence


MAX_RESOURCES = 8
MAX_TASKS = 16
MAX_UNITS = 1_000_000_000
MAX_NAME_LENGTH = 40


@dataclass(frozen=True)
class Resource:
    name: str
    capacity: int


@dataclass(frozen=True)
class Task:
    name: str
    requirement: int
    eligible: tuple[str, ...]


@dataclass(frozen=True)
class AllocationProblem:
    resources: tuple[Resource, ...]
    tasks: tuple[Task, ...]


@dataclass(frozen=True)
class AllocationResult:
    status: Literal["solved", "infeasible", "limit"]
    assignments: tuple[tuple[str, str], ...] = ()
    used: tuple[tuple[str, int], ...] = ()
    issues: tuple[str, ...] = ()
    attempts: int = 0


def validate_names(names: Sequence[str], kind: str, maximum: int) -> tuple[str, ...]:
    clean = tuple(name.strip() for name in names)
    if not clean or any(not name for name in clean):
        raise ValueError(f"Add at least one {kind}; names cannot be blank.")
    if len(clean) > maximum:
        raise ValueError(f"Use at most {maximum} {kind}s.")
    if len({name.casefold() for name in clean}) != len(clean):
        raise ValueError(f"Give each {kind} a unique name, ignoring case.")
    if any(len(name) > MAX_NAME_LENGTH for name in clean):
        raise ValueError(f"Keep {kind} names to {MAX_NAME_LENGTH} characters or fewer.")
    return clean


def make_allocation_problem(resources: Sequence[str], tasks: Sequence[str],
                            capacities: Mapping[str, int], requirements: Mapping[str, int],
                            eligible: Mapping[str, Sequence[str]]) -> AllocationProblem:
    resources = validate_names(resources, "resource", MAX_RESOURCES)
    tasks = validate_names(tasks, "task", MAX_TASKS)
    for names, quantities, minimum, label in ((resources, capacities, 0, "Capacity"),
                                             (tasks, requirements, 1, "Task requirement")):
        for name in names:
            value = quantities.get(name)
            if type(value) is not int or not minimum <= value <= MAX_UNITS:
                raise ValueError(f"{label} for {name} must be a whole number from {minimum} to {MAX_UNITS}.")
    normalized = []
    for name in tasks:
        if name not in eligible or isinstance(eligible[name], str):
            raise ValueError(f"Choose the eligible resources for {name}; an empty selection is allowed but infeasible.")
        if set(eligible[name]) - set(resources):
            raise ValueError(f"Eligible resources for {name} must exist in the resource list.")
        normalized.append(Task(name, requirements[name], tuple(resource for resource in resources if resource in eligible[name])))
    return AllocationProblem(tuple(Resource(name, capacities[name]) for name in resources), tuple(normalized))


def audit_allocation(problem: AllocationProblem, assignments: Mapping[str, str]) -> tuple[tuple[str, ...], dict[str, int]]:
    """Independently check every task assignment and each resource's total load."""
    used = {resource.name: 0 for resource in problem.resources}
    issues = []
    if set(assignments) - {task.name for task in problem.tasks}:
        issues.append("The allocation contains unrequested tasks.")
    for task in problem.tasks:
        resource = assignments.get(task.name)
        if resource is None:
            issues.append(f"{task.name} is unassigned.")
        elif resource not in used:
            issues.append(f"{task.name} is assigned to an undefined resource.")
        else:
            used[resource] += task.requirement
            if resource not in task.eligible:
                issues.append(f"{task.name} cannot use {resource}.")
    for resource in problem.resources:
        if used[resource.name] > resource.capacity:
            issues.append(f"{resource.name} exceeds capacity by {used[resource.name] - resource.capacity} units.")
    return tuple(issues), used


def solve_allocation(problem: AllocationProblem, *, max_attempts: int = 50_000,
                     time_limit: float = 2.0) -> AllocationResult:
    """Backtrack over eligible resources, pruning capacity violations and repeated states.

    Only exhaustive failure (or a proved necessary-condition failure) means
    infeasible. Limits return no partial allocation and make no feasibility claim.
    """
    problem = make_allocation_problem(
        [resource.name for resource in problem.resources], [task.name for task in problem.tasks],
        {resource.name: resource.capacity for resource in problem.resources},
        {task.name: task.requirement for task in problem.tasks}, {task.name: task.eligible for task in problem.tasks})
    if max_attempts < 0 or time_limit < 0:
        raise ValueError("Search limits must be non-negative.")
    capacities = {resource.name: resource.capacity for resource in problem.resources}
    issues = []
    demand = sum(task.requirement for task in problem.tasks)
    if demand > sum(capacities.values()):
        issues.append(f"Total task demand is {demand}, but total capacity is {sum(capacities.values())}; short by {demand - sum(capacities.values())} units.")
    for task in problem.tasks:
        if not task.eligible:
            issues.append(f"{task.name} must be assigned once, but has no eligible resource.")
        elif all(task.requirement > capacities[name] for name in task.eligible):
            issues.append(f"{task.name} needs {task.requirement} units; its largest eligible resource has only {max(capacities[name] for name in task.eligible)}.")
    if issues:
        return AllocationResult("infeasible", issues=tuple(issues))

    order = sorted(problem.tasks, key=lambda task: (len(task.eligible), -task.requirement))
    remaining = capacities.copy()
    assignments = {}
    failed = set()
    attempts = 0
    started = perf_counter()

    def search(index: int) -> bool | None:
        nonlocal attempts
        if index == len(order):
            return True
        if attempts >= max_attempts or perf_counter() - started >= time_limit:
            return None
        state = (index, tuple(remaining.values()))
        if state in failed:
            return False
        task = order[index]
        for resource in task.eligible:
            if attempts >= max_attempts or perf_counter() - started >= time_limit:
                return None
            attempts += 1
            if task.requirement > remaining[resource]:
                continue
            assignments[task.name] = resource
            remaining[resource] -= task.requirement
            result = search(index + 1)
            if result is True:
                return True
            remaining[resource] += task.requirement
            del assignments[task.name]
            if result is None:
                return None
        failed.add(state)
        return False

    outcome = search(0)
    if outcome is None:
        return AllocationResult("limit", issues=("No allocation found within the search limit. Feasibility is unknown; no partial assignment is presented.",), attempts=attempts)
    if not outcome:
        return AllocationResult("infeasible", issues=("Exhaustive search found that assigning every whole task to an eligible resource and respecting all capacities is impossible. These constraints conflict jointly, even if total capacity is sufficient.",), attempts=attempts)
    violations, used = audit_allocation(problem, assignments)
    if violations:
        raise RuntimeError("The allocation failed independent verification: " + " ".join(violations))
    return AllocationResult("solved", tuple((task.name, assignments[task.name]) for task in problem.tasks),
                            tuple(used.items()), attempts=attempts)
