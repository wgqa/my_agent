"""Embedding 模型对比实验

前置条件：
  export DEEPSEEK_API_KEY=sk-xxx   # 用于 LLM 生成（可选）
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# 准备测试文档
from core.loader.base import Document
from core.loader.text_loader import TextLoader
from core.chunker.recursive import RecursiveChunker

test_docs = [
    Document(content="深度学习是机器学习的一个分支，它通过多层神经网络来学习数据的层次化表示。", metadata={"id": "doc1"}),
    Document(content="卷积神经网络在图像识别领域取得了巨大成功，特别是在分类和目标检测任务上。", metadata={"id": "doc2"}),
    Document(content="循环神经网络擅长处理序列数据，如文本和时间序列预测。", metadata={"id": "doc3"}),
    Document(content="Python 是一种广泛使用的编程语言，在人工智能和数据科学领域尤为流行。", metadata={"id": "doc4"}),
    Document(content="向量数据库用于存储和检索高维向量，在 RAG 系统中扮演重要角色。", metadata={"id": "doc5"}),
]

# 1. 理论对比：不同 embedding 模型的特征
print("=" * 60)
print("Embedding 模型对比")
print("=" * 60)

comparison = """
| 特性 | OpenAI text-embedding-3-small | BAAI/bge-small-zh-v1.5 |
|------|------------------------------|------------------------|
| 维度 | 1536 | 512 |
| 运行方式 | API 调用（需联网+付费） | 本地加载（免费离线） |
| 中文支持 | 优秀 | 优秀（专为中优化） |
| 首次延迟 | ~200ms（API 传输） | ~3s（加载模型） |
| 批量成本 | $0.02/1K tokens | 0 |
| 隐私 | 数据经 API 传输 | 完全本地 |
"""
print(comparison)

# 2. 如果只想看效果差异，比较不同维度对检索的影响
# 注：以下为模拟计算，展示 embedding 维度和相似度计算的关系
import math
import numpy as np

print("\n【维度对检索的影响（模拟）】")
for dims in [64, 128, 256, 512, 768, 1536]:
    # 随机生成两个相关向量和两个不相关向量
    np.random.seed(42)
    a = np.random.randn(dims)
    b = a * 0.9 + np.random.randn(dims) * 0.1  # 与 a 高度相关
    c = np.random.randn(dims)  # 与 a 无关

    sim_rel = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    sim_unr = np.dot(a, c) / (np.linalg.norm(a) * np.linalg.norm(c))
    print(f"  维度 {dims:5d}: 相关向量相似度 {sim_rel:.4f}, 不相关向量相似度 {sim_unr:.4f}, 区分度 {sim_rel-sim_unr:.4f}")

print("""
观察结论：
- 维度越高，向量越稀疏，相关/不相关的区分度通常更好（但也不是越高越好）
- 1536 维比 512 维需要 3x 存储和计算量
- 中文场景 BGE 和 OpenAI 效果接近，BGE 免费但有加载和推理成本
""")

# 3. 提供 OpenAI Embedding 测试代码（用户有 API key 时执行）
api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    from core.embeddings.openai_emb import OpenAIEmbedding
    emb = OpenAIEmbedding(api_key=api_key)
    vectors = emb.embed([d.content for d in test_docs])
    print(f"\nOpenAI Embedding 测试：")
    print(f"  文档数: {len(vectors)}, 向量维度: {len(vectors[0])}")
    print(f"  第1个向量前5维: {vectors[0][:5]}")
else:
    print("\n未设置 OPENAI_API_KEY，跳过实际 API 调用。")
    print("设置后运行: export OPENAI_API_KEY=sk-xxx && python experiments/compare_embeddings.py")
