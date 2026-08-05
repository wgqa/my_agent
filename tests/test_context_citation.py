"""M3-T1 + M3-T3: ContextAssembler 与引用验证"""

from core.loader.base import Document
from core.context.assembler import ContextAssembler, ContextBlock
from core.generator.citation import CitationValidator
from core.chunker.token_counter import TokenCounter


def _hits():
    return [
        Document(content="缓存穿透是指查询不存在的数据", metadata={
            "id": "chunk_1", "source": "redis.md", "source_name": "redis.md",
            "score": 0.9, "rank": 1,
        }),
        Document(content="缓存击穿是指热点key失效", metadata={
            "id": "chunk_2", "source": "redis.md", "source_name": "redis.md",
            "score": 0.8, "rank": 2,
        }),
        Document(content="JVM类加载机制", metadata={
            "id": "chunk_3", "source": "jvm.md", "source_name": "jvm.md",
            "score": 0.3, "rank": 3,
        }),
    ]


class TestContextAssembler:
    def test_assigns_citation_ids_in_order(self):
        blocks = ContextAssembler().assemble(_hits())
        assert [b.citation_id for b in blocks] == ["[C1]", "[C2]", "[C3]"]

    def test_dedup_same_content(self):
        hits = [
            Document(content="相同内容", metadata={"score": 0.9, "id": "a"}),
            Document(content="相同内容", metadata={"score": 0.8, "id": "b"}),
            Document(content="不同内容", metadata={"score": 0.7, "id": "c"}),
        ]
        blocks = ContextAssembler().assemble(hits)
        assert len(blocks) == 2
        assert blocks[0].content == "相同内容"

    def test_sorts_by_score_desc(self):
        hits = [
            Document(content="低分", metadata={"score": 0.3, "id": "a"}),
            Document(content="高分", metadata={"score": 0.9, "id": "b"}),
        ]
        blocks = ContextAssembler().assemble(hits)
        assert blocks[0].content == "高分"

    def test_sorts_by_rerank_score_when_present(self):
        # 有 rerank_score 时按它排，不能被稠密 score 覆盖
        hits = [
            Document(content="A", metadata={"id": "a", "score": 0.9, "rerank_score": 0.2}),
            Document(content="B", metadata={"id": "b", "score": 0.1, "rerank_score": 0.8}),
        ]
        blocks = ContextAssembler().assemble(hits)
        assert blocks[0].content == "B"
        assert blocks[0].retrieval_scores["score"] == 0.8

    def test_token_budget_truncation(self):
        hits = [
            Document(content="a" * 100, metadata={"score": 0.9, "id": "a"}),
            Document(content="b" * 100, metadata={"score": 0.8, "id": "b"}),
            Document(content="c" * 100, metadata={"score": 0.7, "id": "c"}),
        ]
        blocks = ContextAssembler(max_context_tokens=150).assemble(hits)
        total = sum(b.token_count for b in blocks)
        assert total <= 150

    def test_doc_share_limit(self):
        long_a = "Redis 缓存穿透的解决方案是布隆过滤器。" * 10
        long_b = "Redis 缓存击穿的解决方案是互斥锁。" * 10
        long_c = "JVM 类加载机制包括加载验证准备解析初始化。" * 10
        hits = [
            Document(content=long_a, metadata={"score": 0.9, "id": "a", "source_name": "doc1"}),
            Document(content=long_b, metadata={"score": 0.8, "id": "b", "source_name": "doc1"}),
            Document(content=long_c, metadata={"score": 0.7, "id": "c", "source_name": "doc2"}),
        ]
        assembler = ContextAssembler(max_context_tokens=200, max_doc_ratio=0.4)
        blocks = assembler.assemble(hits)
        # doc1 上限 80 token → 只保留 1 块
        doc1_blocks = [b for b in blocks if b.source_name == "doc1"]
        assert len(doc1_blocks) == 1


class TestCitationValidator:
    def test_valid_citations(self):
        blocks = [
            ContextBlock(citation_id="[C1]", chunk_id="c1", source_name="a.md",
                         page_number=None, content="内容1", token_count=5),
            ContextBlock(citation_id="[C2]", chunk_id="c2", source_name="b.md",
                         page_number=None, content="内容2", token_count=5),
        ]
        answer = "缓存穿透是……[C1]，击穿是……[C2]"
        result = CitationValidator().validate(answer, blocks)
        assert len(result.valid) == 2
        assert len(result.invalid) == 0
        assert result.validity_rate == 1.0

    def test_invalid_citation(self):
        blocks = [
            ContextBlock(citation_id="[C1]", chunk_id="c1", source_name="a.md",
                         page_number=None, content="内容", token_count=5),
        ]
        answer = "引用不存在的块[C9]"
        result = CitationValidator().validate(answer, blocks)
        assert len(result.valid) == 0
        assert len(result.invalid) == 1
        assert result.invalid[0].citation_id == "[C9]"
        assert result.validity_rate == 0.0

    def test_mixed_citations(self):
        blocks = [
            ContextBlock(citation_id="[C1]", chunk_id="c1", source_name="a.md",
                         page_number=None, content="内容", token_count=5),
        ]
        answer = "正确引用[C1]和错误引用[C5]"
        result = CitationValidator().validate(answer, blocks)
        assert len(result.valid) == 1
        assert len(result.invalid) == 1
        assert result.validity_rate == 0.5

    def test_no_citation(self):
        result = CitationValidator().validate("没有引用的答案", [])
        assert len(result.valid) == 0
        assert result.validity_rate == 1.0


class Char3TokenCounter(TokenCounter):
    """每字符 3 token 的确定性计数器"""

    def __init__(self):
        self._enc = None

    def count(self, text):
        return len(text) * 3


def test_assembler_strict_budget_no_oversize():
    """预算 1、单字符 3 token：连一个完整字符都放不下时输出为空，总 token <= 1"""
    from core.loader.base import Document
    hits = [Document(content="缓存", metadata={"id": "c1", "source": "a.md",
                                              "source_name": "a.md", "score": 0.9})]
    assembler = ContextAssembler(max_context_tokens=1, token_counter=Char3TokenCounter())
    blocks = assembler.assemble(hits)
    assert blocks == [] or sum(b.token_count for b in blocks) <= 1


def test_assembler_skips_oversized_block_then_keeps_smaller():
    """预算 1（真实 tiktoken）："缓"=3 token 放不下时跳过，后续 "a"=1 token 仍进入上下文"""
    from core.loader.base import Document
    hits = [
        Document(content="缓", metadata={"id": "c1", "source": "a.md",
                                        "source_name": "a.md", "score": 0.9}),
        Document(content="a", metadata={"id": "c2", "source": "b.md",
                                        "source_name": "b.md", "score": 0.8}),
    ]
    assembler = ContextAssembler(max_context_tokens=1)  # 真实 TokenCounter
    blocks = assembler.assemble(hits)
    assert [b.content for b in blocks] == ["a"]
    assert sum(b.token_count for b in blocks) <= 1
