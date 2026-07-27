"""三种分块策略的对比实验"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.loader.base import Document
from core.chunker.fixed_size import FixedSizeChunker
from core.chunker.recursive import RecursiveChunker
from core.chunker.semantic import SemanticChunker

# 每个"词"用空格隔开，让 FixedSize 能按词数切分
test_text = (
    "深度学习是机器学习的一个分支 "
    "它通过多层神经网络来学习数据的层次化表示 "
    "卷积神经网络在图像领域取得了巨大成功 "
    "循环神经网络则擅长处理序列数据 "
    "近年来大语言模型成为了AI领域的热点 "
    "GPT系列模型展示了惊人的文本生成能力 "
    "BERT则在自然语言理解任务上表现出色 "
    "RAG检索增强生成是一种结合检索和生成的技术 "
    "它先从知识库中检索相关文档 "
    "然后把检索结果作为上下文辅助LLM生成答案 "
    "分块策略的选择对RAG效果影响很大 "
    "分块太小会导致上下文不完整 "
    "太大又会包含噪声 "
    "合适的overlap可以缓解信息断裂的问题 "
)
# 注意：这不是真实的 RAG 场景，只是为了演示分块效果

doc = Document(content=test_text.strip(), metadata={"source": "test.txt"})

print("=" * 60)
print("原始文档词数:", len(test_text.split()), "个词")
print("=" * 60)

# 1. FixedSizeChunker
chunker_fixed = FixedSizeChunker(chunk_size=5, chunk_overlap=1)
result_fixed = chunker_fixed.chunk([doc])
print("\n【FixedSizeChunker】chunk_size=5词, overlap=1词")
print(f"生成 {len(result_fixed)} 个块：")
for i, c in enumerate(result_fixed):
    print(f"  块{i}: [{len(c.content)}字] {c.content}")

# 2. RecursiveChunker
chunker_recursive = RecursiveChunker(chunk_size=30, chunk_overlap=5)
result_recursive = chunker_recursive.chunk([doc])
print(f"\n【RecursiveChunker】chunk_size=30字, overlap=5字")
print(f"生成 {len(result_recursive)} 个块：")
for i, c in enumerate(result_recursive):
    print(f"  块{i}: [{len(c.content)}字] {c.content}")

# 3. SemanticChunker（没有 embedding 时降级为 Recursive）
chunker_semantic = SemanticChunker()
result_semantic = chunker_semantic.chunk([doc])
print(f"\n【SemanticChunker】未传入embedding，降级为 Recursive")
print(f"生成 {len(result_semantic)} 个块：")
for i, c in enumerate(result_semantic):
    print(f"  块{i}: [{len(c.content)}字] {c.content}")

print("\n" + "=" * 60)
print("观察要点：")
print("1. FixedSize 的块大小基本一致，但可能在句子中间切断")
print("2. Recursive 保留语义边界，块大小不一致")
print("3. 真正 Semantic 需要 embedding，这里做降级演示")
