"""Small, undirected graphs and recorded BFS/DFS traversals. No UI dependencies."""

from collections import deque
from dataclasses import dataclass
from typing import Literal


MAX_NODES = 16
MAX_LABEL_LENGTH = 24
Edge = tuple[str, str]
Method = Literal["BFS", "DFS"]


@dataclass(frozen=True)
class Graph:
    nodes: tuple[str, ...]
    edges: tuple[Edge, ...]

    def neighbors(self) -> dict[str, tuple[str, ...]]:
        adjacent = {node: set() for node in self.nodes}
        for a, b in self.edges:
            adjacent[a].add(b)
            adjacent[b].add(a)
        # Input order is the tie-breaker for both algorithms.
        return {node: tuple(other for other in self.nodes if other in adjacent[node])
                for node in self.nodes}


@dataclass(frozen=True)
class Step:
    action: str
    current: str | None
    visited: tuple[str, ...]
    frontier: tuple[str, ...]
    tree_edges: tuple[Edge, ...]
    explanation: str


@dataclass(frozen=True)
class Traversal:
    method: Method
    start: str
    steps: tuple[Step, ...]
    order: tuple[str, ...]
    unreachable: tuple[str, ...]


def make_graph(nodes: list[str] | tuple[str, ...], edges: list[Edge] | tuple[Edge, ...]) -> Graph:
    """Validate a simple graph and normalize duplicate/reversed edges."""
    names = tuple(node.strip() for node in nodes)
    if not names or any(not node for node in names):
        raise ValueError("Add at least one node. Node names cannot be empty.")
    if len(names) > MAX_NODES:
        raise ValueError(f"Use at most {MAX_NODES} nodes to keep the graph readable.")
    if any(len(node) > MAX_LABEL_LENGTH for node in names):
        raise ValueError(f"Keep node names to {MAX_LABEL_LENGTH} characters or fewer.")
    if len({node.casefold() for node in names}) != len(names):
        raise ValueError("Give each node a unique name (ignoring letter case).")
    positions = {node: index for index, node in enumerate(names)}
    normalized = set()
    for edge in edges:
        if len(edge) != 2:
            raise ValueError("Each connection must contain two nodes.")
        a, b = edge
        if a not in positions or b not in positions:
            raise ValueError("Every connection must reference existing nodes.")
        if a == b:
            raise ValueError("Connect two different nodes; self-loops are not supported.")
        normalized.add((a, b) if positions[a] < positions[b] else (b, a))
    return Graph(names, tuple(sorted(normalized, key=lambda edge: (positions[edge[0]], positions[edge[1]]))))


def traverse(graph: Graph, start: str, method: Method = "BFS") -> Traversal:
    """Compute a traversal and immutable snapshots for an interactive step viewer.

    BFS visits when dequeuing. DFS visits on entry and records each return to
    a parent. Only the component reachable from the starting node is explored.
    """
    graph = make_graph(graph.nodes, graph.edges)
    if start not in graph.nodes:
        raise ValueError("Choose a starting node that exists in the graph.")
    if method not in ("BFS", "DFS"):
        raise ValueError("Choose BFS or DFS.")
    neighbors = graph.neighbors()
    visited: list[str] = []
    tree_edges: list[Edge] = []
    steps: list[Step] = []

    def record(action: str, current: str | None, frontier: list[str], explanation: str) -> None:
        steps.append(Step(action, current, tuple(visited), tuple(frontier), tuple(tree_edges), explanation))

    if method == "BFS":
        queue = deque([start])
        discovered = {start}
        record("Ready", None, list(queue),
               f"Place {start} in the queue. BFS takes the oldest queued node first, exploring one distance layer at a time.")
        while queue:
            current = queue.popleft()
            visited.append(current)
            added = []
            for neighbor in neighbors[current]:
                if neighbor not in discovered:
                    discovered.add(neighbor)
                    queue.append(neighbor)
                    tree_edges.append((current, neighbor))
                    added.append(neighbor)
            detail = (f"Discover {', '.join(added)} and add them to the back of the queue."
                      if added else "There are no new neighbors to queue.")
            record("Visit", current, list(queue),
                   f"Take {current} from the front of the queue: visit {len(visited)}. {detail} "
                   "Already discovered neighbors are skipped, so cycles cannot queue a node twice.")
    else:
        seen: set[str] = set()
        path: list[str] = []
        record("Ready", None, [],
               f"Begin at {start}. DFS follows an unvisited neighbor as far as possible, then returns to explore other branches.")

        def visit(node: str, parent: str | None = None) -> None:
            seen.add(node)
            visited.append(node)
            path.append(node)
            if parent is not None:
                tree_edges.append((parent, node))
            arrival = f"Follow {parent} — {node}" if parent is not None else f"Start at {node}"
            record("Visit", node, path,
                   f"{arrival}: visit {len(visited)}. Keep {node} on the active path while exploring its unvisited neighbors in node-list order. "
                   "Already visited neighbors are skipped.")
            for neighbor in neighbors[node]:
                if neighbor not in seen:
                    visit(neighbor, node)
                    record("Backtrack", node, path,
                           f"Return from {neighbor} to {node}. That branch is fully explored. "
                           f"Check {node} for another unvisited neighbor; returning does not add a second visit.")
            path.pop()

        visit(start)

    unreachable = tuple(node for node in graph.nodes if node not in visited)
    ending = (f"Unreachable from {start}: {', '.join(unreachable)}. No path connects them to the starting node."
              if unreachable else "Every node is reachable from the starting node and has been visited exactly once.")
    record("Complete", None, [], f"Traversal complete. Visited {len(visited)} of {len(graph.nodes)} nodes. {ending}")
    return Traversal(method, start, tuple(steps), tuple(visited), unreachable)
