"""Tool contract (LLD §3.3): typed args, timeout, read-only, structured result."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from eagleeye_llm.gateway import ToolSpec
from pydantic import BaseModel

if TYPE_CHECKING:
    from eagleeye_agents.context import RunContext


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    content: str  # what the model sees (wrapped in <tool_data> by the executor)
    summary: str  # one line for the step tree
    error_code: str | None = None


class Tool(Protocol):
    name: str
    description: str
    args_model: type[BaseModel]
    timeout_s: float

    async def run(self, args: BaseModel, ctx: "RunContext") -> ToolResult: ...


def spec_of(tool: Tool) -> ToolSpec:
    schema = tool.args_model.model_json_schema()
    schema.pop("title", None)
    return ToolSpec(tool.name, tool.description, schema)


def error_result(code: str, message: str) -> ToolResult:
    return ToolResult(ok=False, content=f"Error: {message}", summary=message, error_code=code)
