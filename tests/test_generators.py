import pytest

from core.loader.base import Document
from core.generator.base import BaseGenerator


def test_base_generator_abstract():
    try:
        BaseGenerator()
        assert False
    except TypeError:
        pass


def test_build_prompt():
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen = DeepSeekGenerator(api_key="test")
    docs = [Document(content="AI is important.", metadata={"source": "doc1.pdf"})]
    prompt = gen._build_prompt("What is AI?", docs)

    assert "AI is important" in prompt
    assert "What is AI?" in prompt
    assert "doc1.pdf" in prompt


def test_deepseek_gen_init():
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen = DeepSeekGenerator(api_key="sk-test")
    assert gen.model == "deepseek-v4-flash"
    assert gen.temperature == 0.3


def test_openai_gen_init():
    from core.generator.openai_gen import OpenAIGenerator
    gen = OpenAIGenerator(api_key="sk-test")
    assert gen.model == "gpt-4o-mini"


# ── M3-T2: 消息结构与安全边界 ─────────────────────────

def test_build_messages_has_system_and_user():
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen = DeepSeekGenerator(api_key="sk-test")
    docs = [Document(content="缓存穿透是……", metadata={"source": "redis.md"})]
    messages = gen._build_messages("什么是缓存穿透？", docs)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "<context>" in messages[1]["content"]
    assert "<question>" in messages[1]["content"]


def test_system_prompt_has_injection_guard():
    """system prompt 必须包含注入防护规则"""
    from core.generator.base import SYSTEM_PROMPT
    assert "忽略" in SYSTEM_PROMPT
    assert "资料内容" in SYSTEM_PROMPT


def test_system_prompt_has_no_answer_rule():
    """system prompt 必须包含无答案规则"""
    from core.generator.base import SYSTEM_PROMPT
    assert "不足" in SYSTEM_PROMPT


def test_system_prompt_has_citation_rule():
    """system prompt 必须要求 [Cx] 引用"""
    from core.generator.base import SYSTEM_PROMPT
    assert "[Cx]" in SYSTEM_PROMPT


def test_build_messages_with_context_block():
    """ContextBlock 也能构建消息（带引用编号）"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from core.context.assembler import ContextBlock
    gen = DeepSeekGenerator(api_key="sk-test")
    blocks = [
        ContextBlock(citation_id="[C1]", chunk_id="c1", source_name="redis.md",
                     page_number=None, content="缓存穿透是……", token_count=5),
    ]
    messages = gen._build_messages("什么是缓存穿透？", blocks)
    assert "[C1]" in messages[1]["content"]
    assert "redis.md" in messages[1]["content"]


# ── G1-CTX-03A：Generator 只拼接、不二次截断 ───────────

def test_build_messages_uses_same_render_no_retruncation():
    """Generator 拼接内容与 render_context_block 完全一致（超预算块也不截断）"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from core.context.assembler import ContextBlock, render_context_block
    gen = DeepSeekGenerator(api_key="sk-test")
    block = ContextBlock(citation_id="[C1]", chunk_id="c1", source_name="a.md",
                         page_number=None, content="缓存穿透" * 200, token_count=1200)
    messages = gen._build_messages("q", [block])
    assert render_context_block(block) in messages[1]["content"]


def test_build_messages_does_not_call_encode_decode(monkeypatch):
    """Generator 不再调用 TokenCounter.encode/decode（二次截断已删除）"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from core.chunker.token_counter import TokenCounter

    def boom(self, text):
        raise AssertionError("二次截断已删除，encode/decode 不应被调用")

    monkeypatch.setattr(TokenCounter, "encode", boom)
    monkeypatch.setattr(TokenCounter, "decode", boom)
    gen = DeepSeekGenerator(api_key="sk-test")
    messages = gen._build_messages("q", [Document(content="x", metadata={"source": "s.md"})])
    assert "<context>" in messages[1]["content"]


def test_citation_validator_content_matches_generator():
    """CitationValidator 验证的正文与 Generator 消息中的正文一致"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from core.generator.citation import CitationValidator
    from core.context.assembler import ContextAssembler, render_context_block
    gen = DeepSeekGenerator(api_key="sk-test")
    hits = [
        Document(content="缓存穿透是……", metadata={"id": "c1", "source": "redis.md",
                                                 "source_name": "redis.md", "score": 0.9}),
    ]
    blocks = ContextAssembler().assemble(hits)
    messages = gen._build_messages("q", blocks)
    rendered = "\n\n".join(render_context_block(b) for b in blocks)
    assert rendered in messages[1]["content"]
    result = CitationValidator().validate("答案见 [C1]", blocks)
    assert result.validity_rate == 1.0


# ── M3-T5: Generator 可靠性 ──────────────────────────

from unittest.mock import MagicMock, patch


def test_auth_error_not_retried():
    """认证错误不重试，立即返回 AUTH_ERROR"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen = DeepSeekGenerator(api_key="sk-test")
    gen.client.chat.completions.create = MagicMock(
        side_effect=__import__("openai").AuthenticationError(
            "bad key", response=MagicMock(status_code=401), body={}
        )
    )
    result = gen.generate("q", [])
    assert "[GENERATOR_AUTH_ERROR]" in result


def test_rate_limit_retried_then_succeeds():
    """429 重试一次后成功"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from openai import RateLimitError

    gen = DeepSeekGenerator(api_key="sk-test", max_retries=1)

    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="重试后成功"))]

    mock_create = MagicMock(
        side_effect=[
            RateLimitError("limit", response=MagicMock(status_code=429), body={}),
            resp,
        ]
    )
    gen.client.chat.completions.create = mock_create
    result = gen.generate("q", [])
    assert result == "重试后成功"
    assert mock_create.call_count == 2


