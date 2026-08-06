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
