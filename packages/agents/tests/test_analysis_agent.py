import pytest
from analysis_fakes import (
    FOREIGN_ID,
    REVENUE_ID,
    TARGETS_ID,
    FakeExecutor,
    FakeWorkspace,
    analysis_draft,
    enable_analysis,
    ok_table,
)
from eagleeye_agents.analysis.agent import run_analysis_agent
from eagleeye_agents.graph import run_graph
from eagleeye_agents.tools.registry import default_registry
from eagleeye_sandbox.types import SandboxResult
from fakes import FakeLLM, Turn, call, guard_json, make_ctx

INPUTS = [REVENUE_ID, TARGETS_ID]
QUESTION = "join revenue with targets by month and flag months below target"


async def test_happy_path_saves_artifact_and_masks_pii_for_the_model() -> None:
    llm = FakeLLM([analysis_draft()])
    ctx, sink, _ = make_ctx(llm)
    executor = enable_analysis(ctx)
    outcome = await run_analysis_agent(ctx, QUESTION, INPUTS, "parent")
    assert outcome.status == "ok" and outcome.mode == "sql"
    task = executor.tasks[0]
    assert [i.name for i in task.inputs] == ["ds_1", "ds_2"] and "LIMIT 100000" in task.code
    (ref,) = outcome.artifacts
    assert ref.artifact_id == "art-1" and ref.mode == "duckdb" and ref.row_count == 3
    assert ref.preview[0][-1] == "a@x.com"  # the user sees their own data
    email_col = [c["name"] for c in ref.columns].index("owner_email")
    assert all(row[email_col] == "***" for row in outcome.llm_previews[0])  # the model doesn't
    saved = ctx.workspace.saved[0]
    assert saved["source_refs"]["mode"] == "duckdb" and saved["run_id"] == "r1"
    assert ctx.workspace.logged[0]["status"] == "ok"
    system = llm.complete_calls[0][0].content
    assert "TABLE ds_2" in system and "a@x.com" not in system  # sample rows masked
    started = sink.of("step.started")
    assert [s["name"] for s in started] == [
        "load inputs",
        "write analysis code",
        "check code",
        "run in sandbox",
    ]
    assert {s["parent_id"] for s in started} == {"parent"}


async def test_check_rejection_feeds_back_and_regenerates() -> None:
    llm = FakeLLM([analysis_draft("SELECT * FROM read_csv('/etc/passwd')"), analysis_draft()])
    ctx, _, _ = make_ctx(llm)
    executor = enable_analysis(ctx)
    outcome = await run_analysis_agent(ctx, QUESTION, INPUTS, None)
    assert outcome.status == "ok" and len(executor.tasks) == 1  # bad code never ran
    assert "FUNCTION_NOT_ALLOWED" in llm.complete_calls[1][1].content


async def test_runtime_error_feeds_back_and_self_corrects() -> None:
    failed = SandboxResult("error", error="Binder Error: column revenu not found")
    llm = FakeLLM([analysis_draft(), analysis_draft()])
    ctx, _, _ = make_ctx(llm)
    executor = enable_analysis(ctx, FakeExecutor([failed, ok_table()]))
    outcome = await run_analysis_agent(ctx, QUESTION, INPUTS, None)
    assert outcome.status == "ok" and len(executor.tasks) == 2
    assert "revenu not found" in llm.complete_calls[1][1].content


async def test_timeout_gets_an_aggregate_hint() -> None:
    llm = FakeLLM([analysis_draft(), analysis_draft()])
    ctx, _, _ = make_ctx(llm)
    enable_analysis(
        ctx, FakeExecutor([SandboxResult("timeout", error="took too long"), ok_table()])
    )
    await run_analysis_agent(ctx, QUESTION, INPUTS, None)
    assert "aggregate earlier" in llm.complete_calls[1][1].content


async def test_execution_cap_reports_failure_honestly() -> None:
    failed = SandboxResult("error", error="boom")
    llm = FakeLLM([analysis_draft()] * 4)
    ctx, _, _ = make_ctx(llm)
    executor = enable_analysis(ctx, FakeExecutor([failed]))
    outcome = await run_analysis_agent(ctx, QUESTION, INPUTS, None)
    assert outcome.status == "failed" and len(executor.tasks) == 3 and "boom" in outcome.message


async def test_python_mode_runs_and_stats_are_returned() -> None:
    script = "from scipy import stats\nsave_stat('p_value', 0.031)"
    llm = FakeLLM([analysis_draft(script, mode="python")])
    ctx, _, _ = make_ctx(llm)
    enable_analysis(ctx, FakeExecutor([SandboxResult("ok", stats={"p_value": 0.031})]))
    outcome = await run_analysis_agent(ctx, "is the gap significant?", INPUTS, None)
    assert outcome.status == "ok" and outcome.stats == {"p_value": 0.031}
    assert outcome.artifacts == () and ctx.python_runs == 1


