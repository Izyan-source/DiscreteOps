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
- `graph_explorer.py`: graph editing, examples, SVG visualization, and interactive traversal steps.
- `graph_algorithms.py`: Streamlit-independent graph validation and recorded BFS/DFS traversals.
- `problem_studio.py`: shared problem intake, type-specific forms, and model/solution inspection.
- `problem_models.py`: the problem-type registry, model builders, and adapters to existing solvers, independent of Streamlit.
- `workflow.py`: contextual method explanations and session handoffs that preserve existing inspection-page drafts.
- `assets/styles.css`: shared palette, typography, responsive layout, and subtle motion.
- `assets/experience.html`: a self-contained canvas component for the scroll narrative and visual lab.
- `.streamlit/config.toml`: base Streamlit theme.

Explore progresses from points to connections to an illustrative constrained space. Scroll within the experience or use its three chapter buttons; Visualizations exposes the same scene with a scrubber. The highlighted choice and boundaries in these visual studies are authored drawing positions, not computed solutions.

## Problem Studio

Start with an optional problem description, or go directly to structured input. New sessions have no problem type preselected. Choose **Task scheduling** or **Network routing**, review its scope and available solver, enter data through the numbered form (or load an example), then **Build model**. Inspect the Variables, Constraints, and Objective tabs, along with the input-symbol mapping and assumptions. Building a model does not solve it. **Solve this model** runs only supported formulations; structured-input edits clear stale models and results.

Descriptions are saved as context only. They are not parsed, classified, or converted into constraints; every supported rule must be entered in the form. Changing the description alone does not change the mathematical model. Choose **Other / not supported yet** when the current assumptions do not fit: the description remains available, while model building and solving are unavailable. Results explicitly apply to the structured model, not every requirement mentioned in prose.

Continue with **Inspect in Workbench** or **Visualize in Graph Explorer**. These actions carry the current inputs and, when available, the exact recorded solver run into the existing view without recomputing it. The Workbench displays schedule lanes and the search audit; Graph Explorer replays the BFS behind routing. The BFS traversal is a search over the reachable component, not the selected route itself; the route and destination stay in Studio. DFS remains available for exploration and does not replace the minimum-hop routing solver.

Return using the provided button or sidebar. Input edits in a linked view update the Studio problem and invalidate its previous model/result; rebuild before solving again. Playback-only changes keep the Studio result. An existing independent Workbench/Graph Explorer draft is temporarily set aside and restored when leaving the linked view. Opening those pages directly retains their original standalone editing behavior. Unsupported objectives cannot be handed to a solver with different semantics.

The **Methods behind this workflow** explanation uses the syllabus as a method vocabulary, not six product modules:

| Syllabus area | Current role |
| --- | --- |
| Logic and Proofs | Constraint statements and verification of supported results |
| Basic Counting | Decision-variable, constraint, and hop counts |
| Advanced Combinatorial Techniques | Existing backtracking and pruning for scheduling feasibility |
| Recurrence Relations and Generating Functions | Not yet applied in these workflows |
| Modular Arithmetic | Not yet applied in these workflows |
| Graph Theory | Scheduling conflict graphs and minimum-hop routing with BFS |

Only relevant methods are described as applied to each model. These mappings do not claim full syllabus coverage or introduce new algorithms. The separate Visualizations page remains an illustrative study, not a computed result view.

- Scheduling creates one slot-valued variable per task, domain constraints, and an inequality for each conflicting pair. The feasibility objective (`min 0`) reuses the existing backtracking scheduler and independent schedule audit. The optional **Minimize used slots** objective counts distinct assigned slots; it is explicitly **model only**, because the scheduler does not prove an optimum. Durations, deadlines, precedence, and capacity are outside the model.
- Routing creates two binary arc variables for each undirected connection and a flow-conservation constraint at every node, with +1 at the source and −1 at the destination. The objective minimizes selected arcs (unit-cost hops). The existing BFS discovery tree supplies a shortest route; selected connections and flow balances are verified. Disconnected endpoints are reported as infeasible. Source and destination must differ. Weighted, directed, capacity-constrained, and multiple-route problems are unsupported.

Existing input limits apply (24 tasks / 12 slots or 16 nodes). Unsupported objectives are never silently replaced with feasibility results. A scheduling search limit is reported as inconclusive, not infeasible. No AI services or new dependencies are used.

Focused Studio checks: `python -m unittest discover -s tests -p 'test_problem_studio.py' -v`.

### Extending supported problem types

`PROBLEM_TYPES` in `problem_models.py` is the central registry. Each entry defines its label/scope, input defaults, example, model builder, solver adapter, solver name, and optional existing inspection tool. `solve_model` dispatches by the exact registered model kind and returns `unsupported` for unknown kinds; it never falls through to scheduling or routing.

To add a supported formulation, supply its validated builder and solver adapter returning the common `Model`/`Solution` structures, register a `ProblemType` under that model's kind, and add its field renderer to `INPUT_RENDERERS` in `problem_studio.py`. Use distinct input field names for independent drafts. Renderers draw domain inputs; the shared Studio flow handles state, examples, validation messages, model inspection, support status, solving, explanations, and variable values. Optional schedule/route presentation is retained for the current types; other results use the common values and explanation fields. No new page or copied orchestration is needed. Only declare a Workbench/Graph Explorer handoff when the adapter supplies that existing tool's `Problem`/`Graph` and trace contract; otherwise leave it unset.

This change adds no problem types or algorithms beyond scheduling feasibility and unweighted routing. The registry provides an extension point, not a claim that arbitrary described problems can be solved.

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
