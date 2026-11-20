"""Thread-safe stdio UTF-8 JSON-Lines framing for the VocalPro v3 Worker."""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, BinaryIO


def isolate_stdout_fd() -> int:
    """Duplicate original stdout fd (1) and redirect fd 1 -> stderr (2) so library prints never corrupt JSON-Lines."""
    proto_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return proto_fd


class StdioProtocol:
    """Manages isolated JSON-Lines framing over original stdout while redirecting fd 1 -> stderr."""

    def __init__(self, isolate_fd: bool = True, proto_fd: int | None = None) -> None:
        self._write_lock = threading.Lock()
        if proto_fd is not None:
            self._out: BinaryIO = os.fdopen(proto_fd, "wb", buffering=0)
        elif isolate_fd:
            # Duplicate original stdout fd so even C/C++ stdout writes to fd 1 go to stderr (fd 2)
            dup_fd = isolate_stdout_fd()
            self._out = os.fdopen(dup_fd, "wb", buffering=0)
        else:
            self._out = sys.stdout.buffer

    def send(self, payload: dict[str, Any]) -> None:
        """Serialize a WorkerEvent dict as a single compact UTF-8 JSON line and flush immediately."""
        if "v" not in payload:
            payload = {"v": 1, **payload}
        raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._write_lock:
            self._out.write(raw)
            self._out.flush()

    def log(self, level: str, message: str) -> None:
        """Emit a structured log event over the JSON-Lines channel."""
        self.send({"v": 1, "event": "log", "level": level, "message": str(message)})
