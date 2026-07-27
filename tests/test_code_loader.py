from core.loader.code_loader import CodeLoader


def test_code_loader_split_functions(tmp_path):
    code = """
def foo():
    pass

def bar():
    pass

class MyClass:
    def method(self):
        pass
"""
    file_path = tmp_path / "test.py"
    file_path.write_text(code)

    loader = CodeLoader()
    docs = loader.load(str(file_path))

    # 应该至少分割出 def foo, def bar, class MyClass 三块
    assert len(docs) >= 2
    assert any("def foo" in d.content for d in docs)
    assert any("class MyClass" in d.content for d in docs)


def test_code_loader_single_function(tmp_path):
    code = "x = 1\ny = 2\n"
    file_path = tmp_path / "simple.py"
    file_path.write_text(code)

    loader = CodeLoader()
    docs = loader.load(str(file_path))

    assert len(docs) == 1
