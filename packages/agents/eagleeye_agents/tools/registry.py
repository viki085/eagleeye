"""Tools exposed to the supervisor. Phase 5 adds analyze_data / make_chart here."""

from eagleeye_llm.gateway import ToolSpec

from eagleeye_agents.tools.base import Tool, spec_of
from eagleeye_agents.tools.list_data_sources import ListDataSourcesTool
from eagleeye_agents.tools.list_documents import ListDocumentsTool
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


def default_registry(include_sql: bool = False) -> ToolRegistry:
    """SQL tools appear only when SQL is enabled AND this user can reach a data source,
    so the model can't even attempt a capability the user lacks."""
    tools: list[Tool] = [SearchKnowledgeTool(), ListDocumentsTool()]
    if include_sql:
        tools += [QueryDatabaseTool(), ListDataSourcesTool()]
    return ToolRegistry(tools)
