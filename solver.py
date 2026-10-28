"""A small, deterministic backtracking scheduler, independent of Streamlit.

Every task occupies exactly one slot. Non-conflicting tasks may share a slot;
a conflict is an undirected pair that must receive different slots.
"""

from dataclasses import dataclass
from time import perf_counter
from typing import Iterable, Literal, Mapping, Sequence


MAX_TASKS = 24
MAX_SLOTS = 12
MAX_LABEL_LENGTH = 80


class InvalidProblem(ValueError):
    def __init__(self, issues: Sequence[str]):
        self.issues = tuple(issues)
        super().__init__(" ".join(issues))


@dataclass(frozen=True)
class Problem:
    tasks: tuple[str, ...]
    slots: tuple[str, ...]
    conflicts: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Collision:
    attempt: int
    task: str
    slot: str
    blocking_tasks: tuple[str, ...]


@dataclass(frozen=True)
class Result:
    status: Literal["solved", "infeasible", "limit"]
    assignments: dict[str, str]
    attempts: int
    rejected: int
    backtracks: int
    elapsed_ms: float
    collisions: tuple[Collision, ...]
    limit_reason: str | None = None


def make_problem(tasks: Sequence[str], slots: Sequence[str],
                 conflicts: Iterable[tuple[str, str]]) -> Problem:
    """Validate labels and canonicalize duplicate/reversed conflict pairs."""
    issues = []
    normalized = []
    for kind, labels, maximum in (("tasks", tasks, MAX_TASKS), ("time slots", slots, MAX_SLOTS)):
        clean = tuple(label.strip() for label in labels)
        if not clean:
            issues.append("Add at least one task." if kind == "tasks" else "Add at least one time slot.")
        if any(not label for label in clean):
            issues.append(f"Names for {kind} cannot be blank.")
        if len(clean) > maximum:
            issues.append(f"Use at most {maximum} {kind} per schedule.")
        if any(len(label) > MAX_LABEL_LENGTH for label in clean):
            issues.append(f"Keep each name for {kind} to {MAX_LABEL_LENGTH} characters or fewer.")
        if len({label.casefold() for label in clean}) != len(clean):
            issues.append(f"Give each of the {kind} a unique name (ignoring case).")
        normalized.append(clean)
    clean_tasks, clean_slots = normalized
    order = {task: i for i, task in enumerate(clean_tasks)}
    pairs = set()
    for pair in conflicts:
        if len(pair) != 2:
            issues.append("Each conflict must name exactly two tasks.")
            continue
        a, b = (name.strip() for name in pair)
        if a not in order or b not in order:
            issues.append("Every conflict must refer to tasks in the current task list.")
        elif a == b:
            issues.append(f'"{a}" cannot conflict with itself; choose two different tasks.')
        else:
            pairs.add(tuple(sorted((a, b), key=order.__getitem__)))
    if issues:
        raise InvalidProblem(list(dict.fromkeys(issues)))
    return Problem(clean_tasks, clean_slots,
                   tuple(sorted(pairs, key=lambda pair: (order[pair[0]], order[pair[1]]))))


def audit_schedule(problem: Problem, assignments: Mapping[str, str]) -> tuple[str, ...]:
    """Independently check a candidate schedule; return every violated rule."""
    violations = []
    for task in problem.tasks:
        if task not in assignments:
            violations.append(f'"{task}" has no assigned slot.')
        elif assignments[task] not in problem.slots:
            violations.append(f'"{task}" is assigned to an undefined slot.')
    if set(assignments) - set(problem.tasks):
        violations.append("The schedule contains tasks that were not requested.")
    for a, b in problem.conflicts:
        if a in assignments and b in assignments and assignments[a] == assignments[b]:
            violations.append(f'"{a}" and "{b}" conflict in "{assignments[a]}".')
    return tuple(violations)


def solve(problem: Problem, *, max_attempts: int = 50_000,
          time_limit: float = 2.0) -> Result:
    """Search until a valid schedule, exhaustive failure, or an explicit limit.

    Tasks with the most conflicts are tried first, with input-order tie breaking.
    A failed assignment is undone before the next slot is tried. Search limits
    never count as proof of infeasibility and never return partial schedules.
    """
    problem = make_problem(problem.tasks, problem.slots, problem.conflicts)
    if max_attempts < 0 or time_limit < 0:
        raise ValueError("Search limits must be non-negative.")
    start = perf_counter()
    neighbors = {task: set() for task in problem.tasks}
    for a, b in problem.conflicts:
        neighbors[a].add(b)
        neighbors[b].add(a)
    order = sorted(problem.tasks, key=lambda task: -len(neighbors[task]))
    assignments: dict[str, str] = {}
    collisions: list[Collision] = []
    attempts = rejected = backtracks = 0
    limit_reason = None

    def search(index: int) -> bool | None:
        nonlocal attempts, rejected, backtracks, limit_reason
        if index == len(order):
            return True
        task = order[index]
        for slot in problem.slots:
            if attempts >= max_attempts:
                limit_reason = "attempts"
                return None
            if perf_counter() - start >= time_limit:
                limit_reason = "time"
                return None
            attempts += 1
            blockers = tuple(other for other in problem.tasks
                             if other in neighbors[task] and assignments.get(other) == slot)
            if blockers:
                rejected += 1
                if len(collisions) < 20:
                    collisions.append(Collision(attempts, task, slot, blockers))
                continue
            assignments[task] = slot
            outcome = search(index + 1)
            if outcome is True:
                return True
            del assignments[task]
            if outcome is None:
                return None
            backtracks += 1
        return False

    outcome = search(0)
    status = "solved" if outcome is True else "infeasible" if outcome is False else "limit"
    final = {task: assignments[task] for task in problem.tasks} if outcome is True else {}
    if outcome is True and audit_schedule(problem, final):
        raise RuntimeError("The generated schedule failed independent verification.")
    return Result(status, final, attempts, rejected, backtracks,
                  (perf_counter() - start) * 1000, tuple(collisions), limit_reason)
