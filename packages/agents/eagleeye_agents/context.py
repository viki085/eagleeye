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

    async def record_sql_refusal(
        self, user_id: str, run_id: str, data_source_id: str | None, sql: str, reason: str
    ) -> None: ...


@dataclass(frozen=True)
class AgentSettings:
    limits: BudgetLimits = field(default_factory=BudgetLimits)
    rag_min_score: float = 0.25
    denied_topics: tuple[str, ...] = ()
    answer_max_tokens: int = 2048
    analysis_max_seconds: float = 240.0  # run deadline when analysis tools are offered
    notebook_max_seconds: float = 300.0  # run deadline when notebook mode is offered
    demo_notebook_runs: int = 3  # notebooks a demo visit may make (then the light analysis)


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
    # Phase 5 (data files, analysis sandbox, charts)
    workspace: Any = None  # analysis.workspace.DataWorkspace (owner-scoped data access)
    executor: Any = None  # eagleeye_sandbox.types.AnalysisExecutor
    analysis_available: bool = False  # sandbox reachable → analyze_data offered
    python_analysis: bool = True
    sandbox_runs_per_hour: int = 60
    python_runs: int = 0
    charts: list[dict[str, Any]] = field(default_factory=list)  # chart event payloads, in order
    # Notebook mode (company users only; never the shared demo account)
    notebook_available: bool = False  # explore_data offered
    notebook_executor: Any = None  # the sandbox with notebook limits (longer, more memory)
    notebook_quota_exhausted: bool = False  # demo visit used its notebook(s): say so if asked
    notebooks: list[dict[str, Any]] = field(default_factory=list)  # notebook event payloads
    cache: Any = None  # eagleeye_core.app_cache.AppCache (None = no caching)
    figure_loader: Any = None  # async (object key) -> PNG bytes; None = figures not sent
    answer_key: tuple | None = None  # set when this run's answer may be reused or stored
    data_files: list[Any] = field(default_factory=list)  # the user's READY data files
    references: list[Any] = field(default_factory=list)  # references.FileRef named as [file]
    budget: BudgetTracker = field(init=False)

    def __post_init__(self) -> None:
        self.budget = BudgetTracker(self.settings.limits)

    @classmethod
    def create(cls, **kwargs: Any) -> "RunContext":
        sink: Sink = kwargs["sink"]
        return cls(steps=StepRecorder(sink), text=TextChannel(sink), **kwargs)
