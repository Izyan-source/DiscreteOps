# DiscreteOps

A Python and Streamlit system that connects real-world problems to mathematical models, supported solvers, visual inspection, and explainable results. **Problem Studio** is the default entry point. The existing Workbench and Graph Explorer provide detailed inspection within those workflows; Explore retains the landing experience.

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
- `allocation_solver.py`: shared exact search for capacity-constrained feasibility or minimum-cost assignment, diagnostics, and independent verification.
- `graph_explorer.py`: graph editing, examples, SVG visualization, and interactive traversal steps.
- `graph_algorithms.py`: Streamlit-independent graph/cost validation and recorded BFS, DFS, and Dijkstra searches.
- `problem_studio.py`: shared problem intake, type-specific forms, and model/solution inspection.
- `problem_models.py`: the problem-type registry, model builders, and adapters to existing solvers, independent of Streamlit.
- `workflow.py`: contextual method explanations and session handoffs that preserve existing inspection-page drafts.
- `assets/styles.css`: shared palette, typography, responsive layout, and subtle motion.
- `assets/experience.html`: a self-contained canvas component for the scroll narrative and visual lab.
- `.streamlit/config.toml`: base Streamlit theme.

Explore progresses from points to connections to an illustrative constrained space. Scroll within the experience or use its three chapter buttons; Visualizations exposes the same scene with a scrubber. The highlighted choice and boundaries in these visual studies are authored drawing positions, not computed solutions.

## Problem Studio

Start with an optional problem description, or go directly to structured input. New sessions have no problem type preselected. Choose **Task scheduling**, **Network routing**, or **Resource allocation**, review its scope and available solver, enter data through the numbered form (or load an example), then **Build model**. Inspect the Variables, Constraints, and Objective tabs, along with the input-symbol mapping and assumptions. Building a model does not solve it. **Solve this model** runs only supported formulations; structured-input edits clear stale models and results.

Descriptions are saved as context only. They are not parsed, classified, or converted into constraints; every supported rule must be entered in the form. Changing the description alone does not change the mathematical model. Choose **Other / not supported yet** when the current assumptions do not fit: the description remains available, while model building and solving are unavailable. Results explicitly apply to the structured model, not every requirement mentioned in prose.

Continue with **Inspect in Workbench** or **Visualize in Graph Explorer**. These actions carry the current inputs and, when available, the exact recorded solver run into the existing view without recomputing it. The Workbench displays schedule lanes and the search audit; Graph Explorer replays Dijkstra's search behind weighted routing, including tentative/final costs. The search covers the reachable component; Studio highlights the selected route and displays its total cost and leg-by-leg breakdown. BFS/DFS remain available for connectivity exploration and ignore weights; they do not replace the weighted routing solver.

Return using the provided button or sidebar. Input edits in a linked view update the Studio problem and invalidate its previous model/result; rebuild before solving again. Playback-only changes keep the Studio result. An existing independent Workbench/Graph Explorer draft is temporarily set aside and restored when leaving the linked view. Opening those pages directly retains their original standalone editing behavior. Unsupported objectives cannot be handed to a solver with different semantics.

The **Methods behind this workflow** explanation uses the syllabus as a method vocabulary, not six product modules:

| Syllabus area | Current role |
| --- | --- |
| Logic and Proofs | Constraint statements and verification of supported results |
| Basic Counting | Product rule for candidate scheduling and allocation assignments before constraints |
| Advanced Combinatorial Techniques | No unit coverage claimed; use of backtracking alone is not sufficient |
| Recurrence Relations and Generating Functions | Not yet applied in these workflows |
| Modular Arithmetic | Not yet applied in these workflows |
| Graph Theory | Scheduling conflict graphs and minimum-cost routing with Dijkstra |

The shared **Solution explanation** panel presents the model, constraints, algorithm, validity argument, and limitations for Studio results and the existing solver tools. It distinguishes proven optimality, feasible incumbents, infeasibility, and incomplete searches; traversal explanations follow the displayed playback step.

Only relevant methods are described as applied to each model. These mappings do not claim full syllabus coverage. The separate Visualizations page remains an illustrative study, not a computed result view.

- Scheduling creates one slot-valued variable per task, domain constraints, and an inequality for each conflicting pair. The feasibility objective (`min 0`) reuses the existing backtracking scheduler and independent schedule audit. The optional **Minimize used slots** objective counts distinct assigned slots; it is explicitly **model only**, because the scheduler does not prove an optimum. Durations, deadlines, precedence, and capacity are outside the model.
- Routing accepts locations, two-way connections, a non-negative cost per connection, and distinct start/destination locations. Costs can represent distance, time, or expense but must use one consistent unit; no real-world costs are inferred. New connections default to 1. Costs must be finite and between 0 and 1 trillion. The example contrasts a direct connection costing 12 with a two-leg route costing 5.
- The routing model creates two binary arc variables per connection and flow conservation at every location (+1 at the start, −1 at the destination). Its objective is the sum of each selected arc's cost. Dijkstra runs once in `graph_algorithms.py`; the adapter reconstructs the recorded path and verifies connections, flow balances, and total cost. Zero-cost edges are supported; equal-cost alternatives may exist, and node-list order breaks ties. The solver returns a simple route even if the flow model allows zero-cost cycles. Disconnected destinations produce a clear infeasible result with no route or cost. Negative costs, directed links, capacities, and multiple simultaneous routes remain unsupported. The original unweighted Python model API still uses BFS.

