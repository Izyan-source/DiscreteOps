# DiscreteOps

A Python and Streamlit interface for discrete mathematics and optimization. Product navigation leads to Explore, Workbench, Visualizations, and About. The landing page is an interactive visual story; algorithms and computational tools are intentionally not implemented.

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
- `assets/styles.css`: shared palette, typography, responsive layout, and subtle motion.
- `assets/experience.html`: a self-contained canvas component for the scroll narrative and visual lab.
- `.streamlit/config.toml`: base Streamlit theme.

Explore progresses from points to connections to an illustrative constrained space. Scroll within the experience or use its three chapter buttons; Visualizations exposes the same scene with a scrubber. The highlighted choice and boundaries are authored drawing positions, not computed solutions. Workbench is a clearly labeled future workspace preview.

The interface uses local system fonts and no additional JavaScript libraries. Navigation uses native Streamlit buttons and session state. Only the interactive narrative uses a `streamlit.components.v1.html` iframe (supported by the installed Streamlit 1.49). Its viewport is sized by the shell CSS, with one internal scrolling story and no access to the parent DOM. Motion can be paused, respects reduced-motion preferences, and suspends when the document is hidden. The canvas caps pixel density at 2 and renders 36 points. The sidebar retains Streamlit's native sizing and collapse control, with automatic mobile behavior.

Styling targets Streamlit's test IDs and named containers. If upgrading Streamlit, visually check the sidebar and buttons. Streamlit's [configuration reference](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) documents the base theme options.
