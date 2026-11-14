# Notebook mode: analyst-style exploratory data analysis

> Plan only. Nothing here is built until it is approved. Scheduled inside Phase 7A, together with
> the Lambda analysis sandbox (step 2 of `docs/phase7-cloud-plan.md`), so the sandbox changes once.

## Why

A request like "[titanic.csv] perform detailed EDA" today becomes 2–4 focused DuckDB queries, one
chart and a written summary. It is correct and every figure is verified, but it is not what a data
analyst would produce. The reasons are deliberate design choices made for short, verified answers:

- the code writer prefers DuckDB SQL; Python is only for tests, regression and clustering;
- the sandbox has pandas, numpy, scipy and sklearn but **no plotting library**, and Python can only
  return up to 3 small tables and some single numbers;
- every chart goes through `make_chart`, one table → one chart, "one chart per message is usually
  enough", at most 4; at most 3 Python runs per answer;
- the figures check needs every stated number to come from a saved table or number, so code saves
  tables instead of printing or plotting.

## What we will build

**Notebook mode**: for exploratory requests from company users, EagleEye writes and runs a short
pandas notebook (about 4–8 cells: overview, missing values, distributions, outliers, relationships
with the outcome, correlations), shows it in the answer cell by cell with tables and plots, writes a
summary of the findings, and offers **Download .ipynb** so an analyst can continue in Jupyter.

