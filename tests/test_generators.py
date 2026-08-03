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
