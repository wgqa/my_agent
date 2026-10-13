import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from core.tool_agent.source_excerpt import (
    MAX_PROJECT_CHANGE_CHARACTERS,
    MAX_PROJECT_CONTEXT_CHARACTERS,
    project_evidence_character_limit,
)

MAX_QUESTION_CHARS = 4000
MAX_TOP_K = 50
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_CONTENT_CHARS = 8000


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_HISTORY_CONTENT_CHARS)

    @field_validator("content")
    @classmethod
    def _reject_blank_content(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank")
        return v


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)
    history: List[HistoryMessage] = Field(default_factory=list)

    @field_validator("history")
    @classmethod
    def _limit_history(cls, v: List[HistoryMessage]) -> List[HistoryMessage]:
        if len(v) > MAX_HISTORY_MESSAGES:
            raise ValueError(f"history must have at most {MAX_HISTORY_MESSAGES} messages")
        return v


class SourceItem(BaseModel):
    content: str
    source: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceItem]


class IndexResponse(BaseModel):
    file_name: str
    chunks: int
    status: str = "success"


class HealthResponse(BaseModel):
    status: str = "ok"
    docs_count: int = 0
    embedding_provider: str = ""
    retriever_strategy: str = ""
    generator_provider: str = ""


class ProductVersionResponse(BaseModel):
    schema_version: Literal["product_version_v1"]
    product_name: str
    version: str
    stage: Literal["development"]


class PublicConfigResponse(BaseModel):
    """Allowlisted runtime configuration safe for release API clients."""

    embedding_provider: str
    embedding_model: str
    chunker_strategy: str
    chunk_size: int
    chunk_overlap: int
    retriever_strategy: str
    top_k: int
    reranker_enabled: bool
    generator_provider: str
    generator_model: str


class StatsResponse(BaseModel):
    documents_count: int
    config: PublicConfigResponse


class FeatureCapabilities(BaseModel):
    indexing: bool
    basic_rag: bool
    agentic_rag: bool
    structured_tool_agent: bool
    engineering_agent: bool


class CapabilitiesResponse(BaseModel):
    schema_version: str
    pipeline_ready: bool
    agent_runtime_ready: bool
    tool_agent_runtime_ready: bool
    features: FeatureCapabilities


class EngineeringKnowledgeStatusResponse(BaseModel):
    """Safe public identity/readiness for the dedicated Engineering backend."""

    schema_version: str
    ready: bool
    verified: bool
    corpus_id: Optional[str] = None
    file_count: Optional[int] = None
    chunk_count: Optional[int] = None
    retrieval_strategy: Optional[str] = None
    manifest_experiment_id: Optional[str] = None
    mode: Literal["managed", "verified"] = "verified"
    mutable: bool = False
    revision: Optional[int] = None
    search_scope: Literal["all_documents"] = "all_documents"


class KnowledgeDocumentSummary(BaseModel):
    id: str
    name: str
    file_type: str
    size_bytes: int
    chunk_count: int
    origin: Literal["seed", "upload"]
    created_at: str
    updated_at: str
    status: Literal["ready"]


class KnowledgeDocumentDetail(KnowledgeDocumentSummary):
    content: str
    content_length: int
    offset: int
    next_offset: Optional[int] = None


class KnowledgeDocumentListResponse(BaseModel):
    items: List[KnowledgeDocumentSummary]
    total: int
    file_count: int
    chunk_count: int
    revision: int
    limit: int
    offset: int
    search_scope: Literal["all_documents"]


class KnowledgeUploadResponse(BaseModel):
    document: KnowledgeDocumentSummary
    status: Literal["create", "update", "no_change"]
    revision: int


class ProjectResponse(BaseModel):
    """Public identity for the single bound Engineering Project Workspace."""

    project_name: str
    source: Literal["default_repo", "configured"]