**Demo visitors keep the light version** (today's behaviour). The notebook tool is never offered to
the demo account, enforced in code, not by the prompt.

## Design

### 1. When notebook mode is used
- A new planner tool, `explore_data(input_ids, goal)`, offered only to company users when Python
  analysis is enabled. The planner prompt says when to use it: broad, open-ended requests ("detailed
  EDA", "explore this file in depth", "full analysis") on one or two inputs. Specific questions keep
  using `analyze_data`.
- The tool registry already offers tools per capability; it gains one more check: not for
  `is_demo` users (and a setting, `ENABLE_NOTEBOOK_MODE`, default on for local and company, off
  for the demo).

### 2. Running a notebook in the sandbox
- The runner (`infra/sandbox/runner.py`) learns a **cells** mode: it runs a list of Python cells in
  order in **one shared namespace** (like a notebook kernel) in a single sandbox execution, and
  records each cell's outputs separately: stdout (capped), tables (`save_table`), single numbers
  (`save_stat`), figures, and an error if the cell failed. A failing cell stops the cells after it.
- **Figures**: matplotlib (and seaborn) are added to the sandbox image with the non-interactive
  `Agg` backend and `MPLCONFIGDIR=/tmp`. At the end of each cell, every open figure is saved as a
  PNG (100 dpi) and closed. Caps: at most 12 figures per notebook, 400 KB each, 20 tables, 60 stats.
  Only PNG, never SVG (an SVG could carry script into the browser).
- The result format (`result.json`) gains `cells: [{stdout, tables, stats, figures, error}]`; the
  existing single-code mode is unchanged, so `analyze_data` keeps working as it is.
- Both executors use this one protocol: `DockerExecutor` locally, `LambdaExecutor` in the cloud
  (Phase 7A step 2). Figures and tables travel through S3 single-use links in the cloud, as already
  planned for large data, because a Lambda response is limited to 6 MB.

### 3. The notebook agent (`packages/agents/eagleeye_agents/notebook/`)
1. **Plan**: one model call returns the notebook outline (title, and for each cell a one-line
   purpose), based on the file's profile and the user's goal.
2. **Write**: one model call writes all cells as JSON (`[{purpose, code}]`), compact and in the
   style of an analyst's notebook; key figures the summary will need are saved with
   `save_table` / `save_stat`.
3. **Check**: every cell goes through the existing Python checks (no files, no network, no imports
   outside the allowed list, which gains matplotlib and seaborn).
4. **Run**: all cells in one sandbox execution.
5. **Repair**: if a cell fails, the model gets that cell's code and error and rewrites that cell
   only; the notebook runs again (inputs are small, so a re-run is cheap). At most 2 repairs.
6. **Summarise**: the planner writes the findings. As today, every number in the text must come
   from a saved table or number (the figures check is unchanged); plots are for looking at, not
   evidence.

### 4. Storing and showing the notebook
- A new result type, `notebook`: a manifest (title, cells with purpose, code and outputs) saved in
  the artifacts bucket, figures saved as PNG objects next to it, tables saved as normal result
  tables (so they open in the existing table viewer and download as CSV).
- API:
  - `GET /v1/artifacts/{id}` returns the notebook manifest (owner only, like every artifact);
  - `GET /v1/artifacts/{id}/figures/{n}` serves one PNG (owner only, `image/png`,
    `X-Content-Type-Options: nosniff`, cached privately);
  - `GET /v1/artifacts/{id}/notebook.ipynb` builds a Jupyter notebook (nbformat 4, validated) with
    markdown cells for each purpose, the code, and the outputs embedded (tables as HTML, figures as
    PNG). No raw data is embedded; the notebook expects the user's own copy of the file to re-run.
- Web: a **NotebookCard** under the answer: title, a cell list (purpose, collapsible code, tables,
  figures in a responsive grid with click-to-enlarge), "Download .ipynb", and the existing
  table viewer for tables. Light and dark theme; keyboard accessible.

### 5. Limits (company users)
- One notebook per answer, at most 8 cells, at most 3 sandbox executions (1 run + 2 repairs).
- Sandbox per execution: 120 s, 2 GB memory (today: 60 s, 1 GB for single analyses).
- Run deadline for answers that use notebook mode: 300 s (today's analysis deadline is 240 s).
- The per-answer cost cap ($0.25) and the user's usage limit still apply.
- Expected cost with the current model: about $0.02–0.05 and 1–2 minutes per notebook.

## Security

- Same sandbox controls as today: no network, read-only filesystem except a small temp folder,
  non-root, memory and time caps, static checks before running. Lambda adds a micro-VM per run.
- Output caps (figure count and size, table count and rows, stdout length) are enforced in the
  runner **and** checked again by the API before storing; PNGs are verified by their signature.
- Figures and notebooks are served only to their owner, with safe content types; the .ipynb export
  contains no executable output (no HTML/JS outputs, only escaped text, tables and PNG).
- The security-reviewer agent reviews the runner, the figure endpoint and the export.

## Tests

- Runner: cells share variables; per-cell outputs; figures captured, closed and capped; oversize or
  too many figures refused; a failing cell stops later cells; single-code mode unchanged.
- Checks: matplotlib and seaborn allowed; `plt.savefig("/path")`, `open()`, network and file
  access still rejected.
- Agent: plan → write → run → summary; repair of one failing cell; repair cap; cut-off replies
  handled like `analyze_data`; demo users never get the tool.
- API: owner-only access to manifest, figures and .ipynb (another user gets 404); .ipynb validates
  with nbformat; PNG signature check.
- Web: NotebookCard renders cells, figures and tables; download link; accessibility.
- Eval: three EDA requests (Titanic, the customer survey, the fuel and emissions file) must
  complete with at least 4 figures, a clean figures check, under $0.05 and 2 minutes each.

## Order of work inside 7A

1. Sandbox image (matplotlib, seaborn) and the runner's cells mode, with tests (Docker executor).
2. Notebook agent and the `explore_data` tool; prompts; agent tests.
3. Result storage, API endpoints and the .ipynb export; API tests.
4. NotebookCard in the web app; web tests; live check with the Titanic EDA as a company user, and
   confirm the demo account still gets the light version.
5. The Lambda executor implements the same protocol (already part of 7A step 2), and the sandbox
   test suite, including notebook runs, passes against both executors.

## Decisions

- Decided: notebook mode for company users; demo visitors keep the light version.
- Decided: built inside Phase 7A with the Lambda sandbox.
- Open (default in brackets): include seaborn [yes]; maximum figures per notebook [12].
