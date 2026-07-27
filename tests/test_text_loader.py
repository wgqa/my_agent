from core.loader.text_loader import TextLoader


def test_text_loader_basic(tmp_path):
      file_path = tmp_path / "test.txt"
      file_path.write_text("Hello World\nLine 2")

      loader = TextLoader()
      docs = loader.load(str(file_path))

      assert len(docs) == 1
      assert "Hello World" in docs[0].content


def test_text_loader_metadata(tmp_path):
      file_path = tmp_path / "readme.md"
      file_path.write_text("# Title")

      loader = TextLoader()
      docs = loader.load(str(file_path))

      assert docs[0].metadata["type"] == "text"
      assert "readme.md" in docs[0].metadata.get("filename", "")