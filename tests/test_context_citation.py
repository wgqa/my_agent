"""M3-T1 + M3-T3: ContextAssembler 与引用验证"""

from core.loader.base import Document
from core.context.assembler import (
    ContextAssembler, ContextBlock, render_context_block, display_score,
)
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

    def test_keeps_input_order_not_reorders_by_score(self):
        """保持上游输入顺序：不再按 score 或 rerank_score 重新排序"""
        hits = [
            Document(content="低分", metadata={"score": 0.3, "id": "a"}),
            Document(content="高分", metadata={"score": 0.9, "id": "b"}),
        ]
        blocks = ContextAssembler().assemble(hits)
        assert [b.content for b in blocks] == ["低分", "高分"]

    def test_keeps_input_order_with_rerank_score(self):
        # 有 rerank_score 也不重排：顺序由 Retriever/Reranker 决定
        hits = [
            Document(content="A", metadata={"id": "a", "score": 0.9, "rerank_score": 0.2}),
            Document(content="B", metadata={"id": "b", "score": 0.1, "rerank_score": 0.8}),
        ]
        blocks = ContextAssembler().assemble(hits)
        assert [b.content for b in blocks] == ["A", "B"]
        assert blocks[1].retrieval_scores["rerank_score"] == 0.8
        assert display_score(blocks[1]) == 0.8

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
    """渲染预算（真实 tiktoken）：长来源 header 的高分块放不下正文时跳过，
    后续短 header 的低分块仍进入上下文"""
    from core.loader.base import Document
    hits = [
        Document(content="缓存穿透", metadata={"id": "c1", "source": "缓存缓存缓存",
                                              "source_name": "缓存缓存缓存", "score": 0.9}),
        Document(content="a", metadata={"id": "c2", "source": "x",
                                        "source_name": "x", "score": 0.8}),
    ]
    counter = TokenCounter()
    h1 = counter.count("[C1] [来源: 缓存缓存缓存]\n")
    h2 = counter.count("[C2] [来源: x]\n")
    assert h1 - h2 >= 2  # 长来源 header 成本更高（预算语义前提）
    # 预算 = h1 + 1：块1 正文连一个字符都放不下（"缓"=2 token）→ 跳过，
    # 块2 短 header 完整放得下（"a"=1 token → 保留）
    assembler = ContextAssembler(max_context_tokens=h1 + 1)
    blocks = assembler.assemble(hits)
    assert [b.content for b in blocks] == ["a"]
    rendered = "\n\n".join(render_context_block(b) for b in blocks)
    assert counter.count(rendered) <= h1 + 1


# ── G1-CTX-03A：统一渲染契约（预算按渲染后文本） ────────
# Char3 下：header "[C1] [来源: a.md]\n" = 16 字符 = 48 token；"\n\n" = 6 token

def test_render_context_block_format():
    b = ContextBlock(citation_id="[C1]", chunk_id="c1", source_name="redis.md",
                     page_number=None, content="缓存穿透", token_count=3)
    assert render_context_block(b) == "[C1] [来源: redis.md]\n缓存穿透"


def test_assembler_rendered_context_within_budget():
    """渲染后的 context（含 header/分隔符）总 token 不超过预算"""
    hits = [
        Document(content="内容一" * 30, metadata={"source_name": "a.md", "score": 0.9}),
        Document(content="内容二" * 30, metadata={"source_name": "b.md", "score": 0.8}),
    ]
    assembler = ContextAssembler(max_context_tokens=120, token_counter=Char3TokenCounter())
    blocks = assembler.assemble(hits)
    rendered = "\n\n".join(render_context_block(b) for b in blocks)
    assert Char3TokenCounter().count(rendered) <= 120


def test_header_and_separator_count_in_budget():
    """引用编号、来源头与块间分隔符都计入预算（预算精确等于各组成部分）"""
    hits = [
        Document(content="缓", metadata={"source_name": "a.md", "score": 0.9}),
        Document(content="a", metadata={"source_name": "b.md", "score": 0.8}),
    ]
    # 预算 = sep(6) + h1(48) + body(3) + h2(48) + body(3) = 108
    assembler = ContextAssembler(max_context_tokens=108, token_counter=Char3TokenCounter())
    blocks = assembler.assemble(hits)
    assert len(blocks) == 2
    assert blocks[0].content == "缓"
    assert blocks[1].content == "a"
    rendered = "\n\n".join(render_context_block(b) for b in blocks)
    assert Char3TokenCounter().count(rendered) <= 108


