"""从环境变量读取配置。支持项目根目录的 .env 文件。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """读取简单的 KEY=VALUE 文件，不覆盖已有环境变量。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    api_key: str | None
    base_url: str
    model: str
    cache_dir: Path

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_key=os.environ.get("RRA_API_KEY"),
            base_url=os.environ.get("RRA_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("RRA_MODEL", "deepseek-chat"),
            cache_dir=Path(os.environ.get("RRA_CACHE_DIR", Path.home() / ".cache" / "rra")),
        )
