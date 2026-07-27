"""
Day 4 实验：三种检索策略对比（Simple vs MMR vs Hybrid）

目的：直观感受三种检索器在同一个查询下的行为差异
- Simple: 纯向量相似度，可能结果高度重复
- MMR: 在相关性和多样性之间平衡
- Hybrid: 稠密向量 + BM25 关键词互补

注意：本实验使用 Mock 数据，仅演示算法行为差异。
完整实验在 Day 6 评估阶段用真实数据重新跑。
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.loader.base import Document
from core.retriever.simple import SimpleRetriever
from core.retriever.mmr import MMRRetriever
from core.retriever.hybrid import HybridRetriever, BM25


# ========== Mock 组件（模拟 embedding 和向量库） ==========

class MockEmbedding:
    """模拟 embedding 模型：把文本映射到固定维度的向量"""
    def embed(self, texts):
        import hashlib
        result = []
        for t in texts:
            # 用 hash 生成一个确定性向量（同一个文本得到相同向量）
            h = hashlib.md5(t.encode()).hexdigest()
            vec = [int(h[i:i+2], 16) / 255.0 for i in range(0, 10, 2)]
            result.append(vec)
        return result

    def embed_query(self, text):
        return self.embed([text])[0]


def make_docs():
    """构建一个包含多个主题的测试文档集"""
    return [
        Document(content="Python is a programming language for AI and data science", metadata={"topic": "python"}),
        Document(content="Java is a programming language for enterprise applications", metadata={"topic": "java"}),
        Document(content="Machine learning uses algorithms to learn from data", metadata={"topic": "ml"}),
        Document(content="Deep learning is a subset of machine learning using neural networks", metadata={"topic": "dl"}),
        Document(content="Natural language processing enables computers to understand text", metadata={"topic": "nlp"}),
        Document(content="Transformers are a type of neural network architecture for NLP", metadata={"topic": "transformer"}),
        Document(content="Python has many libraries for data science like numpy and pandas", metadata={"topic": "python"}),
        Document(content="Spring Boot is a popular Java framework for microservices", metadata={"topic": "java"}),
    ]


class MockVectorStore:
    """模拟向量库：用余弦相似度做检索"""
    def __init__(self, docs):
        self.docs = docs

    def search(self, query_emb, top_k=5):
        import numpy as np
        scores = []
        for d in self.docs:
            doc_emb = MockEmbedding().embed([d.content])[0]
            sim = np.dot(query_emb, doc_emb) / (np.linalg.norm(query_emb) * np.linalg.norm(doc_emb) + 1e-10)
            scores.append(sim)
        # 按相似度降序排列
        scored = sorted(zip(scores, self.docs), key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]


def main():
    print("=" * 60)
    print("Day 4 实验：三种检索策略对比")
    print("=" * 60)

    embedding = MockEmbedding()
    docs = make_docs()
    vector_store = MockVectorStore(docs)

    # 三种检索器
    retrievers = {
        "Simple (纯向量)": SimpleRetriever(embedding, vector_store),
        "MMR (λ=0.5)": MMRRetriever(embedding, vector_store, lambda_param=0.5, top_k_initial=20),
        "Hybrid (α=0.5)": HybridRetriever(embedding, vector_store, alpha=0.5, top_k_initial=20),
    }

    queries = [
        "programming language",
        "machine learning and AI",
        "neural networks",
    ]

    for query in queries:
        print(f"\n{'─' * 50}")
        print(f"查询: 「{query}」")
        print('─' * 50)

        for name, retriever in retrievers.items():
            results = retriever.retrieve(query, top_k=4)
            print(f"\n  [{name}]")
            for i, doc in enumerate(results):
                print(f"    {i+1}. {doc.content[:80]}...")

    # 额外演示：BM25 从零实现的效果
    print(f"\n{'=' * 60}")
    print("BM25 示例：关键词匹配 vs 语义匹配")
    print('=' * 60)

    bm25 = BM25()
    corpus = [
        "the cat sat on the mat",
        "the dog chased the cat through the park",
        "the cat and the dog are friends",
        "machine learning is transforming technology",
    ]
    bm25.fit(corpus)

    test_queries = ["cat dog", "machine learning"]
    for q in test_queries:
        print(f"\n查询: 「{q}」")
        for i in range(len(corpus)):
            score = bm25.score(q, i)
            print(f"  文档{i+1}: {corpus[i][:50]:50s} BM25={score:.4f}")


if __name__ == "__main__":
    main()
