import pytest
from eagleeye_agents.checks.numbers import extract_figures, unverified_figures
from eagleeye_agents.graph import run_graph
from eagleeye_agents.router import choose_route
from eagleeye_agents.sql.agent import run_sql_agent
from eagleeye_agents.sql.preview import masked_preview
from fakes import FakeLLM, Turn, call, guard_json, make_ctx
from sql_fakes import FakeCatalog, FakeGateway, db_error, draft, enable_sql, ok_result


def _state(q: str = "How many orders per channel?") -> dict:
    return {"question": q, "history": [], "doc_ids": []}


SQL_GUARD = guard_json(intent="sql", complexity="simple")


async def test_sql_route_runs_subagent_and_answers_from_result() -> None:
    llm = FakeLLM([SQL_GUARD, draft()], [Turn("Web leads with 20 orders, store has 10.")])
    ctx, sink, _ = make_ctx(llm)
    gateway = enable_sql(ctx)
    final = await run_graph(ctx, _state())
    assert final["route"] == "sql" and final["status"] == "SUCCEEDED"
    assert len(gateway.calls) == 1 and len(ctx.artifacts) == 1
    assert sink.of("artifact")[0]["artifact_id"] == "art-1"
    started = sink.of("step.started")
    tool = next(s for s in started if s["name"] == "query_database")
    nested = [s["name"] for s in started if s["parent_id"] == tool["step_id"]]
    assert nested == ["find tables", "write SQL", "validate SQL", "run SQL"]
    assert "unverified_numbers" not in ctx.warnings
    answer_prompt = llm.stream_calls[0]["messages"][-1].content
    assert "<tool_data" in answer_prompt and "web | 20" in answer_prompt


async def test_validation_rejection_feeds_back_and_regenerates() -> None:
    llm = FakeLLM(
        [SQL_GUARD, draft("SELECT email FROM sales.customers"), draft()], [Turn("Web 20.")]
    )
    ctx, sink, _ = make_ctx(llm)
    gateway = enable_sql(ctx)
    await run_graph(ctx, _state())
    assert len(gateway.calls) == 1  # the PII query never reached the gateway
    retry_prompt = llm.complete_calls[2][1].content
    assert "COLUMN_RESTRICTED" in retry_prompt
    errors = [s for s in sink.of("step.finished") if s["status"] == "error"]
    assert errors and "COLUMN_RESTRICTED" in errors[0]["output_summary"]


async def test_database_error_feeds_back_and_self_corrects() -> None:
    # a query that passes local validation but fails in the database (e.g. a type error)
    llm = FakeLLM([SQL_GUARD, draft(), draft()], [Turn("Web 20.")])
    ctx, _, _ = make_ctx(llm)
    gateway = enable_sql(ctx, FakeGateway([db_error(), ok_result()]))
    await run_graph(ctx, _state())
    assert len(gateway.calls) == 2 and len(ctx.artifacts) == 1
    assert "does not exist" in llm.complete_calls[2][1].content


async def test_execution_cap_reports_failure_honestly() -> None:
    llm = FakeLLM([SQL_GUARD, draft(), draft(), draft(), draft()])
    ctx, _, _ = make_ctx(llm)
    gateway = enable_sql(ctx, FakeGateway([db_error()]))
    await run_graph(ctx, _state())
    assert len(gateway.calls) == 3 and ctx.artifacts == []
    assert "couldn't produce a working query" in ctx.text.value
    assert llm.stream_calls == []  # no answer turn → no invented figures


async def test_zero_rows_gets_one_retry_then_accepted() -> None:
    empty = ok_result(rows=[])
    llm = FakeLLM([SQL_GUARD, draft(), draft()], [Turn("No matching orders were found.")])
    ctx, _, _ = make_ctx(llm)
    gateway = enable_sql(ctx, FakeGateway([empty, empty]))
    await run_graph(ctx, _state())
    assert len(gateway.calls) == 2 and ctx.artifacts[0].row_count == 0
    assert "0 rows" in llm.complete_calls[2][1].content


async def test_clarification_short_circuits_without_execution() -> None:
    llm = FakeLLM([SQL_GUARD, draft(sql="", clarification="Which year do you mean?")])
    ctx, _, _ = make_ctx(llm)
    gateway = enable_sql(ctx)
    await run_graph(ctx, _state("What were sales?"))
    assert gateway.calls == [] and ctx.text.value.strip() == "Which year do you mean?"


@pytest.mark.parametrize(
    "reason",
    ["Salary data isn't available to you.", "I can only read data, not delete it."],
)
async def test_unavailable_is_reported_plainly_without_execution(reason: str) -> None:
    llm = FakeLLM([SQL_GUARD, draft(sql="", unavailable=reason)])
    ctx, _, _ = make_ctx(llm)
    gateway = enable_sql(ctx)
    await run_graph(ctx, _state("average salary by department"))
    assert gateway.calls == [] and ctx.text.value.strip() == reason
    assert llm.stream_calls == []