class AgentQueryRequest(BaseModel):
    """/agent/query 请求。history 只属于 Agentic RAG 的用户会话上下文。"""

    model_config = {"extra": "forbid"}

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)
    history: List[HistoryMessage] = Field(default_factory=list)

    @field_validator("history")
    @classmethod
    def _limit_history(cls, v: List[HistoryMessage]) -> List[HistoryMessage]:
        if len(v) > MAX_HISTORY_MESSAGES:
            raise ValueError(f"history must have at most {MAX_HISTORY_MESSAGES} messages")
        return v

    @field_validator("question")
    @classmethod
    def _reject_blank_question(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v


class AgentSourceItem(BaseModel):
    citation_id: str
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    source: str
    content: str
    score: Optional[float] = None
    rank: int
    query_id: Optional[str] = None


class AgentQueryResponse(BaseModel):
    schema_version: str
    run_id: str
    status: str
    answer: Optional[str] = None
    sources: List[AgentSourceItem]
    planner: Optional[dict] = None
    route: Optional[dict] = None
    verification: Optional[dict] = None
    trace: List[dict]
    error_code: Optional[str] = None
    warnings: List[str]


class ToolAgentQueryRequest(BaseModel):
    """/tool-agent/query 请求 v1。只接受 question；history / provider / model /
    budget / max_iterations / max_tool_calls / max_tool_errors / tool allowlist /
    system prompt 一律属于系统边界，未定义字段（含以上）显式拒绝（extra=forbid）。"""

    model_config = {"extra": "forbid"}

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def _reject_blank_question(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v


class ToolAgentChangeStatus(BaseModel):
    """One source-verified row from a changed_files status inventory."""

    model_config = {"extra": "forbid"}

    path: str = Field(min_length=1)
    status: Literal["modified", "added", "deleted", "renamed", "untracked"]
    old_path: Optional[str] = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_rename_shape(self):
        if (self.status == "renamed") != (self.old_path is not None):
            raise ValueError("renamed status must carry old_path, and other statuses must not")
        for path in (self.path, self.old_path):
            if path is None:
                continue
            windows_path = PureWindowsPath(path)
            posix_path = PurePosixPath(path)
            if (
                not path.strip()
                or path != path.strip()
                or "\\" in path
                or windows_path.is_absolute()
                or windows_path.drive
                or posix_path.is_absolute()
                or any(part in ("", ".", "..") for part in path.split("/"))
                or any(ord(char) < 32 for char in path)
            ):
                raise ValueError("status entry path must be a safe repo-relative POSIX path")
        return self


class ToolAgentEvidence(BaseModel):
    """Public project evidence and provenance-bound Tool result records."""

    model_config = {"json_schema_extra": {"allOf": [{
        "if": {"properties": {"kind": {"const": "project_change"}}, "required": ["kind"]},
        "then": {"properties": {"snippet": {"maxLength": MAX_PROJECT_CHANGE_CHARACTERS}}},
    }]}}

    evidence_id: str = Field(pattern=r"^E[1-9][0-9]*$")
    kind: Literal["project_code", "project_doc", "project_change", "project_test"]
    path: Optional[str] = None
    start_line: Optional[int] = Field(default=None, ge=1)
    end_line: Optional[int] = Field(default=None, ge=1)
    snippet: Optional[str] = Field(default=None, min_length=1, max_length=MAX_PROJECT_CONTEXT_CHARACTERS)
    granularity: Optional[Literal["locator", "candidate", "status_list", "source_body", "diff"]] = None
    completeness: Optional[Literal["complete", "partial", "unknown"]] = None
    tool_name: Optional[Literal["code_search", "changed_files", "find_tests", "read_project_context", "git_diff"]] = None
    call_id: Optional[str] = None
    tool_version: Optional[str] = None
    arguments_json: Optional[str] = None
    arguments_sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    result_sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    scope: Optional[str] = None
    scope_paths: List[str] = Field(default_factory=list)
    requirement_eligible: Optional[bool] = None
    status_entries: List[ToolAgentChangeStatus] = Field(default_factory=list)
    candidate_reasons: List[Literal["mirrored_path", "filename_match", "content_reference"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enforce_kind_snippet_limit(self):
        if self.snippet is not None:
            limit = project_evidence_character_limit(self.kind)
            if len(self.snippet) > limit:
                raise ValueError(f"{self.kind} snippet must have at most {limit} characters")
        if self.candidate_reasons and self.granularity != "candidate":
            raise ValueError("candidate_reasons are valid only for candidate Evidence")
        if len(set(self.candidate_reasons)) != len(self.candidate_reasons):
            raise ValueError("candidate_reasons must not contain duplicates")
        if self.granularity is None:
            if (
                not self.path
                or self.start_line is None
                or self.end_line is None
                or self.snippet is None
                or self.completeness is not None
                or self.tool_name is not None
            ):
                raise ValueError("legacy project Evidence requires path, line range, and snippet")
            if self.status_entries or self.scope_paths or any(
                getattr(self, label) is not None
                for label in (
                    "call_id", "tool_version", "arguments_json", "arguments_sha256",
                    "result_sha256", "scope", "requirement_eligible",
                )
            ):
                raise ValueError("legacy project Evidence cannot carry partial Tool provenance")
            return self
        if self.completeness is None:
            raise ValueError("granular Evidence requires a completeness state")
        if self.tool_name is None and (
            self.granularity not in {"source_body", "diff"}
            or self.completeness != "unknown"
            or self.scope_paths
            or any(
                getattr(self, label) is not None
                for label in (
                    "call_id", "tool_version", "arguments_json", "arguments_sha256",
                    "result_sha256", "scope", "requirement_eligible",
                )
            )
        ):
            raise ValueError("legacy granular Evidence must be source_body/diff with unknown completeness")
        if self.path is not None:
            windows_path = PureWindowsPath(self.path)
            posix_path = PurePosixPath(self.path)
            if (
                not self.path.strip()
                or self.path != self.path.strip()
                or "\\" in self.path
                or windows_path.is_absolute()
                or windows_path.drive
                or posix_path.is_absolute()
                or any(part in ("", ".", "..") for part in self.path.split("/"))
                or any(ord(char) < 32 for char in self.path)
            ):
                raise ValueError("path must be a safe repo-relative POSIX path")
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("line range must provide both start_line and end_line")
        if self.start_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        if self.granularity == "source_body":
            if self.kind not in {"project_code", "project_doc", "project_test"}:
                raise ValueError("source_body requires code, documentation, or test kind")
        elif self.granularity == "diff":
            if self.kind != "project_change":
                raise ValueError("diff requires project_change kind")
        elif self.granularity == "locator":
            if self.tool_name != "code_search" or self.kind not in {"project_code", "project_doc", "project_test"}:
                raise ValueError("locator requires a code_search result kind")
        elif self.granularity == "candidate":
            if self.tool_name != "find_tests" or self.kind != "project_test":
                raise ValueError("candidate requires a find_tests project_test result")
        elif self.granularity == "status_list":
            if self.tool_name != "changed_files" or self.kind != "project_change":
                raise ValueError("status_list requires a changed_files project_change result")
            if not self.status_entries and not (
                self.completeness == "complete" and not self.scope_paths
            ):
                raise ValueError("status_list requires structured status entries")
        elif self.status_entries:
            raise ValueError("status_entries are valid only for status_list Evidence")
        if self.granularity in {"locator", "candidate"} and (
            not self.path or self.start_line is None or self.start_line != self.end_line
        ):
            raise ValueError("locator/candidate Evidence requires one path and line")
        if self.granularity == "status_list" and (self.path is not None or self.start_line is not None or self.snippet is not None):
            raise ValueError("status_list must not impersonate a single file body or diff")
        if self.granularity in {"source_body", "diff"} and (
            not self.path or self.start_line is None
        ):
            raise ValueError("source_body/diff Evidence requires a source path and line range")
        if self.tool_name is not None:
            for label in ("call_id", "tool_version", "arguments_json", "arguments_sha256", "result_sha256", "scope"):
                if not getattr(self, label):
                    raise ValueError(f"Tool result Evidence requires {label}")
            if self.requirement_eligible is None:
                raise ValueError("Tool result Evidence requires requirement_eligible")
            if not self.scope_paths and not (
                self.granularity == "status_list"
                and self.completeness == "complete"
                and not self.status_entries
            ):
                raise ValueError("Tool result Evidence requires scope_paths")
            if len(set(self.scope_paths)) != len(self.scope_paths):
                raise ValueError("scope_paths must not contain duplicates")
            if self.path is not None and self.path not in self.scope_paths:
                raise ValueError("path must be included in scope_paths")
            if any(
                entry.path not in self.scope_paths
                or (entry.old_path is not None and entry.old_path not in self.scope_paths)
                for entry in self.status_entries
            ):
                raise ValueError("status entries must be within scope_paths")
            entry_keys = {
                (entry.path, entry.status, entry.old_path)
                for entry in self.status_entries
            }
            if len(entry_keys) != len(self.status_entries):
                raise ValueError("status_entries must not contain duplicates")
            if any(
                type(path) is not str
                or not path.strip()
                or "\\" in path
                or PureWindowsPath(path).is_absolute()
                or PureWindowsPath(path).drive
                or PurePosixPath(path).is_absolute()
                or any(part in ("", ".", "..") for part in path.split("/"))
                or any(ord(char) < 32 for char in path)
                for path in self.scope_paths
            ):
                raise ValueError("scope_paths must be safe repo-relative paths")
        eligible = (
            (self.kind in {"project_code", "project_doc", "project_test"} and self.granularity == "source_body")
            or (self.kind == "project_change" and self.granularity == "diff")
        ) and self.completeness == "complete"
        if self.requirement_eligible is not None and self.requirement_eligible != eligible:
            raise ValueError("requirement_eligible does not match source granularity/completeness")
        return self


class EngineeringQueryRequest(BaseModel):
    """Unified Engineering Agent request v1: only the user question is public."""

    model_config = {"extra": "forbid"}

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def _reject_blank_question(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v


class KnowledgeEvidence(BaseModel):
    """Public bounded evidence from the persistent knowledge backend."""

    evidence_id: str = Field(pattern=r"^E[1-9][0-9]*$")
    kind: Literal["knowledge"]
    source_name: str = Field(min_length=1)
    chunk_id: Optional[str] = None
    score: Optional[float] = None
    rank: int = Field(ge=1)
    snippet: str = Field(min_length=1, max_length=500)

    @field_validator("source_name")
    @classmethod
    def _reject_unsafe_source_name(cls, v: str) -> str:
        windows_path = PureWindowsPath(v)
        posix_path = PurePosixPath(v)
        if (
            not v.strip()
            or v != v.strip()
            or windows_path.is_absolute()
            or windows_path.drive
            or posix_path.is_absolute()
            or v.startswith("\\")
            or any(part in (".", "..") for part in windows_path.parts)
            or any(part in (".", "..") for part in posix_path.parts)
        ):
            raise ValueError("source_name must be a safe relative identity")
        return v

    @field_validator("score")
    @classmethod
    def _require_finite_score(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not math.isfinite(v):
            raise ValueError("score must be finite")
        return v


EngineeringEvidence = Annotated[
    Union[KnowledgeEvidence, ToolAgentEvidence],
    Field(discriminator="kind"),
]


class EngineeringExecutionMetrics(BaseModel):
    """Safe execution summary (PRODUCT-ENGINEERING-24B).

    ``elapsed_ms`` covers the whole product request; ``decision_llm_calls``
    counts loop decisions and ``selector_llm_calls`` counts the optional typed
    finalization request. Token fields aggregate provider-reported usage and are null when no call
    reported usage (never estimated or fabricated).
    """

    elapsed_ms: int
    decision_llm_calls: int
    selector_llm_calls: int = 0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    selector_latency_ms: Optional[float] = None


class EngineeringFeedback(BaseModel):
    """Product guidance for a non-completed outcome; never grounding evidence."""

    title: str
    message: str
    next_steps: List[str]
    action: Optional[Literal["revise", "retry"]] = None


class EngineeringQueryResponse(BaseModel):
    """Unified public contract for Knowledge/Repository/Change/Test evidence."""

    schema_version: str
    status: str
    answer: Optional[str] = None
    reason_code: Optional[str] = None
    failure_code: Optional[str] = None
    iterations_used: int
    tool_calls_used: int
    tool_errors_used: int
    trace: List[dict]
    evidence: List[EngineeringEvidence]
    execution: Optional[EngineeringExecutionMetrics] = None
    feedback: Optional[EngineeringFeedback] = None


class EngineeringConversationMessageRequest(BaseModel):
    """One server-owned conversation turn; clients never submit history,
    project, provider, model, budget, tools, prompt, or context window."""

    model_config = {"extra": "forbid"}

    message: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("message")
    @classmethod
    def _reject_blank_message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v


class LocalProjectCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    path: str = Field(min_length=1, max_length=4096)


class LocalProjectSummary(BaseModel):
    id: str
    project_name: str
    source: Literal["default_repo", "configured"]
    is_default: bool
    available: bool


class LocalProjectListResponse(BaseModel):
    projects: List[LocalProjectSummary]


class EngineeringConversationCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    project_id: Optional[str] = Field(default=None, min_length=1, max_length=64)


class EngineeringConversationSummary(BaseModel):
    """Public conversation metadata; never a project key, root, or local path."""

    schema_version: str = "engineering_conversation_v1"
    id: str
    title: str
    project_name: str
    project_source: str
    project_id: Optional[str] = None
    created_at: str
    updated_at: str


class EngineeringConversationMessageView(BaseModel):
    """One stored message. ``result`` is only present on assistant turns and
    carries the same public Engineering response contract as the live API."""

    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    result: Optional[dict] = None


class EngineeringConversationDetail(BaseModel):
    schema_version: str = "engineering_conversation_v1"
    id: str
    title: str
    project_name: str
    project_source: str
    project_id: Optional[str] = None
    created_at: str
    updated_at: str
    messages: List[EngineeringConversationMessageView]


class EngineeringConversationListResponse(BaseModel):
    schema_version: str = "engineering_conversation_list_v1"
    conversations: List[EngineeringConversationSummary]


class ToolAgentQueryResponse(BaseModel):
    """/tool-agent/query 响应 v1（冻结）。

    只回结构化安全事实；绝不含 raw model response / 完整 Prompt / CoT /
    API key / traceback / 本机敏感绝对路径。
    """

    schema_version: str
    status: str
    answer: Optional[str] = None
    reason_code: Optional[str] = None
    failure_code: Optional[str] = None
    iterations_used: int
    tool_calls_used: int
    tool_errors_used: int
    trace: List[dict]
    evidence: List[ToolAgentEvidence]
