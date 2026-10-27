import pytest

from app.html_utils import HtmlExtractionError, extract_html, extract_title

DOC = "<!DOCTYPE html>\n<html><head><title>Hi</title></head><body>ok</body></html>"


def test_returns_plain_html_unchanged():
    assert extract_html(DOC) == DOC


def test_strips_markdown_code_fence():
    text = f"```html\n{DOC}\n```"
    assert extract_html(text) == DOC


def test_strips_text_around_document():
    text = f"Конечно! Вот ваш сайт:\n\n{DOC}\n\nНадеюсь, понравится."
    assert extract_html(text) == DOC


def test_accepts_document_without_doctype():
    doc = "<html><body>x</body></html>"
    assert extract_html(f"Here:\n{doc}") == doc


def test_raises_when_no_html():
    with pytest.raises(HtmlExtractionError):
        extract_html("Извините, я не могу помочь.")


def test_raises_when_document_is_truncated():
    with pytest.raises(HtmlExtractionError):
        extract_html("<!DOCTYPE html><html><body><h1>Обрыв")


def test_extract_title():
    assert extract_title(DOC) == "Hi"


def test_extract_title_trims_whitespace_and_unescapes():
    assert extract_title("<title>\n  Tom &amp; Jerry  </title>") == "Tom & Jerry"


def test_extract_title_default():
    assert extract_title("<html></html>") == "Сайт от Say IT"
