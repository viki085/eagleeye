"""Tools exposed to the supervisor. Phases 4–5 add run_sql / analyze_data / make_chart here."""

from eagleeye_llm.gateway import ToolSpec

from eagleeye_agents.tools.base import Tool, spec_of
from eagleeye_agents.tools.list_documents import ListDocumentsTool
from eagleeye_agents.tools.search_knowledge import SearchKnowledgeTool


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [spec_of(t) for t in self._tools.values()]


def default_registry() -> ToolRegistry:
    return ToolRegistry([SearchKnowledgeTool(), ListDocumentsTool()])
