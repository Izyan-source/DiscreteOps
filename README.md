# DiscreteOps

A Python and Streamlit interface for discrete mathematics and optimization. Product navigation leads to Explore, Workbench, Graph Explorer, Problem Studio, Visualizations, and About. The landing page is an interactive visual story; the Constraint Workbench builds real schedules with backtracking.

## Run locally

Requires Python 3.10 or newer. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open http://localhost:8501. On Windows, activate the environment with `.venv\Scripts\activate`.

## Structure

- `app.py`: application configuration and page routing.
- `ui.py`: product navigation and reusable presentation functions.
- `workbench.py`: editable scheduling inputs, examples, results, and constraint explanations.
- `solver.py`: Streamlit-independent input validation, backtracking, and schedule verification.
- `graph_explorer.py`: graph editing, examples, SVG visualization, and interactive traversal steps.
- `graph_algorithms.py`: Streamlit-independent graph validation and recorded BFS/DFS traversals.
- `problem_studio.py`: guided scheduling/routing forms and model/solution inspection.
- `problem_models.py`: Streamlit-independent model generation and adapters to existing solvers.
- `assets/styles.css`: shared palette, typography, responsive layout, and subtle motion.
- `assets/experience.html`: a self-contained canvas component for the scroll narrative and visual lab.
- `.streamlit/config.toml`: base Streamlit theme.

Explore progresses from points to connections to an illustrative constrained space. Scroll within the experience or use its three chapter buttons; Visualizations exposes the same scene with a scrubber. The highlighted choice and boundaries in these visual studies are authored drawing positions, not computed solutions.

## Problem Studio

Choose **Task scheduling** or **Network routing**, enter inputs through the numbered form (or load an example), then **Build model**. Inspect the Variables, Constraints, and Objective tabs, along with the input-symbol mapping and assumptions. Building a model does not solve it. **Solve this model** runs only supported formulations; edits clear stale models and results. Studio inputs persist across navigation independently of the Workbench and Graph Explorer.

- Scheduling creates one slot-valued variable per task, domain constraints, and an inequality for each conflicting pair. The feasibility objective (`min 0`) reuses the existing backtracking scheduler and independent schedule audit. The optional **Minimize used slots** objective counts distinct assigned slots; it is explicitly **model only**, because the scheduler does not prove an optimum. Durations, deadlines, precedence, and capacity are outside the model.
- Routing creates two binary arc variables for each undirected connection and a flow-conservation constraint at every node, with +1 at the source and −1 at the destination. The objective minimizes selected arcs (unit-cost hops). The existing BFS discovery tree supplies a shortest route; selected connections and flow balances are verified. Disconnected endpoints are reported as infeasible. Source and destination must differ. Weighted, directed, capacity-constrained, and multiple-route problems are unsupported.

Existing input limits apply (24 tasks / 12 slots or 16 nodes). Unsupported objectives are never silently replaced with feasibility results. A scheduling search limit is reported as inconclusive, not infeasible. No AI services or new dependencies are used.

Focused Studio checks: `python -m unittest discover -s tests -p 'test_problem_studio.py' -v`.

## Graph Explorer

Open **Graph Explorer** in the sidebar. A sample graph is preloaded; use **Edit nodes & connections** to create your own, or load the branching, disconnected, or blank example. Graphs are undirected and unweighted, with up to 16 uniquely named nodes (24 characters each). Select pairs to add connections; isolated nodes and cycles are supported.

Choose a starting node and BFS or DFS, then click **Run traversal**. Use Previous, Next, the step slider, or Show result to inspect actual algorithm snapshots. The graph highlights the current node, visited nodes, discovery edges, and the queue or active DFS path. Numbers mark first-visit order. Explanations describe every visit and DFS return; unreachable nodes are identified at completion. Both algorithms explore only the starting node's connected component and break neighbor ties using node-list order.

Editing the graph, start, or method clears the old traversal. Graphs and playback position persist across page navigation. The viewer uses native Streamlit controls and SVG images, with no new dependencies.

## Constraint Workbench

Enter one task and one time-slot label per line, then select pairs of tasks that cannot run together. Each task occupies exactly one slot; tasks without a declared conflict may share a slot. Slots are distinct labels: durations, overlapping clock times, ordering, and resource capacity are not inferred. Use distinct, non-overlapping slots. Up to 24 tasks and 12 slots are supported.

Click **Generate schedule** to run the real backtracking solver. It tries highly connected tasks first, rejects conflicting placements, and undoes assignments when a branch fails. The result is independently checked, grouped by time slot, and accompanied by a pair-by-pair audit and actual rejected search attempts. It finds a valid schedule; it does not minimize slots or balance workloads. Examples include a team workshop and a deliberately impossible two-slot case, both solved from their inputs at runtime.

An exhausted search proves that no schedule exists for the supplied constraints. A 50,000-attempt or two-second limit is reported separately as inconclusive. No partial schedule is presented as a solution. Editing inputs invalidates the previous result, and inputs/results persist when navigating between product pages in the same session.

Run the solver tests (including comparison against exhaustive enumeration for every four-task conflict graph):

```bash
python -m unittest discover -s tests -v
```

The interface uses local system fonts and no additional JavaScript libraries. Navigation uses native Streamlit buttons and session state. Only the interactive narrative uses a `streamlit.components.v1.html` iframe (supported by the installed Streamlit 1.49). Its viewport is sized by the shell CSS, with one internal scrolling story and no access to the parent DOM. Motion can be paused, respects reduced-motion preferences, and suspends when the document is hidden. The canvas caps pixel density at 2 and renders 36 points. The sidebar retains Streamlit's native sizing and collapse control, with automatic mobile behavior.

Styling targets Streamlit's test IDs and named containers. If upgrading Streamlit, visually check the sidebar and buttons. Streamlit's [configuration reference](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) documents the base theme options.