def test_timeout_retried_then_fails():
    """超时重试后仍失败 → GENERATOR_TIMEOUT"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from openai import APITimeoutError

    gen = DeepSeekGenerator(api_key="sk-test", max_retries=1)
    gen.client.chat.completions.create = MagicMock(
        side_effect=APITimeoutError("timeout")
    )
    result = gen.generate("q", [])
    assert "[GENERATOR_TIMEOUT]" in result


def test_max_tokens_set():
    """generate 调用必须传 max_tokens"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen = DeepSeekGenerator(api_key="sk-test")

    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_create = MagicMock(return_value=resp)
    gen.client.chat.completions.create = mock_create

    gen.generate("q", [])
    kwargs = mock_create.call_args.kwargs
    assert kwargs.get("max_tokens") == 800


# ── G1-CTX-03B：端到端 Prompt Budget ──────────────────

def test_available_context_tokens_shrinks_with_longer_query():
    """问题越长，可用 Context 预算越小"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen = DeepSeekGenerator(api_key="sk-test")
    short = gen.available_context_tokens("q")
    long = gen.available_context_tokens("q" * 500)
    assert long < short
    assert short > 0


def test_available_context_tokens_counts_fixed_cost():
    """System Prompt、包装与回答指令均计入预算（固定成本）"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from core.generator.base import SYSTEM_PROMPT, build_user_content
    from core.chunker.token_counter import TokenCounter
    gen = DeepSeekGenerator(api_key="sk-test")
    counter = TokenCounter()
    fixed = (counter.count(SYSTEM_PROMPT)
             + counter.count(build_user_content("q", ""))
             + gen.message_overhead_tokens)
    assert gen.available_context_tokens("q") == \
        gen.max_total_tokens - gen.max_output_tokens - fixed


def test_output_reserve_reduces_available():
    """输出预留增大时，可用 Context 预算减小"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen1 = DeepSeekGenerator(api_key="sk-test", max_output_tokens=200)
    gen2 = DeepSeekGenerator(api_key="sk-test", max_output_tokens=800)
    assert gen1.available_context_tokens("q") > gen2.available_context_tokens("q")


def test_full_input_plus_output_within_total():
    """完整输入 + 输出预留不超过总预算"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from core.generator.base import build_messages
    from core.context.assembler import ContextBlock
    from core.chunker.token_counter import TokenCounter
    gen = DeepSeekGenerator(api_key="sk-test")
    budget = gen.available_context_tokens("q")
    blocks = [
        ContextBlock(citation_id="[C1]", chunk_id="c1", source_name="a.md",
                     page_number=None, content="内容" * 50, token_count=150),
    ]
    assert gen.validate_budget("q", blocks) is None  # 预算内不抛
    counter = TokenCounter()
    total_input = sum(counter.count(m["content"]) for m in build_messages("q", blocks))
    assert total_input + gen.message_overhead_tokens + gen.max_output_tokens \
        <= gen.max_total_tokens


def test_budget_exhausted_raises_before_model():
    """固定内容耗尽预算：模型调用前抛清晰异常"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from core.generator.base import PromptBudgetError
    gen = DeepSeekGenerator(api_key="sk-test", max_total_tokens=100,
                            max_output_tokens=50)
    with pytest.raises(PromptBudgetError):
        gen.available_context_tokens("q" * 200)


def test_invalid_budget_params_rejected():
    """max_total_tokens/max_output_tokens 非法值被拒绝"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    with pytest.raises(ValueError):
        DeepSeekGenerator(api_key="sk-test", max_total_tokens=0)
    with pytest.raises(ValueError):
        DeepSeekGenerator(api_key="sk-test", max_total_tokens=100,
                          max_output_tokens=100)
    with pytest.raises(TypeError):
        DeepSeekGenerator(api_key="sk-test", max_output_tokens=True)


def test_validate_budget_raises_when_over():
    """发送前防御校验：输入+输出预留超限立即报错"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    from core.generator.base import PromptBudgetError
    from core.context.assembler import ContextBlock
    gen = DeepSeekGenerator(api_key="sk-test", max_total_tokens=200,
                            max_output_tokens=50)
    blocks = [
        ContextBlock(citation_id="[C1]", chunk_id="c1", source_name="a.md",
                     page_number=None, content="x" * 500, token_count=500),
    ]
    with pytest.raises(PromptBudgetError):
        gen.validate_budget("q", blocks)


def test_deepseek_uses_configured_max_output_tokens(monkeypatch):
    """DeepSeek 调用使用配置的 max_output_tokens 而非硬编码"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen = DeepSeekGenerator(api_key="sk-test", max_output_tokens=321)
    captured = {}

    def fake_create(**kwargs):
        captured["max_tokens"] = kwargs["max_tokens"]
        msg = type("M", (), {"content": "ok"})()
        ch = type("C", (), {"message": msg})()
        return type("R", (), {"choices": [ch]})()

    monkeypatch.setattr(gen.client.chat.completions, "create", fake_create)
    gen.generate("q", [])
    assert captured["max_tokens"] == 321


def test_available_context_tokens_mixed_language():
    """中英文和 Emoji 问题均能正确计算"""
    from core.generator.deepseek_gen import DeepSeekGenerator
    gen = DeepSeekGenerator(api_key="sk-test")
    for q in ["什么是缓存穿透？", "How does JVM GC work?", "缓存穿透 🎉🚀 Cache?"]:
        avail = gen.available_context_tokens(q)
        assert avail > 0
        assert avail < gen.max_total_tokens
