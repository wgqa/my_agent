from typing import List, Literal

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
