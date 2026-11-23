import pytest

from rra.cache import FileCache
from rra.data import DataError
from rra.pdf import ReportReader, clean_text, download, truncate


def test_clean_text_drops_axis_lines():
    assert clean_text("投资要点\n-8%\n12\n营收  增长\n\n") == "投资要点\n营收 增长"


def test_truncate():
    assert truncate("abc", 5) == "abc"
    assert truncate("abcdef", 3).startswith("abc\n…")


def test_download_rejects_other_hosts():
    with pytest.raises(DataError):
        download("http://example.com/a.pdf")


def test_reader_caches(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("rra.pdf.extract_text", lambda b: b.decode())

    def fake_download(url):
        calls.append(url)
        return "正文内容".encode()

    reader = ReportReader(FileCache(tmp_path), downloader=fake_download)
    assert reader.read("u") == "正文内容"
    assert reader.read("u", max_chars=2).startswith("正文")
    assert calls == ["u"]


def test_reader_empty_text(tmp_path, monkeypatch):
    monkeypatch.setattr("rra.pdf.extract_text", lambda b: "")
    reader = ReportReader(FileCache(tmp_path), downloader=lambda u: b"")
    with pytest.raises(DataError, match="扫描件"):
        reader.read("u")


@pytest.mark.network
def test_real_pdf(tmp_path):
    from rra.data import MarketData

    cache = FileCache(tmp_path)
    r = MarketData(cache).list_reports("600519", days=365)[0]
    text = ReportReader(cache).read(r["pdf_url"], max_chars=3000)
    assert "600519" in text or "茅台" in text
