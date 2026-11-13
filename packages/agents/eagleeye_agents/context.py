"""Everything a node needs for one run. Built by the runner; graph nodes close over it."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from eagleeye_llm.gateway import ChatMessage, LLMGateway
from eagleeye_retrieval.types import AccessScope, RetrievalResult

from eagleeye_agents.budgets import BudgetLimits, BudgetTracker
from eagleeye_agents.control import CancelToken, TextChannel, UsageMeter
from eagleeye_agents.prompts.loader import Prompts
from eagleeye_agents.sources import SourceRegistry
from eagleeye_agents.steps import Sink, StepRecorder


@dataclass(frozen=True)
class DocInfo:
    id: str
    title: str
    scope: str
    page_count: int | None
    chunk_count: int | None


class RetrieverPort(Protocol):
    async def retrieve(
        self,
        question: str,
        history: list[ChatMessage],
        scope: AccessScope,
        rewrite: bool = True,
    ) -> RetrievalResult: ...


class RunStore(Protocol):
    """The few reads/writes nodes need mid-run (final persistence is the runner's job)."""

    async def visible_ready_documents(self, user_id: str) -> list[DocInfo]: ...

    async def record_security_event(
        self, user_id: str, run_id: str, kind: str, category: str, detail: dict[str, Any]
    ) -> None: ...


@dataclass(frozen=True)
class AgentSettings:
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    rag_min_score: float = 0.25
    denied_topics: tuple[str, ...] = ()
    answer_max_tokens: int = 2048


@dataclass
class RunContext:
    run_id: str
    chat_id: str
    user_id: str
    llm: LLMGateway
    retriever: RetrieverPort
    store: RunStore
    sink: Sink
    cancel: CancelToken
    prompts: Prompts
    settings: AgentSettings
    steps: StepRecorder
    text: TextChannel
    sources: SourceRegistry = field(default_factory=SourceRegistry)
    usage: UsageMeter = field(default_factory=UsageMeter)
    # Phase 4 (text-to-SQL). `user_role` comes from the users table, never from model output.
    gateway: Any = None  # sql.gateway_client.GatewayPort
    catalog: Any = None  # eagleeye_catalog.service.CatalogService
    user_role: str = "member"
    sql_available: bool = False
    artifacts: list[Any] = field(default_factory=list)  # sql.types.ArtifactRef, in run order
    warnings: list[str] = field(default_factory=list)  # e.g. "unverified_numbers"
    numeric_evidence: list[float] = field(default_factory=list)  # numbers the model was shown
    budget: BudgetTracker = field(init=False)

    def __post_init__(self) -> None:
        self.budget = BudgetTracker(self.settings.limits)

    @classmethod
    def create(cls, **kwargs: Any) -> "RunContext":
        sink: Sink = kwargs["sink"]
        return cls(steps=StepRecorder(sink), text=TextChannel(sink), **kwargs)
