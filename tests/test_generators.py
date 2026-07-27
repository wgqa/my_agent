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
