from typing import List, Optional
import os
import yaml

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
                 openai_api_key: str = None):       #定义传入参数
        self.deepseek_api_key = deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")

        self.config = {}                    
        if config_path and os.path.exists(config_path):
            with open(config_path, "r") as f:
                self.config = yaml.safe_load(f) or {}       

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
        cfg = self.config.get("embedding", {})
        provider = cfg.get("provider", "openai")        
        if provider == "openai":
            return OpenAIEmbedding(
                model=cfg.get("model", "text-embedding-3-small"),
                api_key=self.openai_api_key,
            )
        from core.embeddings.bge_emb import BGEEmbedding
        return BGEEmbedding(model_name=cfg.get("model", "BAAI/bge-small-zh-v1.5"))

    def _init_vector_store(self) -> BaseVectorStore:        
        path = self.config.get("vector_store", {}).get("path", "./data/vector_store")
        return ChromaStore(path=path)

    def _init_chunker(self) -> BaseChunker:
        cfg = self.config.get("chunker", {})
        strategy = cfg.get("strategy", "recursive")
        chunk_size = cfg.get("size_tokens") or cfg.get("chunk_size", 512)
        chunk_overlap = cfg.get("overlap_tokens") or cfg.get("chunk_overlap", 64)

        if strategy == "fixed":
            return FixedSizeChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        elif strategy == "semantic":
            from core.chunker.semantic import SemanticChunker
            return SemanticChunker(embedding_fn=self.embedding.embed)
        return RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def _init_retriever(self) -> BaseRetriever:
        cfg = self.config.get("retriever", {})
        strategy = cfg.get("strategy", "hybrid")
        top_k = cfg.get("top_k", 5)

        if strategy == "simple":
            return SimpleRetriever(self.embedding, self.vector_store)
        elif strategy == "hybrid":
            return HybridRetriever(
                self.embedding, self.vector_store,
                dense_candidate_k=cfg.get("dense_candidate_k", 30),
                sparse_candidate_k=cfg.get("sparse_candidate_k", 30),
                final_k=cfg.get("final_k", 20),
                rrf_k=cfg.get("rrf_k", 60.0),
            )
        from core.retriever.mmr import MMRRetriever
        return MMRRetriever(self.embedding, self.vector_store)

    def _init_reranker(self) -> BaseReranker:
        return BGEReranker()

    def _init_generator(self) -> BaseGenerator:
        cfg = self.config.get("generator", {})
        provider = cfg.get("provider", "deepseek")
        model = cfg.get("model", "deepseek-v4-flash")
        temperature = cfg.get("temperature", 0.3)

        if provider == "deepseek":
            return DeepSeekGenerator(
                api_key=self.deepseek_api_key or "",
                model=model,
                temperature=temperature,
            )
        from core.generator.openai_gen import OpenAIGenerator
        return OpenAIGenerator(
            api_key=self.openai_api_key or "",
            model=model,
            temperature=temperature,
        )

    def _get_loader(self, file_path: str):
        ext = os.path.splitext(file_path)[1].lower()
        loader = self.loader_map.get(ext)
        if loader is None:
            loader = TextLoader()
        return loader

    def index_file(self, file_path: str) -> int:        
        """索引文件：加载 → 分块 → embedding → 存储，返回 chunk 数量"""
        loader = self._get_loader(file_path)       
        docs = loader.load(file_path)
        chunks = self.chunker.chunk(docs)
        texts = [d.content for d in chunks]
        embeddings = self.embedding.embed(texts)
        ids = self.vector_store.add(chunks, embeddings)

        # 同步更新 BM25 稀疏索引
        if hasattr(self.retriever, "build_sparse_index"):
            self.retriever.build_sparse_index(zip(ids, texts))

        return len(chunks)

    def query(self, question: str, top_k: int = None) -> dict:
        """查询：检索 → 重排序 → 生成，返回答案和来源"""
        k = top_k or self.config.get("retriever", {}).get("top_k", 5)
        candidate_k = self.config.get("retriever", {}).get("candidate_k", k * 3)

        retrieved = self.retriever.retrieve(question, top_k=candidate_k)
        retrieved = self.reranker.rerank(question, retrieved, top_k=k)

        answer = self.generator.generate(question, retrieved)

        sources = [
            {
                "content": d.content[:200],
                "source": d.metadata.get("source", "unknown"),
                "score": d.metadata.get("score", d.metadata.get("rrf_score", 0.0)),
            }
            for d in retrieved
        ]

        return {"answer": answer, "sources": sources}

    def _rebuild_sparse_index(self):
        """从 Chroma 全量重建 BM25 稀疏索引"""
        if not hasattr(self.retriever, "build_sparse_index"):
            return
        try:
            all_data = self.vector_store.collection.get(
                include=["documents", "metadatas"]
            )
            pairs = [
                (all_data["metadatas"][i].get("id", ""), all_data["documents"][i])
                for i in range(len(all_data["ids"]))
                if all_data["metadatas"][i].get("id")
            ]
            if pairs:
                self.retriever.build_sparse_index(pairs)
        except Exception:
            pass

    def delete_document(self, document_id: str) -> int:
        """删除文档"""
        try:
            self.vector_store.delete_by_document_id(document_id)
        except Exception:
            pass
        return self.vector_store.count()
