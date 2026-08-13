from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

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


class AgentQueryRequest(BaseModel):
    """/agent/query 请求。本版本不接 history：未定义字段（含 history）显式
    拒绝（extra=forbid），绝不静默忽略。"""

    model_config = {"extra": "forbid"}

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)

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
