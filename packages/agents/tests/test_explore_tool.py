"""explore_data: offered only when notebook mode is on for this user; one notebook per answer;
the notebook is emitted to the UI and its numbers count as evidence."""

from analysis_fakes import TARGETS_ID, FakeExecutor, enable_analysis
from eagleeye_agents.tools.explore_data import ExploreArgs, ExploreDataTool
from eagleeye_agents.tools.registry import default_registry
from fakes import FakeLLM, make_ctx
from test_notebook_agent import CELLS, draft, ok_run


def test_offered_only_when_notebook_mode_is_on() -> None:
    assert "explore_data" not in default_registry(include_data=True, include_analysis=True).names()
    names = default_registry(
        include_data=True, include_analysis=True, include_notebook=True
    ).names()
    assert "explore_data" in names and "analyze_data" in names


async def test_notebook_is_emitted_and_grounded() -> None:
    ctx, sink, _ = make_ctx(FakeLLM([draft(*CELLS)]))
    ctx.notebook_executor = enable_analysis(ctx, FakeExecutor([ok_run()]))
    ctx.notebook_available = True
    result = await ExploreDataTool().run(
        ExploreArgs(goal="explore in depth", inputs=[TARGETS_ID]), ctx, "s1"
    )
    assert result.ok and "Target by month" in result.content
    (event,) = sink.of("notebook")
    assert event["title"] == "Targets EDA" and event["figure_count"] == 1
    assert ctx.notebooks == [event] and 100.0 in ctx.numeric_evidence


async def test_one_notebook_per_answer() -> None:
    ctx, _, _ = make_ctx(FakeLLM([draft(*CELLS)]))
    ctx.notebook_executor = enable_analysis(ctx, FakeExecutor([ok_run()]))
    ctx.notebook_available = True
    ctx.notebooks = [{"notebook_id": "earlier"}]
    result = await ExploreDataTool().run(ExploreArgs(goal="again", inputs=[TARGETS_ID]), ctx, "s1")
    assert not result.ok and "one notebook" in result.content


async def test_refused_when_notebook_mode_is_off_for_this_user() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    ctx.notebook_executor = enable_analysis(ctx, FakeExecutor([ok_run()]))
    ctx.notebook_available = False  # e.g. the shared demo account
    result = await ExploreDataTool().run(
        ExploreArgs(goal="explore", inputs=[TARGETS_ID]), ctx, "s1"
    )
    assert not result.ok and "not available" in result.content.lower()
