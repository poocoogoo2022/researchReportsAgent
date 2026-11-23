from rra import cli
from rra.data import MarketData
from rra.cache import NullCache


def test_reports_command(fake_ak, capsys, monkeypatch):
    market = MarketData(NullCache(), ak=fake_ak)
    monkeypatch.setattr(market, "list_reports", lambda code, days: market.all_reports(code))
    cli.cmd_reports(market, "600519", 365)
    out = capsys.readouterr().out
    assert "贵州茅台(600519)" in out
    assert "中邮证券 上调：增持 → 买入" in out
    assert "2026: 均值" in out


def test_digest_requires_api_key(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("RRA_API_KEY", raising=False)
    monkeypatch.setenv("RRA_CACHE_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["digest", "600519"]) == 2
    assert "RRA_API_KEY" in capsys.readouterr().err
