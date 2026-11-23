"""研报 PDF 下载与文本抽取。"""

from __future__ import annotations

import io
import re
from typing import Callable

import requests

from .cache import FileCache
from .data import DataError

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
MAX_PDF_BYTES = 30 * 1024 * 1024


def download(url: str, timeout: float = 30) -> bytes:
    if not url.startswith("https://pdf.dfcfw.com/"):
        raise DataError(f"不支持的研报链接：{url}")
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DataError(f"下载研报失败：{e}") from e
    if len(resp.content) > MAX_PDF_BYTES:
        raise DataError("研报 PDF 过大")
    return resp.content


def extract_text(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [p.extract_text() or "" for p in reader.pages]
    except Exception as e:  # pypdf 对损坏文件抛多种异常
        raise DataError(f"解析 PDF 失败：{e}") from e
    return clean_text("\n".join(pages))


def clean_text(text: str) -> str:
    text = text.replace("　", " ")
    text = re.sub(r"[ \t]+", " ", text)
    # 去掉纯数字/百分比的行（多为图表坐标轴）
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not re.fullmatch(r"[-+]?\d+(\.\d+)?%?", ln)]
    return "\n".join(lines)


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n…（正文已截断，原文共 {len(text)} 字）"


class ReportReader:
    def __init__(self, cache: FileCache, downloader: Callable[[str], bytes] = download):
        self.cache = cache
        self.downloader = downloader

    def full_text(self, pdf_url: str) -> str:
        text = self.cache.get_text("pdf", pdf_url, None, lambda: extract_text(self.downloader(pdf_url)))
        if not text.strip():
            raise DataError("PDF 中未抽取到文字（可能是扫描件）")
        return text

    def read(self, pdf_url: str, max_chars: int = 8000) -> str:
        return truncate(self.full_text(pdf_url), max_chars)