async def test_python_disabled_is_rejected_by_the_check() -> None:
    llm = FakeLLM([analysis_draft("save_stat('x', 1)", mode="python"), analysis_draft()])
    ctx, _, _ = make_ctx(llm)
    executor = enable_analysis(ctx)
    ctx.python_analysis = False
    outcome = await run_analysis_agent(ctx, QUESTION, INPUTS, None)
    assert outcome.status == "ok" and executor.tasks[0].mode == "sql"
    assert "PYTHON_DISABLED" in llm.complete_calls[1][1].content
    assert "Python mode is DISABLED" in llm.complete_calls[0][0].content


async def test_python_run_limit_per_answer() -> None:
    llm = FakeLLM([analysis_draft("save_stat('x', 1)", mode="python"), analysis_draft()])
    ctx, _, _ = make_ctx(llm)
    executor = enable_analysis(ctx)
    ctx.python_runs = 3
    await run_analysis_agent(ctx, QUESTION, INPUTS, None)
    assert [t.mode for t in executor.tasks] == ["sql"]


async def test_hourly_quota_stops_before_running() -> None:
    llm = FakeLLM([analysis_draft()])
    ctx, _, _ = make_ctx(llm)
    executor = enable_analysis(ctx, workspace=FakeWorkspace(runs_last_hour=60))
    outcome = await run_analysis_agent(ctx, QUESTION, INPUTS, None)
    assert outcome.status == "failed" and "hourly" in outcome.message and executor.tasks == []


async def test_other_users_inputs_are_never_loaded() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    executor = enable_analysis(ctx)
    outcome = await run_analysis_agent(ctx, QUESTION, [FOREIGN_ID, "not-a-uuid"], None)
    assert outcome.status == "no_access" and executor.tasks == []


async def test_foreign_input_is_dropped_from_a_mixed_list() -> None:
    llm = FakeLLM([analysis_draft("SELECT month, SUM(revenue) AS r FROM ds_1 GROUP BY month")])
    ctx, _, _ = make_ctx(llm)
    executor = enable_analysis(ctx)
    await run_analysis_agent(ctx, QUESTION, [FOREIGN_ID, REVENUE_ID], None)
    assert [i.name for i in executor.tasks[0].inputs] == ["ds_1"]


@pytest.mark.parametrize("field", ["unavailable", "clarification"])
async def test_unanswerable_or_unclear_returns_without_running(field: str) -> None:
    llm = FakeLLM([analysis_draft("", **{field: "No such column."})])
    ctx, _, _ = make_ctx(llm)
    executor = enable_analysis(ctx)
    outcome = await run_analysis_agent(ctx, QUESTION, INPUTS, None)
    assert outcome.status in ("no_access", "clarify") and executor.tasks == []


async def test_disabled_when_sandbox_missing() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    assert (await run_analysis_agent(ctx, QUESTION, INPUTS, None)).status == "no_access"


def test_registry_offers_tools_per_capability() -> None:
    assert "make_chart" not in default_registry().names()
    data_only = default_registry(include_data=True).names()
    assert {"list_datasets", "get_dataset_profile", "make_chart"} <= set(data_only)
    assert "analyze_data" not in data_only
    assert "analyze_data" in default_registry(include_data=True, include_analysis=True).names()
    assert "make_chart" in default_registry(include_sql=True).names()


async def test_supervisor_analyses_then_charts_with_grounded_figures() -> None:
    llm = FakeLLM(
        [guard_json(intent="analysis", complexity="complex"), analysis_draft()],
        [
            Turn("", (call("analyze_data", {"question": QUESTION, "inputs": INPUTS}),)),
            Turn(
                "",
                (
                    call(
                        "make_chart",
                        {
                            "source_id": REVENUE_ID,
                            "type": "line",
                            "x": "month",
                            "y": "revenue",
                            "title": "Revenue by month",
                        },
                    ),
                ),
            ),
            Turn("February was below target: revenue 80 against a target of 100."),
        ],
    )
    ctx, sink, _ = make_ctx(llm)
    enable_analysis(ctx)
    final = await run_graph(ctx, {"question": QUESTION, "history": [], "doc_ids": []})
    assert final["route"] == "supervisor" and final["status"] == "SUCCEEDED"
    assert len(sink.of("artifact")) == 1 and sink.of("artifact")[0]["mode"] == "duckdb"
    (chart,) = sink.of("chart")
    assert chart["spec"]["mark"]["type"] == "line" and "Highest: 130" in chart["summary"]
    assert "unverified_numbers" not in ctx.warnings  # 80 and 100 came from the result
    tool_specs = [t.name for t in llm.stream_calls[0]["tools"]]
    assert {"analyze_data", "make_chart", "list_datasets"} <= set(tool_specs)
