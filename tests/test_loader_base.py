from core.loader.base import Document, BaseLoader

def test_document_creation():
    doc = Document(content="hello",metadata={"source":"test.txt"})
    assert doc.content == "hello"
    assert doc.metadata["source"] == "test.txt"

def test_document_default_metadata():
      doc = Document(content="hello")
      assert doc.metadata == {}


def test_base_loader_cannot_instantiate():
      try:
          BaseLoader()
          assert False, "应该不能实例化抽象类"
      except TypeError:
          pass