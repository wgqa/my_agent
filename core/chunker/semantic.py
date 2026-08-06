from typing import List, Optional, Tuple
import numpy as np

from core.loader.base import Document
from core.chunker.base import BaseChunker
from core.chunker.token_counter import TokenCounter


class SemanticChunker(BaseChunker):
    """基于句子 Embedding 相似度变化进行语义分割的实验性实现。

    ⚠️ EXPERIMENTAL（G1-CHUNK-05B）：当前是实验性实现，保留手动学习与
    调试入口，但不得用于正式 Gate 2 基线报告。已知限制：
    - 原文 Span 不可靠（会改变原始空白，非精确保持）；
    - 严格预算不可靠（长句使用 token decode 切分，可能切半字符/边界漂移）；
    - 切片与 Embedding 下标存在错位风险。
    正式实验请使用 fixed / recursive（ExperimentConfig 已拒绝 semantic）。
    """

    def __init__(
        self,
        embedding_fn=None,
        threshold: float = 0.7,
        min_chunk_len: int = 50,
        max_chunk_len: int = 1000,
        token_counter: TokenCounter | None = None,
    ):
        self.embedding_fn = embedding_fn
        self.threshold = threshold
        self.min_chunk_len = min_chunk_len
        self.max_chunk_len = max_chunk_len
        self._counter = token_counter or TokenCounter()

    def _split_sentences(self, text: str) -> List[str]:
        import re
        sentences = re.split(r"(?<=[。！？.!?])\s*", text)
        return [s.strip() for s in sentences if s.strip()]

    def chunk(self, documents: List[Document]) -> List[Document]:
        if self.embedding_fn is None:
            from core.chunker.recursive import RecursiveChunker
            return RecursiveChunker(token_counter=self._counter).chunk(documents)

        chunked = []
        for doc in documents:
            sentences = self._split_sentences(doc.content)
            if len(sentences) <= 1:
                chunked.append(Document(
                    content=doc.content,
                    metadata={**doc.metadata, "chunk_index": 0, "token_count": self._counter.count(doc.content)}
                ))
                continue

            # batch embedding 失败时降级为 Recursive，并记录 warning
            try:
                embeddings = self.embedding_fn(sentences)
            except Exception as e:
                import warnings
                warnings.warn(
                    f"SemanticChunker embedding 失败，降级 Recursive: {type(e).__name__}"
                )
                from core.chunker.recursive import RecursiveChunker
                return RecursiveChunker(
                    chunk_size=self.max_chunk_len,
                    token_counter=self._counter,
                ).chunk(documents)

            groups = self._group_sentences(sentences, embeddings)

            for i, group in enumerate(groups):
                text = "".join(group)
                chunked.append(Document(
                    content=text,
                    metadata={**doc.metadata, "chunk_index": i, "token_count": self._counter.count(text)}
                ))
        return chunked

    def _group_sentences(
        self, sentences: List[str], embeddings: List[List[float]]
    ) -> List[List[str]]:
        """语义分组 + min/max 长度约束 + 超长单句兜底硬切"""
        # 超长单句先按 token 硬切，防止产出超上限 chunk
        safe_sentences: List[str] = []
        for s in sentences:
            n = self._counter.count(s)
            if n > self.max_chunk_len:
                tokens = self._counter.encode(s)
                for t in range(0, len(tokens), self.max_chunk_len):
                    seg = self._counter.decode(tokens[t:t + self.max_chunk_len])
                    if seg:
                        safe_sentences.append(seg)
            else:
                safe_sentences.append(s)

        if not safe_sentences:
            return []
        if len(safe_sentences) == 1:
            return [safe_sentences]

        groups = [[safe_sentences[0]]]
        for i in range(1, len(safe_sentences)):
            last_group_text = "".join(groups[-1])
            if self._counter.count(last_group_text) >= self.max_chunk_len:
                groups.append([])
                groups[-1].append(safe_sentences[i])
                continue

            # 硬切后的子句没有语义 embedding，直接追加
            sim = self._cosine_sim(embeddings[i - 1], embeddings[i]) if i < len(embeddings) else 1.0
            if sim < self.threshold:
                if self._counter.count(last_group_text) < self.min_chunk_len:
                    groups[-1].append(safe_sentences[i])
                else:
                    groups.append([])
                    groups[-1].append(safe_sentences[i])
            else:
                groups[-1].append(safe_sentences[i])

        merged = [groups[0]]
        for g in groups[1:]:
            g_text = "".join(g)
            merged_last_text = "".join(merged[-1])
            if self._counter.count(merged_last_text) < self.min_chunk_len:
                merged[-1].extend(g)
            elif self._counter.count(g_text) < self.min_chunk_len:
                merged[-1].extend(g)
            else:
                merged.append(g)

        return merged

    def _cosine_sim(self, a: List[float], b: List[float]) -> float:
        a_arr = np.array(a)
        b_arr = np.array(b)
        return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr) + 1e-10))
