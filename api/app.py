import logging
import os
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.pipeline import Pipeline
from core.agent_runtime import AgentRuntime, build_pipeline_agent_runtime
from api.schemas import (
    AgentQueryRequest,
    AgentQueryResponse,
    AgentSourceItem,
    QueryRequest,
    QueryResponse,
    SourceItem,
    IndexResponse,
    HealthResponse,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MiB
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB
MAX_FILENAME_LENGTH = 255
ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf", ".py", ".js", ".java")
_WINDOWS_ILLEGAL_CHARS = set('<>:"|?*')


pipeline: Optional[Pipeline] = None
agent_runtime: Optional[AgentRuntime] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline, agent_runtime
    try:
        pipeline = Pipeline(
            config_path="config.yaml",
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )
    except Exception as e:
        print(f"[WARN] Pipeline init failed (will retry on first request): {e}")
        pipeline = None
    agent_runtime = None
    if pipeline is not None:
        try:
            provider, api_key = _resolve_agent_provider(pipeline)
            agent_runtime = build_pipeline_agent_runtime(
                pipeline,
                planner_provider=provider,
                api_key=api_key,
            )
        except Exception:
            logger.exception("Agent runtime init failed")
            agent_runtime = None
    yield
    pipeline = None
    agent_runtime = None


app = FastAPI(
    title="RAG Knowledge Base API",
    description="Local RAG system: index documents and ask questions",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _get_pipeline() -> Pipeline:
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    return pipeline


def _resolve_agent_provider(p) -> tuple[str, Optional[str]]:
    """按 Generator 供应商解析 Agent Planner 的 provider 与 api_key。"""
    provider = str(getattr(p.config, "generator_provider", "") or "").lower()
    if provider == "deepseek":
        return "deepseek", os.getenv("DEEPSEEK_API_KEY")
    return "openai", os.getenv("OPENAI_API_KEY")


def _get_agent_runtime() -> AgentRuntime:
    if agent_runtime is None:
        raise HTTPException(status_code=503, detail="Agent runtime not initialized")
    return agent_runtime


def _build_agent_response(result) -> AgentQueryResponse:
    sources = []
    for item in (result.evidence_bundle.items if result.evidence_bundle else ()):
        sources.append(
            AgentSourceItem(
                citation_id=item.citation_id,
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                source=item.source_name,
                content=item.content[:200],
                score=item.score,
                rank=item.rank,
            )
        )
    return AgentQueryResponse(
        schema_version="agent_query_response_v1",
        run_id=result.run_id,
        status=result.status,
        answer=result.answer,
        sources=sources,
        planner=(
            result.planner_outcome.to_dict()
            if result.planner_outcome is not None
            else None
        ),
        route=(
            result.route_decision.to_dict()
            if result.route_decision is not None
            else None
        ),
        verification=(
            result.verification.to_dict()
            if result.verification is not None
            else None
        ),
        trace=[event.to_dict() for event in result.trace],
        error_code=result.error_code,
        warnings=list(result.warnings),
    )


@app.get("/health", response_model=HealthResponse)
def health():
    p = _get_pipeline()
    return HealthResponse(
        docs_count=p.vector_store.count(),
        embedding_provider=p.config.embedding_provider,
        retriever_strategy=p.config.retriever_strategy,
        generator_provider=p.config.generator_provider,
    )


def _validate_filename(filename: str) -> None:
    if not filename:
        raise HTTPException(status_code=400, detail="No file provided")
    if filename in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: path separators are not allowed",
        )
    if any(ord(c) < 32 or ord(c) == 127 for c in filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: control characters are not allowed",
        )
    if any(c in _WINDOWS_ILLEGAL_CHARS for c in filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if len(filename) > MAX_FILENAME_LENGTH:
        raise HTTPException(status_code=400, detail="Invalid filename: too long")
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: .txt, .md, .pdf, .py, .js, .java",
        )


def _copy_upload(file_obj, dst_path: str, max_bytes: int) -> int:
    total = 0
    with open(dst_path, "wb") as out:
        while True:
            chunk = file_obj.read(UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="File too large (max 20 MiB)",
                )
            out.write(chunk)
    return total


@app.post("/index/file", response_model=IndexResponse)
def index_file(file: UploadFile = File(...)):
    p = _get_pipeline()
    filename = file.filename or ""
    _validate_filename(filename)

    try:
        with tempfile.TemporaryDirectory(prefix="rag_upload_") as tmp_dir:
            tmp_path = os.path.join(tmp_dir, filename)
            total = _copy_upload(file.file, tmp_path, MAX_UPLOAD_BYTES)
            if total == 0:
                raise HTTPException(status_code=400, detail="Empty file")
            result = p.index_file(tmp_path)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Indexing failed")
        raise HTTPException(status_code=500, detail="Internal indexing error")

    return IndexResponse(
        file_name=filename,
        chunks=result.get("chunks", 0),
        status=result.get("status", "success"),
    )


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    p = _get_pipeline()

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        history = [m.model_dump() for m in req.history]
        result = p.query(req.question, top_k=req.top_k, history=history)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Query failed")
        raise HTTPException(status_code=500, detail="Internal query error")

    sources = [
        SourceItem(
            content=s["content"],
            source=s["source"],
            score=s["score"],
        )
        for s in result["sources"]
    ]

    return QueryResponse(answer=result["answer"], sources=sources)


@app.post("/agent/query", response_model=AgentQueryResponse)
def agent_query(req: AgentQueryRequest):
    """Agentic RAG 问答入口：Planner → Runtime → BM25 → Generator → Citation。

    本版本不接 history（AgentQueryRequest extra=forbid，显式拒绝）；
    completed/refused/deferred/failed 都返回结构化结果，deferred 不伪装成
    成功回答。Agent Runtime 未初始化时返回 503，不泄露内部异常。
    """
    rt = _get_agent_runtime()
    try:
        result = rt.run(req.question, top_k=req.top_k)
    except Exception:
        logger.exception("Agent query failed")
        raise HTTPException(status_code=500, detail="Internal agent query error")
    return _build_agent_response(result)


@app.get("/stats")
def stats():
    p = _get_pipeline()
    return {
        "documents_count": p.vector_store.count(),
        "config": p.config,
    }
