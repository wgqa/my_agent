import os
from core.loader.pdf_loader import PDFLoader


def create_test_pdf(path: str):
    """生成一个测试用的最小 PDF 文件"""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Hello PDF World.\nThis is page one.")
    doc.save(path)
    doc.close()


def test_pdf_loader_basic(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    create_test_pdf(str(pdf_path))

    loader = PDFLoader()
    docs = loader.load(str(pdf_path))

    assert len(docs) == 1
    assert "Hello PDF World" in docs[0].content
    assert docs[0].metadata["type"] == "pdf"
    assert docs[0].metadata["page_num"] == 1


def test_pdf_loader_source_in_metadata(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    create_test_pdf(str(pdf_path))

    loader = PDFLoader()
    docs = loader.load(str(pdf_path))

    assert str(pdf_path) in docs[0].metadata["source"]
