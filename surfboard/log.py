"""Buffered structured logger with batching and log levels."""

from __future__ import annotations

import atexit
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOG_LEVELS = {"debug": 0, "info": 1, "warn": 2, "error": 3}


class SurfboardLogger:
    """Thread-safe buffered logger that flushes to disk in batches."""

    def __init__(self, log_dir: str | Path | None = None, level: str = "info", batch_size: int = 10):
        self.log_dir = Path(log_dir or (Path.home() / ".surfboard"))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._level = _LOG_LEVELS.get(level, 1)
        self._batch_size = batch_size
        self._buffer: list[str] = []
        self._lock = threading.Lock()
        self._history_path = self.log_dir / "history.jsonl"
        atexit.register(self.flush)

    def _write(self, entry: dict[str, Any]) -> None:
        line = json.dumps(entry, default=str)
        with self._lock:
            self._buffer.append(line + "\n")
            if len(self._buffer) >= self._batch_size:
                self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        if not self._buffer:
            return
        try:
            with open(self._history_path, "a", encoding="utf-8") as f:
                f.writelines(self._buffer)
        except OSError:
            pass
        self._buffer.clear()

    def flush(self) -> None:
        with self._lock:
            self._flush_unlocked()

    def log(self, tool: str, detail: str, status: str = "ok", level: str = "info") -> None:
        if _LOG_LEVELS.get(level, 1) < self._level:
            return
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "detail": detail,
            "status": status,
            "level": level,
        }
        self._write(entry)

    def info(self, tool: str, detail: str, status: str = "ok") -> None:
        self.log(tool, detail, status, "info")

    def warning(self, tool: str, detail: str, status: str = "warn") -> None:
        self.log(tool, detail, status, "warn")

    def warn(self, tool: str, detail: str, status: str = "warn") -> None:
        return self.warning(tool, detail, status)

    def error(self, tool: str, detail: str, status: str = "error") -> None:
        self.log(tool, detail, status, "error")


# Singleton shared across the process
_logger: SurfboardLogger | None = None
_lock = threading.Lock()


def get_logger() -> SurfboardLogger:
    global _logger
    if _logger is None:
        with _lock:
            if _logger is None:
                _logger = SurfboardLogger()
    return _logger