def test_header_preserved_when_truncated():
    """超长块只截正文：引用与来源头保持完整，无 U+FFFD"""
    hits = [Document(content="缓存穿透", metadata={"source_name": "a.md", "score": 0.9})]
    assembler = ContextAssembler(max_context_tokens=48 + 3, token_counter=Char3TokenCounter())
    blocks = assembler.assemble(hits)
    assert len(blocks) == 1
    assert blocks[0].content == "缓"  # 正文截到 1 字符
    rendered = render_context_block(blocks[0])
    assert rendered.startswith("[C1] [来源: a.md]\n")
    assert "�" not in rendered


def test_block_skipped_when_header_plus_char_not_fit():
    """连完整头部+至少一个正文字符都放不下 → 跳过该块"""
    hits = [Document(content="缓存", metadata={"source_name": "a.md", "score": 0.9})]
    assembler = ContextAssembler(max_context_tokens=48, token_counter=Char3TokenCounter())
    blocks = assembler.assemble(hits)
    assert blocks == []


# ── G1-CTX-03A-R1：预算按最终完整渲染字符串判断 ────────

def test_render_without_citation_no_leading_space():
    """无 citation_id 的 Document：`[来源: xxx]\n正文`，行首无多余空格"""
    doc = Document(content="正文内容", metadata={"source_name": "a.md"})
    assert render_context_block(doc) == "[来源: a.md]\n正文内容"


class NonAdditiveCounter(TokenCounter):
    """模拟 BPE 跨边界：joined 中 '\n' 后跟非换行字符时额外 +1 token，
    使 'sep + 两块分别计数' 的和 < 真实拼接计数"""

    def __init__(self):
        self._enc = None

    def count(self, text):
        extra = sum(1 for i in range(len(text) - 1)
                    if text[i] == "\n" and text[i + 1] != "\n")
        return len(text) + extra


def test_non_additive_counter_regression():
    """separate 计数和看似等于预算，joined 更大：最终渲染不得超预算"""
    counter = NonAdditiveCounter()
    sep = "\n\n"
    hits = [
        Document(content="缓存", metadata={"source_name": "a.md", "score": 0.9}),
        Document(content="穿透", metadata={"source_name": "b.md", "score": 0.8}),
    ]
    rendered_hits = [render_context_block(h) for h in hits]
    # 构造预算 = sep + 两块单独渲染之和（非可加假设下的"看似够"）
    budget = counter.count(sep) + counter.count(rendered_hits[0]) + counter.count(rendered_hits[1])
    # 验证前提：真实拼接确实更大（sep 末尾换行与下块边界产生额外 token）
    full = "\n\n".join(rendered_hits)
    assert counter.count(full) > budget

    assembler = ContextAssembler(max_context_tokens=budget, token_counter=counter)
    blocks = assembler.assemble(hits)
    rendered = "\n\n".join(render_context_block(b) for b in blocks)
    assert counter.count(rendered) <= budget, "最终渲染文本不得超预算"


def test_truncation_mixed_text_prefix_no_replacement():
    """中文/英文/Emoji 混合正文：截断是原文字符前缀，无 U+FFFD，不超预算"""
    text = ("缓存穿透 Cache 穿透击穿 🎉🚀 Emoji 混排 " * 5).strip()
    hits = [Document(content=text, metadata={"source_name": "a.md", "score": 0.9})]
    # 预算 = header(48) + 1 个字符(3)：正文恰好能截 1 字符
    assembler = ContextAssembler(max_context_tokens=51, token_counter=Char3TokenCounter())
    blocks = assembler.assemble(hits)
    assert len(blocks) == 1
    assert text.startswith(blocks[0].content), "截断必须是原文字符前缀"
    assert "�" not in blocks[0].content
    assert "�" not in render_context_block(blocks[0])
    rendered = "\n\n".join(render_context_block(b) for b in blocks)
    assert Char3TokenCounter().count(rendered) <= 51


# ── G1-RANK-04：排名契约（保持上游顺序，不自行排序） ──

