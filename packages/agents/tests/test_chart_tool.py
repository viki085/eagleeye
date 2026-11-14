from analysis_fakes import FOREIGN_ID, REVENUE_ID, TARGETS_ID, FakeWorkspace
from eagleeye_agents.tools.list_datasets import GetDatasetProfileTool, ProfileArgs
from eagleeye_agents.tools.make_chart import MAX_CHARTS, ChartArgs, MakeChartTool
from fakes import FakeLLM, make_ctx


def args(**kw: object) -> ChartArgs:
    base = {"source_id": REVENUE_ID, "type": "bar", "x": "month", "y": "revenue", "title": "Rev"}
    return ChartArgs(**{**base, **kw})


async def test_chart_is_built_from_data_and_emitted() -> None:
    ctx, sink, _ = make_ctx(FakeLLM())
    ctx.workspace = FakeWorkspace()
    result = await MakeChartTool().run(args(), ctx, "s1")
    assert result.ok and "Total: 310" in result.content
    (event,) = sink.of("chart")
    assert event["source_id"] == REVENUE_ID and event["spec"]["data"]["values"]
    assert ctx.charts == [event] and 310.0 in ctx.numeric_evidence


async def test_foreign_source_is_refused() -> None:
    ctx, sink, _ = make_ctx(FakeLLM())
    ctx.workspace = FakeWorkspace()
    result = await MakeChartTool().run(args(source_id=FOREIGN_ID), ctx, "s1")
    assert not result.ok and sink.of("chart") == []


async def test_bad_intent_explains_then_gives_up_after_two() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    ctx.workspace = FakeWorkspace()
    tool = MakeChartTool()
    first = await tool.run(args(y="nope"), ctx, "s1")
    assert not first.ok and "Unknown column 'nope'" in first.content
    await tool.run(args(y="nope"), ctx, "s1")
    third = await tool.run(args(), ctx, "s1")
    assert not third.ok and "answer with the result table" in third.content


async def test_chart_cap_per_answer() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    ctx.workspace = FakeWorkspace()
    ctx.charts = [{}] * MAX_CHARTS
    assert not (await MakeChartTool().run(args(), ctx, "s1")).ok


async def test_profile_tool_returns_digest_and_adds_evidence() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    ctx.workspace = FakeWorkspace()
    ok = await GetDatasetProfileTool().run(ProfileArgs(dataset_id=TARGETS_ID), ctx, "s1")
    assert ok.ok and "3 rows" in ok.content
    result_not_dataset = await GetDatasetProfileTool().run(
        ProfileArgs(dataset_id=REVENUE_ID), ctx, "s1"
    )
    assert not result_not_dataset.ok


async def test_numbers_shown_in_the_profile_count_as_evidence() -> None:
    """Regression: correlations quoted from the profile were flagged as unverified figures."""
    from dataclasses import replace

    from eagleeye_agents.checks.numbers import unverified_figures

    class ProfiledWorkspace(FakeWorkspace):
        def _items(self):  # noqa: ANN202
            items = super()._items()
            profile = {
                **items[TARGETS_ID].profile,
                "correlations": [{"a": "pclass", "b": "fare", "r": -0.549}],
            }
            return {**items, TARGETS_ID: replace(items[TARGETS_ID], profile=profile)}

    ctx, _, _ = make_ctx(FakeLLM())
    ctx.workspace = ProfiledWorkspace()
    result = await GetDatasetProfileTool().run(ProfileArgs(dataset_id=TARGETS_ID), ctx, "s1")
    assert result.ok and "-0.549" in result.content
    answer = "The strongest correlation was pclass with fare (Pearson *r* = −0.549)."
    assert unverified_figures(answer, ctx.numeric_evidence, "explore my file") == []