Existing input limits apply (24 tasks / 12 slots for scheduling; 16 nodes for routing). Unsupported objectives are never silently replaced with feasibility results. A search limit is reported as inconclusive, not infeasible. No AI services or new dependencies are used.

### Resource allocation

Enter resource names and task names, each on a separate line. Give each resource a capacity and each task a positive requirement, then select the resources eligible for that task. Each whole task must be assigned to **exactly one** eligible resource, and the sum of requirements assigned to a resource must fit its capacity. Use one common unit across all inputs, such as work hours across teams in the same planning period. This is not a model of tasks simultaneously consuming different resource types (such as CPU plus RAM), scheduling, splitting tasks, or selecting a profitable subset.

Capacities are whole numbers from 0 to 1 billion; requirements are whole numbers from 1 to 1 billion. The limits are 8 resources and 16 tasks, with unique names of up to 40 characters. New resources default to zero capacity; new tasks default to one unit and all current resources eligible. Review these defaults. Removing a resource removes it from eligibility selections; adding a resource does not automatically make it eligible for existing tasks. Empty eligibility is a valid but infeasible model.

The shared model inspector shows binary assignment variables, an exactly-once constraint for every task, and a capacity inequality for every resource. **Solve this model** runs the shared exact solver in `allocation_solver.py`, trying constrained/larger tasks first and undoing failed placements. Feasibility mode stops at the first valid allocation. Search is bounded by 50,000 attempted placements or two seconds.

The optional **Minimize total allocation cost** objective requires a cost for every eligible task–resource pair. Each cost is for the whole assignment, not a rate multiplied by its requirement. Use a common cost unit, non-negative amounts up to 1 billion, and at most two decimal places. Blank costs are missing, not zero: model building is blocked until they are supplied, or you explicitly switch back to feasibility. The example includes costs but keeps feasibility as the default objective.

Optimization uses the same search with branch and bound: it keeps the cheapest complete allocation, bounds each branch by the cheapest independently affordable assignment for every remaining task, and discards a repeated capacity state only if a cheaper or equal prefix already reached it. Costs are stored and summed as integer hundredths to avoid floating-point pruning errors. **Optimal allocation / minimum cost proven** appears only after every potentially improving branch has been explored or safely pruned. Results show the chosen assignments, their individual costs, and the minimum total. A limit after a complete solution returns **Feasible allocation / optimality not proven**, with the best total cost found; it never labels that cost a minimum. A limit before any complete solution reports unknown feasibility.

Successful results show each task's resource, each resource's used and remaining capacity, and the outcome of the independent constraint audit. Provably impossible inputs show capacity shortages, tasks that fit no eligible resource, or a joint constraint conflict established by exhaustive search. These messages do not claim a minimal conflicting constraint set. No partial allocation or fabricated cost/capacity result is shown. Editing capacities, requirements, eligibility, costs, or the objective invalidates the old model and result. Allocation is inspected in Studio through shared result tables; it is not sent to scheduling or routing tools with different constraints.

Focused allocation checks: `python -m unittest discover -s tests -p 'test_allocation.py' -v`.

Focused Studio checks: `python -m unittest discover -s tests -p 'test_problem_studio.py' -v`.

### Extending supported problem types

`PROBLEM_TYPES` in `problem_models.py` is the central registry. Each entry defines its label/scope, input defaults, example, model builder, solver adapter, solver name, and optional existing inspection tool. `solve_model` dispatches by the exact registered model kind and returns `unsupported` for unknown kinds; it never falls through to scheduling or routing.

To add a supported formulation, supply its validated builder and solver adapter returning the common `Model`/`Solution` structures, register a `ProblemType` under that model's kind, and add its field renderer to `INPUT_RENDERERS` in `problem_studio.py`. Use distinct input field names for independent drafts. Renderers draw domain inputs; the shared Studio flow handles state, examples, validation messages, model inspection, support status, solving, explanations, and variable values. Optional schedule/route presentation is retained for those types; other results can provide reusable `ResultTable` data, diagnostics, variable values, and explanations. No new page or copied orchestration is needed. Only declare a Workbench/Graph Explorer handoff when the adapter supplies that existing tool's `Problem`/`Graph` and trace contract; otherwise leave it unset.

The supported types are scheduling feasibility, network routing, and capacity-constrained resource allocation. The registry provides an extension point, not a claim that arbitrary described problems can be solved.

## Graph Explorer

Open **Graph Explorer** in the sidebar. A sample graph is preloaded; use **Edit nodes & connections** to create your own, or load the branching, disconnected, or blank example. Graphs are undirected and unweighted, with up to 16 uniquely named nodes (24 characters each). Select pairs to add connections; isolated nodes and cycles are supported.

When opened from a weighted Studio model, Graph Explorer retains the connection costs and offers Dijkstra alongside BFS/DFS. Edit costs in the same graph editor; changed costs return to Studio and invalidate its old model/result. Edges are labelled with their costs, and Dijkstra playback shows the current predecessor tree, settled locations, and tentative distances. Loading a topology example in this linked view assigns its connections cost 1. Returning restores the independent Graph Explorer draft.

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
