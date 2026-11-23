"""简单的文件缓存：key -> JSON 或文本，带可选 TTL。"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable


class FileCache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, namespace: str, key: str, suffix: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self.root / namespace / f"{digest}{suffix}"

    def _fresh(self, path: Path, ttl: float | None) -> bool:
        if not path.is_file():
            return False
        return ttl is None or (time.time() - path.stat().st_mtime) < ttl

    def get_json(self, namespace: str, key: str, ttl: float | None, producer: Callable[[], Any]) -> Any:
        path = self._path(namespace, key, ".json")
        if self._fresh(path, ttl):
            return json.loads(path.read_text(encoding="utf-8"))
        value = producer()
        self._write(path, json.dumps(value, ensure_ascii=False))
        return value

    def get_text(self, namespace: str, key: str, ttl: float | None, producer: Callable[[], str]) -> str:
        path = self._path(namespace, key, ".txt")
        if self._fresh(path, ttl):
            return path.read_text(encoding="utf-8")
        value = producer()
        self._write(path, value)
        return value

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)


class NullCache(FileCache):
    """不缓存，直接调用 producer。测试用。"""

    def __init__(self) -> None:
        super().__init__(Path("/nonexistent"))

    def get_json(self, namespace, key, ttl, producer):
        return producer()

    def get_text(self, namespace, key, ttl, producer):
        return producer()
