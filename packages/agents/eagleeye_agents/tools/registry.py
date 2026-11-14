"""Tools exposed to the supervisor, offered only when this user can actually use them."""

from eagleeye_llm.gateway import ToolSpec

from eagleeye_agents.tools.analyze_data import AnalyzeDataTool
from eagleeye_agents.tools.base import Tool, spec_of
from eagleeye_agents.tools.explore_data import ExploreDataTool
from eagleeye_agents.tools.list_data_sources import ListDataSourcesTool
from eagleeye_agents.tools.list_datasets import GetDatasetProfileTool, ListDatasetsTool
from eagleeye_agents.tools.list_documents import ListDocumentsTool
from eagleeye_agents.tools.make_chart import MakeChartTool
from eagleeye_agents.tools.query_database import QueryDatabaseTool
from eagleeye_agents.tools.search_knowledge import SearchKnowledgeTool


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [spec_of(t) for t in self._tools.values()]


def default_registry(
    include_sql: bool = False,
    include_data: bool = False,
    include_analysis: bool = False,
    include_notebook: bool = False,
) -> ToolRegistry:
    """Each capability's tools appear only when it is enabled AND usable by this user, so the
    model can't even attempt something the user lacks:
    SQL → a reachable data source; data → the data-file store; analysis → the sandbox;
    notebook → notebook mode for this user (company users, never the shared demo account)."""
    tools: list[Tool] = [SearchKnowledgeTool(), ListDocumentsTool()]
    if include_sql:
        tools += [QueryDatabaseTool(), ListDataSourcesTool()]
    if include_data:
        tools += [ListDatasetsTool(), GetDatasetProfileTool()]
    if include_analysis:
        tools.append(AnalyzeDataTool())
    if include_analysis and include_notebook:
        tools.append(ExploreDataTool())
    if include_sql or include_data:
        tools.append(MakeChartTool())  # charts need no sandbox, only a table to plot
    return ToolRegistry(tools)