def test_hybrid_rrf_order_kept_when_dense_score_reversed():
    """Hybrid RRF 输入顺序与 Dense score 相反：保持 RRF 输入顺序"""
    hits = [
        Document(content="RRF高分但Dense低分", metadata={
            "id": "a", "score": 0.1, "rrf_score": 0.9, "dense_rank": 3,
            "sparse_rank": 1, "final_rank": 1}),
        Document(content="Dense高分但RRF低分", metadata={
            "id": "b", "score": 0.9, "rrf_score": 0.2, "dense_rank": 1,
            "sparse_rank": None, "final_rank": 2}),
    ]
    blocks = ContextAssembler().assemble(hits)
    assert [b.content for b in blocks] == ["RRF高分但Dense低分", "Dense高分但RRF低分"]


def test_sparse_only_not_pushed_to_end():
    """Sparse-only 文档没有 Dense score 时，不得被重新推到末尾"""
    hits = [
        Document(content="sparse-only 结果", metadata={
            "id": "s", "sparse_score": 0.7, "sparse_rank": 1, "final_rank": 1}),
        Document(content="dense 结果", metadata={
            "id": "d", "score": 0.9, "dense_rank": 1, "final_rank": 2}),
    ]
    blocks = ContextAssembler().assemble(hits)
    assert [b.content for b in blocks] == ["sparse-only 结果", "dense 结果"]


def test_mmr_order_kept_when_dense_score_reversed():
    """MMR 输入顺序与原 Dense score 相反：保持 MMR 顺序"""
    hits = [
        Document(content="MMR第一名", metadata={"id": "m1", "score": 0.2, "mmr_score": 0.8}),
        Document(content="MMR第二名", metadata={"id": "m2", "score": 0.9, "mmr_score": 0.3}),
    ]
    blocks = ContextAssembler().assemble(hits)
    assert [b.content for b in blocks] == ["MMR第一名", "MMR第二名"]


def test_dedup_keeps_first_occurrence():
    """相同内容去重保留第一次出现（即最高上游排名）"""
    hits = [
        Document(content="重复内容", metadata={"id": "first", "score": 0.1, "final_rank": 1}),
        Document(content="其他", metadata={"id": "mid", "score": 0.5, "final_rank": 2}),
        Document(content="重复内容", metadata={"id": "later", "score": 0.9, "final_rank": 3}),
    ]
    blocks = ContextAssembler().assemble(hits)
    assert [b.content for b in blocks] == ["重复内容", "其他"]
    assert blocks[0].chunk_id == "first"


def test_retrieval_scores_keep_all_present_fields():
    """retrieval_scores 完整保留各阶段已有字段；缺失字段不虚构为 0"""
    hits = [Document(content="内容", metadata={
        "id": "c1", "score": 0.5, "distance": 0.3, "dense_score": 0.6,
        "sparse_score": 0.7, "rrf_score": 0.8, "mmr_score": 0.9,
        "rerank_score": 0.95, "rank": 2, "dense_rank": 3, "sparse_rank": 1,
        "final_rank": 1})]
    blocks = ContextAssembler().assemble(hits)
    rs = blocks[0].retrieval_scores
    assert rs["score"] == 0.5
    assert rs["distance"] == 0.3
    assert rs["dense_score"] == 0.6
    assert rs["sparse_score"] == 0.7
    assert rs["rrf_score"] == 0.8
    assert rs["mmr_score"] == 0.9
    assert rs["rerank_score"] == 0.95
    assert rs["rank"] == 2
    assert rs["dense_rank"] == 3
    assert rs["sparse_rank"] == 1
    assert rs["final_rank"] == 1
    # 缺失字段不出现（区别于"真实 0 分"）
    assert "score2" not in rs


def test_display_score_priority():
    """sources.score 统一展示分数：rerank > mmr > rrf > score"""
    from core.context.assembler import display_score
    base = dict(id="c1")
    cases = [
        ({"score": 0.1, "rrf_score": 0.4, "mmr_score": 0.5, "rerank_score": 0.9}, 0.9),
        ({"score": 0.1, "rrf_score": 0.4, "mmr_score": 0.5}, 0.5),
        ({"score": 0.1, "rrf_score": 0.4}, 0.4),
        ({"score": 0.1}, 0.1),
        ({"sparse_score": 0.7}, 0.0),  # 无展示分数候选 → 0.0
    ]
    for meta, expected in cases:
        block = ContextAssembler().assemble(
            [Document(content="x", metadata={**base, **meta})]
        )[0]
        assert display_score(block) == expected, f"{meta}"
