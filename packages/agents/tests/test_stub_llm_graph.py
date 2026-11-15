"""The load-test stub model drives the real agent graph down each route the k6 script uses."""

from types import SimpleNamespace

from analysis_fakes import REVENUE_ID, FakeWorkspace, enable_analysis
from eagleeye_agents.graph import run_graph
from eagleeye_llm.stub import StubLLM, StubTiming
from fakes import make_ctx

FAST = StubTiming(first_token_s=0, words_per_s=0, answer_words=20, complete_s=0)


class ListingWorkspace(FakeWorkspace):
    async def list_datasets(self, user_id: str) -> list:
        columns = [{"name": "month", "type": "VARCHAR"}, {"name": "revenue", "type": "DOUBLE"}]
        return [
            SimpleNamespace(
                id=REVENUE_ID, title="revenue", row_count=3, columns=columns, summary=""
            )
        ]


def _state(question: str) -> dict:
    return {"question": question, "history": [], "doc_ids": []}


async def test_small_talk_succeeds_on_the_simple_route() -> None:
    ctx, _, _ = make_ctx(StubLLM(FAST))
    final = await run_graph(ctx, _state("hello"))
    assert final["route"] == "simple" and final["status"] == "SUCCEEDED"
    assert len(ctx.text.value.split()) == 20


async def test_docs_question_retrieves_and_cites() -> None:
    ctx, _, _ = make_ctx(StubLLM(FAST))
    final = await run_graph(ctx, _state("#docs how long do refunds take?"))
    assert final["route"] == "rag" and final["status"] == "SUCCEEDED"
    assert final["citations"] and final["citations"][0]["chunk_id"] == "c1"


async def test_analysis_runs_code_in_the_sandbox() -> None:
    ctx, sink, _ = make_ctx(StubLLM(FAST))
    executor = enable_analysis(ctx, workspace=ListingWorkspace())
    final = await run_graph(ctx, _state("#analysis how many rows are in my data?"))
    assert final["route"] == "supervisor" and final["status"] == "SUCCEEDED"
    assert len(executor.tasks) == 1 and "ds_1" in executor.tasks[0].code
    assert len(sink.of("artifact")) == 1
