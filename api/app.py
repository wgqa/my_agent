import os
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.pipeline import Pipeline
from api.schemas import (
    QueryRequest,
    QueryResponse,
    SourceItem,
    IndexResponse,
    HealthResponse,
)

pipeline: Optional[Pipeline] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    try:
        pipeline = Pipeline(
            config_path="config.yaml",
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )
    except Exception as e:
        print(f"[WARN] Pipeline init failed (will retry on first request): {e}")
        pipeline = None
    yield
    pipeline = None


app = FastAPI(
    title="RAG Knowledge Base API",
    description="Local RAG system: index documents and ask questions",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_pipeline() -> Pipeline:
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    return pipeline


@app.get("/health", response_model=HealthResponse)
def health():
    p = _get_pipeline()
    return HealthResponse(
        docs_count=p.vector_store.count(),
        embedding_provider=p.config.embedding_provider,
        retriever_strategy=p.config.retriever_strategy,
        generator_provider=p.config.generator_provider,
    )


@app.post("/index/file", response_model=IndexResponse)
def index_file(file: UploadFile = File(...)):
    p = _get_pipeline()

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    suffix = os.path.splitext(file.filename)[1].lower()
    if suffix not in (".txt", ".md", ".pdf", ".py", ".js", ".java"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: .txt, .md, .pdf, .py, .js, .java",
        )

    tmp_path = os.path.join(tempfile.gettempdir(), f"rag_{file.filename}")
    try:
        content = file.file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)
        chunks = p.index_file(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return IndexResponse(file_name=file.filename, chunks=chunks)


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    p = _get_pipeline()

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        result = p.query(req.question, top_k=req.top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

    sources = [
        SourceItem(
            content=s["content"],
            source=s["source"],
            score=s["score"],
        )
        for s in result["sources"]
    ]

    return QueryResponse(answer=result["answer"], sources=sources)


@app.get("/stats")
def stats():
    p = _get_pipeline()
    return {
        "documents_count": p.vector_store.count(),
        "config": p.config,
    }
