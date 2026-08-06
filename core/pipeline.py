from typing import List, Optional
import os

from core.config import Config
from core.loader.base import Document
from core.loader.text_loader import TextLoader
from core.loader.pdf_loader import PDFLoader
from core.loader.code_loader import CodeLoader
from core.chunker.base import BaseChunker
from core.chunker.fixed_size import FixedSizeChunker
from core.chunker.recursive import RecursiveChunker
from core.embeddings.base import BaseEmbedding
from core.embeddings.openai_emb import OpenAIEmbedding
from core.vector_store.base import BaseVectorStore
from core.vector_store.chroma_store import ChromaStore
from core.retriever.base import BaseRetriever
from core.retriever.simple import SimpleRetriever
from core.retriever.hybrid import HybridRetriever
from core.reranker.base import BaseReranker
from core.reranker.bge_reranker import BGEReranker
from core.generator.base import BaseGenerator
from core.generator.deepseek_gen import DeepSeekGenerator


class Pipeline:
    """串联索引和查询的完整 RAG 管线"""

    def __init__(self, config_path: str = "config.yaml",
                 deepseek_api_key: str = None,
                 openai_api_key: str = None):
        self.deepseek_api_key = deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")

        self.config = Config(config_path)

        self.embedding = self._init_embedding()
        self.vector_store = self._init_vector_store()
        self.chunker = self._init_chunker()
        self.retriever = self._init_retriever()
        self.reranker = self._init_reranker()
        self.generator = self._init_generator()

        # 从 Chroma 重建 BM25 稀疏索引
        self._rebuild_sparse_index()

        self.loader_map = {
            ".txt": TextLoader(),
            ".md": TextLoader(),
            ".pdf": PDFLoader(),
            ".py": CodeLoader(language="python"),
            ".js": CodeLoader(language="javascript"),
            ".java": CodeLoader(language="java"),
        }                                               

    def _init_embedding(self) -> BaseEmbedding:
        if self.config.embedding_provider == "openai":
            return OpenAIEmbedding(
                model=self.config.embedding_model,
                api_key=self.openai_api_key,
            )
        from core.embeddings.bge_emb import BGEEmbedding
        return BGEEmbedding(model_name=self.config.embedding_model)

    def _init_vector_store(self) -> BaseVectorStore:
        return ChromaStore(path=self.config.vector_store_path)

    def _init_chunker(self) -> BaseChunker:
        if self.config.chunker_strategy == "fixed":
            return FixedSizeChunker(
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
            )
        elif self.config.chunker_strategy == "semantic":
            from core.chunker.semantic import SemanticChunker
            return SemanticChunker(embedding_fn=self.embedding.embed)
        return RecursiveChunker(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )

    def _init_retriever(self) -> BaseRetriever:
        if self.config.retriever_strategy == "simple":
            return SimpleRetriever(self.embedding, self.vector_store)
        elif self.config.retriever_strategy == "hybrid":
            return HybridRetriever(
                self.embedding, self.vector_store,
                dense_candidate_k=self.config.dense_candidate_k,
                sparse_candidate_k=self.config.sparse_candidate_k,
                final_k=self.config.top_k,
                rrf_k=self.config.rrf_k,
            )
        from core.retriever.mmr import MMRRetriever
        return MMRRetriever(self.embedding, self.vector_store)

    def _init_reranker(self) -> BaseReranker:
        return BGEReranker()

    def _init_generator(self) -> BaseGenerator:
        if self.config.generator_provider == "deepseek":
            return DeepSeekGenerator(
                api_key=self.deepseek_api_key or "",
                model=self.config.generator_model,
                temperature=self.config.generator_temperature,
            )
        from core.generator.openai_gen import OpenAIGenerator
        return OpenAIGenerator(
            api_key=self.openai_api_key or "",
            model=self.config.generator_model,
            temperature=self.config.generator_temperature,
        )

    def _get_loader(self, file_path: str):
        ext = os.path.splitext(file_path)[1].lower()
        loader = self.loader_map.get(ext)
        if loader is None:
            loader = TextLoader()
        return loader

    def index_file(self, file_path: str) -> dict:
        """幂等入库：相同文件 no_change，内容变更 update，新文件 create"""
        from core.domain.models import compute_content_hash, make_document_id

        source_name = os.path.basename(file_path)
        document_id = make_document_id(source_name)

        loader = self._get_loader(file_path)
        docs = loader.load(file_path)
        full_text = "".join(d.content for d in docs)
        content_hash = compute_content_hash(full_text)

        # decide：查是否已入库
        existing = self.vector_store.get_by_document_id(document_id)

        if existing:
            old_hash = existing[0]["metadata"].get("content_hash", "")
            if old_hash == content_hash:
                return {
                    "status": "no_change",
                    "document_id": document_id,
                    "chunks": 0,
                }

        old_ids = [c["id"] for c in existing] if existing else []

        # 分块 → embedding → 入库（先写新版本）
        chunks = self.chunker.chunk(docs)
        texts = [d.content for d in chunks]
        embeddings = self.embedding.embed(texts)

        for c in chunks:
            c.metadata["document_id"] = document_id
            c.metadata["content_hash"] = content_hash

        # upsert 而非 add：内容重复产生相同 chunk_id 时幂等处理
        ids = self.vector_store.upsert(chunks, embeddings)

        # 写入成功后，删除旧版本中未被新版本覆盖的 chunk（先写后删，中途失败不丢数据）
        if old_ids:
            new_ids = set(ids)
            stale = [oid for oid in old_ids if oid not in new_ids]
            if stale:
                self.vector_store.delete(stale)
                if hasattr(self.retriever, "_bm25"):
                    for cid in stale:
                        self.retriever._bm25.remove_document(cid)

        # 同步 BM25 稀疏索引：用 chunk 元数据 id 配对（upsert 去重后 zip 会错位）；
        # 传完整元数据（BM25 内部 dict() 复制），Sparse-only 命中可恢复来源
        if hasattr(self.retriever, "build_sparse_index"):
            self.retriever.build_sparse_index(
                [(c.metadata["id"], c.content, c.metadata) for c in chunks]
            )

        return {
            "status": "update" if existing else "create",
            "document_id": document_id,
            "chunks": len(chunks),
        }

    def query(self, question: str, top_k: int = None, history: list = None) -> dict:
        """查询：检索 → 重排序 → 上下文组装 → 生成 → 引用验证"""
        from core.context.assembler import ContextAssembler
        from core.generator.citation import CitationValidator

        k = top_k or self.config.top_k
        final_k = self.config.reranker_final_k or k
        candidate_k = self.config.reranker_candidate_k or max(self.config.top_k * 3, k * 3)

        # 多轮改写：指代问题 → 独立问句
        if history:
            from core.query_rewriter import QueryRewriter
            question = QueryRewriter().rewrite(history, question)

        retrieved = self.retriever.retrieve(question, top_k=candidate_k)

        # Reranker 失败时降级为检索结果，不中断请求
        if self.config.reranker_enabled:
            try:
                retrieved = self.reranker.rerank(question, retrieved, top_k=final_k)
            except Exception as e:
                import warnings
                warnings.warn(f"Reranker 失败，使用检索结果: {type(e).__name__}")

        # 语义：请求 top_k 是最终答案数上限；reranker 关闭时也严格截断
        retrieved = retrieved[:k]

        # ── 无答案拒答（M3-T4 基础版） ────────────────
        if not retrieved:
            return {
                "answer": "现有资料中没有找到与问题相关的信息。",
                "sources": [],
                "citation_validation": {"valid_count": 0, "invalid_count": 0,
                                        "validity_rate": 1.0, "invalid_ids": []},
            }

        if self.config.min_score > 0.0:
            top_score = max(
                (d.metadata.get("score", 0.0) for d in retrieved),
                default=0.0,
            )
            if top_score < self.config.min_score:
                return {
                    "answer": "现有资料不足，无法可靠回答该问题。",
                    "sources": [],
                    "citation_validation": {"valid_count": 0, "invalid_count": 0,
                                            "validity_rate": 1.0, "invalid_ids": []},
                }

        # 上下文组装（去重 + token 预算 + 引用编号）
        assembler = ContextAssembler()
        blocks = assembler.assemble(retrieved)

        answer = self.generator.generate(question, [b for b in blocks])

        # 引用验证：答案中的 [Cx] 必须存在于本次 Context
        validator = CitationValidator()
        validation = validator.validate(answer, blocks)

        sources = [
            {
                "content": b.content[:200],
                "source": b.source_name,
                "score": b.retrieval_scores.get("score", 0.0),
                "citation_id": b.citation_id,
            }
            for b in blocks
        ]

        return {
            "answer": answer,
            "sources": sources,
            "citation_validation": {
                "valid_count": len(validation.valid),
                "invalid_count": len(validation.invalid),
                "validity_rate": validation.validity_rate,
                "invalid_ids": [c.citation_id for c in validation.invalid],
            },
        }

    def _rebuild_sparse_index(self, strict: bool = False) -> int:
        """从 Chroma 全量重建 BM25 稀疏索引，返回实际重建的文档数。

        strict=True（评测场景）：读取/构建异常、BM25 为空或文档数与
        可索引 chunk 数不一致时抛异常，避免 Hybrid 评测静默退化为
        Dense-only 产生失真结果。普通 Pipeline 启动保持默认容错。
        """
        if not hasattr(self.retriever, "build_sparse_index"):
            return 0
        try:
            all_data = self.vector_store.collection.get(
                include=["documents", "metadatas"]
            )
            pairs = [
                (
                    all_data["metadatas"][i].get("id", ""),
                    all_data["documents"][i],
                    all_data["metadatas"][i],
                )
                for i in range(len(all_data["ids"]))
                if all_data["metadatas"][i].get("id")
            ]
            if pairs:
                self.retriever.build_sparse_index(pairs)
        except Exception as exc:
            if strict:
                raise RuntimeError(
                    f"Hybrid 评测已终止：BM25 稀疏索引重建失败（{exc}），"
                    "不能生成失真结果"
                )
            return 0
        if strict:
            built = getattr(getattr(self.retriever, "_bm25", None), "doc_count", 0)
            if len(all_data["ids"]) > 0 and built == 0:
                raise RuntimeError(
                    "Hybrid 评测已终止：向量库有数据但 BM25 文档数为 0，"
                    "不能生成失真结果"
                )
            if built != len(pairs):
                raise RuntimeError(
                    f"Hybrid 评测已终止：BM25 文档数 {built} 与可索引 "
                    f"chunk 数 {len(pairs)} 不一致，不能生成失真结果"
                )
        return len(pairs)

    def delete_document(self, document_id: str) -> int:
        """删除文档：向量库 + BM25 同步清理"""
        chunks = self.vector_store.get_by_document_id(document_id)
        if hasattr(self.retriever, "_bm25"):
            for c in chunks:
                self.retriever._bm25.remove_document(c["id"])
        try:
            self.vector_store.delete_by_document_id(document_id)
        except Exception:
            pass
        return self.vector_store.count()
