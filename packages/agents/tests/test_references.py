"""[file name] references and data-file awareness in the classifier."""

from dataclasses import dataclass

from eagleeye_agents import references, runner
from eagleeye_agents.context import AgentSettings
from eagleeye_agents.guard.classifier import build_user_message, describe_data_file
from eagleeye_agents.prompts.loader import load_prompts
from fakes import FakeLLM, FakeRetriever, FakeSink, Turn, guard_json
from test_runner import DB, FakeRedis, db  # noqa: F401 - db is a fixture


@dataclass(frozen=True)
class DS:
    id: str
    title: str
    filename: str
    sheet: str
    columns: tuple


BRENT = DS(
    "ds-1",
    "brent crude daily",
    "brent_crude_daily.csv",
    "",
    ({"name": "date"}, {"name": "brent_usd_per_barrel"}),
)
FORECAST = DS(
    "ds-2",
    "demand forecast 2027 by lane — Forecast",
    "demand_forecast_2027_by_lane.xlsx",
    "Forecast",
    ({"name": "trade_lane"}, {"name": "base_teu"}),
)


def test_tokens_skip_citations_and_duplicates() -> None:
    q = "Compare [brent_crude_daily.csv] with fuel [1] and [2, 3] and ['BRENT_crude_daily.csv']"
    assert references.tokens(q) == ["brent_crude_daily.csv"]


def test_data_files_match_by_file_name_title_or_sheet_case_insensitively() -> None:
    refs = references.resolve_datasets(
        ["Brent_Crude_Daily.csv", "demand_forecast_2027_by_lane.xlsx (Forecast)", "nope.csv"],
        [BRENT, FORECAST],
    )
    assert [r.id for r in refs] == ["ds-1", "ds-2"]
    assert refs[0].columns == ("date", "brent_usd_per_barrel")


def test_planner_note_gives_ids_and_columns() -> None:
    refs = [
        references.FileRef("data_file", "ds-1", "brent crude daily", ("date", "price")),
        references.FileRef("document", "doc-9", "Reefer SOP", scope="enterprise"),
    ]
    note = references.planner_note(refs)
    assert "id ds-1 (columns: date, price)" in note and "enterprise document 'Reefer SOP'" in note
    assert references.planner_note([]) == ""


def test_classifier_sees_the_users_data_files_and_columns() -> None:
    files = [describe_data_file("voyage utilisation by week", ["week_start", "vessel"])]
    msg = build_user_message("ships with week_start 2024-01-01", [], [], False, files)
    assert "User's data files: voyage utilisation by week (columns: week_start, vessel)" in msg
    assert "User's data files" not in build_user_message("hi", [], [], False)


class Workspace:
    async def list_datasets(self, user_id: str) -> list:
        return [BRENT]


async def test_naming_a_file_sends_the_question_to_the_planner_with_its_id(
    db: DB,  # noqa: F811
    monkeypatch,  # noqa: ANN001
) -> None:
    from eagleeye_agents import persistence

    async def question(pool, chat_id, run_id):  # noqa: ANN001, ANN202
        return "Plot [brent_crude_daily.csv] please", []

    monkeypatch.setattr(persistence, "load_conversation", question)
    # the classifier calls it small talk; the file reference still forces the planner
    llm = FakeLLM([guard_json(intent="chitchat"), "Brent chat"], [Turn("Here is the plot.")])
    deps = runner.RunnerDeps(
        pool=None,
        redis=FakeRedis(),
        llm=llm,
        retriever=FakeRetriever(),  # type: ignore[arg-type]
        settings=AgentSettings(),
        prompts=load_prompts(),
        model_ids={"capable": "m"},
        workspace=Workspace(),
    )
    await runner.execute_run(deps, "r1", lambda rid: FakeSink())
    system = llm.stream_calls[0]["messages"][0].content
    assert "data file 'brent crude daily', id ds-1" in system
    guard_input = llm.complete_calls[0][1].content
    assert (
        "User's data files: brent crude daily (columns: date, brent_usd_per_barrel)" in guard_input
    )
