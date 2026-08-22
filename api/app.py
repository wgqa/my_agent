import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.agent_runtime import AgentRuntime, build_pipeline_agent_runtime
from core.agent_runtime.adapters import PipelineRetrievalAdapter
from core.engineering_agent import EngineeringAgentFacade
from core.generator.deepseek_gen import DEEPSEEK_BASE_URL
from core.pipeline import Pipeline
from core.tool_agent import (
    ToolAgentRunResult,
    ToolAgentRuntime,
    build_tool_agent_runtime,
)
from api.schemas import (
    AgentQueryRequest,
    AgentQueryResponse,
    AgentSourceItem,
    QueryRequest,
    QueryResponse,
    SourceItem,
    IndexResponse,
    HealthResponse,
    PublicConfigResponse,
    StatsResponse,
    CapabilitiesResponse,
    FeatureCapabilities,
    ToolAgentQueryRequest,
    ToolAgentEvidence,
    ToolAgentQueryResponse,
    ProjectResponse,
    EngineeringQueryRequest,
    EngineeringQueryResponse,
    KnowledgeEvidence,
)
from api.project_workspace import EngineeringProject, resolve_engineering_project
from core.tool_agent.runtime_models import (
    EngineeringEvidence as RuntimeEngineeringEvidence,
    KnowledgeEvidence as RuntimeKnowledgeEvidence,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MiB
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB
MAX_FILENAME_LENGTH = 255
ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf", ".py", ".js", ".java")
_WINDOWS_ILLEGAL_CHARS = set('<>:"|?*')


pipeline: Optional[Pipeline] = None
agent_runtime: Optional[AgentRuntime] = None
tool_agent_runtime: Optional[ToolAgentRuntime] = None
engineering_agent_facade: Optional[EngineeringAgentFacade] = None
engineering_project: Optional[EngineeringProject] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline, agent_runtime, tool_agent_runtime, engineering_agent_facade, engineering_project
    # The system owns this binding. A bad explicit value aborts startup instead
    # of silently running code_search against a different repository.
    engineering_project = resolve_engineering_project(REPO_ROOT)
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
    tool_agent_runtime = None
    engineering_agent_facade = None
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
        # Gate 4 Structured Tool Agent：独立 runtime，不覆盖 Gate 3 agent_runtime。
        try:
            port = PipelineRetrievalAdapter(pipeline.retriever)
            tool_agent_runtime = build_tool_agent_runtime(
                repo_root=engineering_project.root,
                retrieval_port=port,
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url=DEEPSEEK_BASE_URL,
            )
            engineering_agent_facade = EngineeringAgentFacade(tool_agent_runtime)
        except Exception:
            logger.exception("Tool agent runtime init failed")
            tool_agent_runtime = None
    yield
    pipeline = None
    agent_runtime = None
    tool_agent_runtime = None
    engineering_agent_facade = None
    engineering_project = None


app = FastAPI(
    title="Evidence-Grounded AI Engineering Agent",
    description=(
        "Evidence-Grounded AI Engineering Agent with evaluable knowledge "
        "retrieval, repository evidence and bounded tool use."
    ),
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
    cited = set(result.sources)
    sources = []
    for item in (result.evidence_bundle.items if result.evidence_bundle else ()):
        if item.citation_id in cited:
            sources.append(
                AgentSourceItem(
                    citation_id=item.citation_id,
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    source=item.source_name,
                    content=item.content[:200],
                    score=item.score,
                    rank=item.rank,
                    query_id=item.query_id,
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


_TRACE_ALLOWED_KEYS = frozenset({
    "event_type",
    "iteration",
    "action_type",
    "tool_name",
    "call_id",
    "tool_status",
    "error_code",
    "iterations_used",
    "tool_calls_used",
    "tool_errors_used",
})


def _safe_trace(trace) -> list[dict]:
    """只透出 Runtime Trace 的安全字段白名单；绝不含 raw/CoT/prompt/key/
    traceback/本机敏感绝对路径。code_search 匹配行文本也不进 trace。"""
    return [
        {k: event.get(k) for k in _TRACE_ALLOWED_KEYS if k in event}
        for event in trace
    ]


def _get_tool_agent_runtime() -> ToolAgentRuntime:
    if tool_agent_runtime is None:
        raise HTTPException(
            status_code=503, detail="Tool agent runtime not initialized"
        )
    return tool_agent_runtime


def _get_engineering_agent_facade() -> EngineeringAgentFacade:
    if engineering_agent_facade is not None:
        return engineering_agent_facade
    # This fallback keeps tests and embedded callers that inject the legacy
    # runtime working without creating a second execution path.
    if tool_agent_runtime is not None:
        return EngineeringAgentFacade(tool_agent_runtime)
    raise HTTPException(
        status_code=503, detail="Engineering agent runtime not initialized"
    )


def _get_engineering_project() -> EngineeringProject:
    if engineering_project is not None:
        return engineering_project
    try:
        return resolve_engineering_project(REPO_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _build_tool_agent_response(result: ToolAgentRunResult) -> ToolAgentQueryResponse:
    return ToolAgentQueryResponse(
        schema_version="tool_agent_query_response_v1",
        status=result.status,
        answer=result.answer,
        reason_code=result.reason_code,
        failure_code=result.failure_code,
        iterations_used=result.iterations_used,
        tool_calls_used=result.tool_calls_used,
        tool_errors_used=result.tool_errors_used,
        trace=_safe_trace([event.to_dict() for event in result.trace]),
        evidence=[
            ToolAgentEvidence(
                evidence_id=item.evidence_id,
                kind=item.kind,
                path=item.path,
                start_line=item.start_line,
                end_line=item.end_line,
                snippet=item.snippet,
            )
            for item in result.evidence
            if type(item) is RuntimeEngineeringEvidence
        ],
    )


def _build_engineering_response(
    result: ToolAgentRunResult,
) -> EngineeringQueryResponse:
    evidence = []
    for item in result.evidence:
        if type(item) is RuntimeKnowledgeEvidence:
            evidence.append(
                KnowledgeEvidence(
                    evidence_id=item.evidence_id,
                    kind="knowledge",
                    source_name=item.source_name,
                    chunk_id=item.chunk_id,
                    score=item.score,
                    rank=item.rank,
                    snippet=item.snippet,
                )
            )
        elif type(item) is RuntimeEngineeringEvidence:
            evidence.append(
                ToolAgentEvidence(
                    evidence_id=item.evidence_id,
                    kind=item.kind,
                    path=item.path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    snippet=item.snippet,
                )
            )
    return EngineeringQueryResponse(
        schema_version="engineering_query_response_v1",
        status=result.status,
        answer=result.answer,
        reason_code=result.reason_code,
        failure_code=result.failure_code,
        iterations_used=result.iterations_used,
        tool_calls_used=result.tool_calls_used,
        tool_errors_used=result.tool_errors_used,
        trace=_safe_trace([event.to_dict() for event in result.trace]),
        evidence=evidence,
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


@app.get("/project", response_model=ProjectResponse)
def project() -> ProjectResponse:
    """Return only public project identity, never a local filesystem path."""
    bound_project = _get_engineering_project()
    return ProjectResponse(
        project_name=bound_project.project_name,
        source=bound_project.source,
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

    history 只传入 Agentic RAG runtime；Tool Agent 仍有独立且冻结的请求契约。
    completed/refused/deferred/failed 都返回结构化结果，deferred 不伪装成
    成功回答。Agent Runtime 未初始化时返回 503，不泄露内部异常。
    """
    rt = _get_agent_runtime()
    try:
        result = rt.run(
            req.question,
            history=tuple(message.model_dump() for message in req.history),
            top_k=req.top_k,
        )
    except Exception:
        logger.exception("Agent query failed")
        raise HTTPException(status_code=500, detail="Internal agent query error")
    return _build_agent_response(result)


@app.post("/tool-agent/query", response_model=ToolAgentQueryResponse)
def tool_agent_query(req: ToolAgentQueryRequest):
    """Gate 4 Structured Tool Agent 问答入口：Decision → Tool → Observation → Final。

    独立于 Gate 3 /agent/query。模型只见 question + ToolSpec + observations；
    history / provider / model / budget / tool allowlist 一律不被接受（extra=forbid）。
    Agent 自己的 refused / failed / budget stop / parse failure 是正常结构化系统
    结果 → HTTP 200 + status/reason/failure；只有未知基础设施异常 → HTTP 500。
    """
    rt = _get_tool_agent_runtime()
    try:
        result = rt.run(req.question)
    except Exception:
        logger.exception("Tool agent query failed")
        raise HTTPException(
            status_code=500, detail="Internal tool agent query error"
        )
    return _build_tool_agent_response(result)


@app.post("/engineering/query", response_model=EngineeringQueryResponse)
def engineering_query(req: EngineeringQueryRequest):
    """Unified product entry backed by the existing ToolAgentRuntime loop."""

    facade = _get_engineering_agent_facade()
    try:
        result = facade.run(req.question)
    except Exception:
        logger.exception("Engineering agent query failed")
        raise HTTPException(
            status_code=500, detail="Internal engineering agent query error"
        )
    return _build_engineering_response(result)


@app.get("/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    p = _get_pipeline()
    config = p.config
    return StatsResponse(
        documents_count=p.vector_store.count(),
        config=PublicConfigResponse(
            embedding_provider=config.embedding_provider,
            embedding_model=config.embedding_model,
            chunker_strategy=config.chunker_strategy,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            retriever_strategy=config.retriever_strategy,
            top_k=config.top_k,
            reranker_enabled=config.reranker_enabled,
            generator_provider=config.generator_provider,
            generator_model=config.generator_model,
        ),
    )


@app.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities() -> CapabilitiesResponse:
    """Report independent runtime availability without requiring readiness."""
    pipeline_ready = pipeline is not None
    agent_runtime_ready = agent_runtime is not None
    tool_agent_runtime_ready = tool_agent_runtime is not None
    return CapabilitiesResponse(
        schema_version="capabilities_response_v1",
        pipeline_ready=pipeline_ready,
        agent_runtime_ready=agent_runtime_ready,
        tool_agent_runtime_ready=tool_agent_runtime_ready,
        features=FeatureCapabilities(
            indexing=pipeline_ready,
            basic_rag=pipeline_ready,
            agentic_rag=agent_runtime_ready,
            structured_tool_agent=tool_agent_runtime_ready,
            engineering_agent=tool_agent_runtime_ready,
        ),
    )
