"""Helpers for pulling a clean HTML document out of the model's answer."""

from __future__ import annotations

import html as html_lib
import re

DEFAULT_TITLE = "Сайт от Say IT"

_START_RE = re.compile(r"<!DOCTYPE\s+html[^>]*>|<html[\s>]", re.IGNORECASE)
_END_RE = re.compile(r"</html\s*>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)


class HtmlExtractionError(ValueError):
    """The model's answer does not contain a complete HTML document."""


def extract_html(text: str) -> str:
    """Return the HTML document from `text`, dropping code fences and chatter around it."""
    start = _START_RE.search(text)
    if not start:
        raise HtmlExtractionError("В ответе модели нет HTML-документа")

    ends = list(_END_RE.finditer(text, start.start()))
    if not ends:
        raise HtmlExtractionError("HTML-документ оборвался — не найден закрывающий </html>")

    return text[start.start() : ends[-1].end()].strip()


def extract_title(html: str, default: str = DEFAULT_TITLE) -> str:
    match = _TITLE_RE.search(html)
    if not match:
        return default
    title = html_lib.unescape(" ".join(match.group(1).split()))
    return title or default