async def test_invalid_json_from_model_is_retried() -> None:
    llm = FakeLLM([SQL_GUARD, "not json", draft()], [Turn("Web 20.")])
    ctx, _, _ = make_ctx(llm)
    gateway = enable_sql(ctx)
    await run_graph(ctx, _state())
    assert len(gateway.calls) == 1 and "valid JSON" in llm.complete_calls[2][1].content


async def test_unverified_figures_are_flagged() -> None:
    llm = FakeLLM([SQL_GUARD, draft()], [Turn("Web had 20 orders and 4,512 returns.")])
    ctx, sink, _ = make_ctx(llm)
    enable_sql(ctx)
    await run_graph(ctx, _state())
    assert "unverified_numbers" in ctx.warnings
    figures = [s for s in sink.of("step.finished") if "not in results" in s["output_summary"]]
    assert figures and "4,512" in figures[0]["output_summary"]


async def test_no_access_when_sql_unavailable() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    outcome = await run_sql_agent(ctx, "orders?", None, None)
    assert outcome.status == "no_access"


async def test_unknown_source_name_is_no_access() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    enable_sql(ctx)
    outcome = await run_sql_agent(ctx, "orders?", "someone_elses_db", None)
    assert outcome.status == "no_access"


async def test_pii_is_masked_for_the_model_but_kept_for_the_ui() -> None:
    rows = [["a@example.com", 3]]
    llm = FakeLLM(
        [SQL_GUARD, draft("SELECT email, COUNT(*) AS n FROM sales.customers GROUP BY email")],
        [Turn("One customer.")],
    )
    ctx, _, _ = make_ctx(llm)
    enable_sql(ctx, FakeGateway([ok_result(rows, ("email", "n"))]), FakeCatalog(can_see_pii=True))
    await run_graph(ctx, _state())
    assert ctx.artifacts[0].preview[0][0] == "a@example.com"
    assert "a@example.com" not in llm.stream_calls[0]["messages"][-1].content


async def test_supervisor_can_call_query_database_tool() -> None:
    llm = FakeLLM(
        [guard_json(intent="mixed", complexity="complex"), draft()],
        [
            Turn("", (call("query_database", {"question": "orders per channel"}),)),
            Turn("Web leads with 20 orders."),
        ],
    )
    ctx, sink, _ = make_ctx(llm)
    enable_sql(ctx)
    final = await run_graph(ctx, _state("compare channels with our policy"))
    assert final["route"] == "supervisor" and len(ctx.artifacts) == 1
    tool_names = [s["name"] for s in sink.of("step.started") if s["kind"] == "tool"]
    assert "query_database" in tool_names and "run SQL" in tool_names
    specs = [t.name for t in llm.stream_calls[0]["tools"]]
    assert "query_database" in specs and "list_data_sources" in specs


async def test_sql_tools_hidden_when_unavailable() -> None:
    llm = FakeLLM([guard_json(intent="mixed", complexity="complex")], [Turn("No data access.")])
    ctx, _, _ = make_ctx(llm)
    await run_graph(ctx, _state())
    assert "query_database" not in [t.name for t in llm.stream_calls[0]["tools"]]


def test_router_sql_route_requires_availability() -> None:
    from eagleeye_agents.guard.verdict import GuardVerdict

    v = GuardVerdict("allowed", "sql", "simple", "llm")
    assert choose_route(v, False, sql_available=True) == "sql"
    assert choose_route(v, False, sql_available=False) == "supervisor"


# --- numeric check + preview units ----------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "evidence", "unverified"),
    [
        ("Revenue was €1,234.50 [1].", [1234.5], []),
        ("Revenue was 1.2M.", [1_234_567.0], []),
        ("On-time rate is 87.3%.", [0.8731], []),
        ("Top 5 categories in 2025.", [], []),
        ("Revenue was 9,999.", [1234.5], ["9,999"]),
        ("Shipped on 2026-01-02 with 3 parcels.", [], []),
        ("As of November 13, 2026, 40 orders qualify.", [40.0], []),
        ("Delivered 13th of Nov and 28 Sept 2026.", [], []),
        ("Since Oct. 30th: 40 orders.", [40.0], []),
        ("May 2026 revenue was 9,999.", [1234.5], ["9,999"]),  # month word alone ≠ date
        ("Feb missed by −€90,380.83.", [-90380.83], []),  # typographic minus, signed evidence
        ("Below target by €90,380.83.", [-90380.83], []),
        ("p = 0.444; 95% confidence interval −70.51 to 30.89.", [0.444, -70.51, 30.89], []),
        ("Not significant at the 0.05 level (p < 0.05 fails).", [], []),
        ("p = 0.031, significant at α = 0.05.", [0.444], ["0.031"]),  # the p-value IS checked
    ],
)
def test_unverified_figures(answer: str, evidence: list[float], unverified: list[str]) -> None:
    assert unverified_figures(answer, evidence, "") == unverified


def test_question_numbers_are_not_flagged() -> None:
    assert unverified_figures("Orders above 250 euros: 40.", [40.0], "orders above 250 euros") == []


def test_extract_handles_units() -> None:
    figs = extract_figures("12.5% and 3 million and 1,000")
    assert [(f.value, f.percent, f.scale) for f in figs] == [
        (12.5, True, 1.0),
        (3.0, False, 1e6),
        (1000.0, False, 1.0),
    ]


def test_format_result_explains_masked_values() -> None:
    from eagleeye_agents.sql.preview import format_result

    text = format_result("SELECT 1", "", [{"name": "email"}], [("***",)], 1, False)
    assert "visible to the user in the result table" in text
    assert "visible to the user" not in format_result(
        "SELECT 1", "", [{"name": "n"}], [(1,)], 1, False
    )


@pytest.mark.parametrize(
    ("value", "masked"),
    [
        ("2026-09-01", False),  # regression: ISO dates were masked as phone numbers
        ("2026-09-01T00:00:00+00:00", False),
        ("12-34", False),
        ("+1-555-1001", False),  # too few digits to be confident
        ("+1 555 123 4567", True),
        ("(020) 7946 0958", True),
        ("x@y.com", True),
        ("Laptops", False),
    ],
)
def test_preview_masking_shapes(value: str, masked: bool) -> None:
    out = masked_preview([{"name": "v"}], [[value]], set())
    assert (out[0][0] == "***") is masked


def test_masked_preview_regex_catches_aliased_pii() -> None:
    cols = [{"name": "contact"}, {"name": "phone_number"}, {"name": "n"}]
    rows = [["x@y.com", "+1 555 123 4567", 3]]
    assert masked_preview(cols, rows, set()) == (("***", "***", 3),)


async def test_schema_gaps_are_unanswerable_not_access_denied() -> None:
    """A question the granted schema can't answer (e.g. a column that only exists in the user's
    file) is reported so the planner may retry with concrete values; "Not available" stays
    reserved for users without access."""
    from eagleeye_agents.sql.agent import run_sql_agent
    from eagleeye_agents.tools.query_database import outcome_text

    reason = "No week_start column exists in the accessible schema."
    llm = FakeLLM([draft(sql="", unavailable=reason)])
    ctx, _, _ = make_ctx(llm)
    gateway = enable_sql(ctx)
    outcome = await run_sql_agent(ctx, "ships whose week_start is 2024-01-01", None, None)
    assert outcome.status == "unanswerable" and gateway.calls == []
    text = outcome_text(outcome)
    assert text.startswith("Not answerable from the database as asked: " + reason)
    assert "listing those values explicitly" in text and "Not available" not in text


def test_planner_is_told_to_query_files_before_the_database() -> None:
    from eagleeye_agents.prompts.loader import load_prompts

    supervisor = load_prompts().text("supervisor")
    assert "call analyze_data FIRST and" in supervisor
    assert "ask again once with those values" in supervisor


@pytest.mark.parametrize(
    "answer",
    [
        "The difference is significant (*p* < 0.001).",
        "NPS = (promoters - detractors) / responses × 100; Key scored 24.85.",
        "There were 3 complaints per 100 bookings.",
        "Welch's *t* = 50.42, *p* < **0.001**; NPS on the −100 to +100 scale.",
        "Key scored an NPS of 24.85.",  # the analysis returned the share 0.2485
    ],
)
def test_conventions_and_formula_constants_are_not_flagged(answer: str) -> None:
    assert unverified_figures(answer, [0.2485, 3.0, 50.42], "") == []


def test_invented_figures_are_still_flagged() -> None:
    assert unverified_figures("Key scored an NPS of 31.70.", [0.2485, 24.85], "") == ["31.70"]


async def test_query_constants_count_as_evidence() -> None:
    from eagleeye_agents.sql.types import ArtifactRef, SqlOutcome
    from eagleeye_agents.tools.query_database import register_artifact

    ctx, _, _ = make_ctx(FakeLLM())
    artifact = ArtifactRef(
        "a1",
        "Reliability",
        "SELECT 1 WHERE x <= y + INTERVAL '24 hours'",
        "src",
        (),
        1,
        False,
        (),
        assumptions="On time = within 24 hours of schedule.",
    )
    await register_artifact(ctx, SqlOutcome("ok", artifact=artifact, llm_preview=((0.3057,),)))
    assert (
        unverified_figures(
            "On time means within 24 hours; reliability 30.57%.", ctx.numeric_evidence, ""
        )
        == []
    )
