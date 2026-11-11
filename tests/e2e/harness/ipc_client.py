"""Opaque-box Line-Delimited JSON IPC Client for VocalPro v3 Worker.

Spawns `worker/.venv/bin/python -m vocalpro_worker`, establishes line-delimited
UTF-8 JSON communication over stdin/stdout, monitors stderr diagnostics concurrently,
and validates responses against the official IPC protocol.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class IpcClient:
    """Opaque-box IPC client communicating with the VocalPro Python Worker via stdio JSON-Lines."""

    def __init__(
        self,
        python_bin: Optional[str] = None,
        cwd: Optional[str | Path] = None,
        extra_env: Optional[dict[str, str]] = None,
        startup_timeout: float = 15.0,
    ) -> None:
        workspace_root = Path(__file__).resolve().parents[3]
        self.cwd = Path(cwd) if cwd else workspace_root
        if python_bin:
            self.python_bin = Path(python_bin)
        else:
            self.python_bin = self.cwd / "worker" / ".venv" / "bin" / "python"
            if not self.python_bin.exists():
                self.python_bin = Path(sys.executable)

        self.extra_env = dict(extra_env or {})
        self.startup_timeout = startup_timeout

        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()

        # Responses & events tracking
        self._pending_queues: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._all_events: list[dict[str, Any]] = []
        self._events_by_job: dict[str, list[dict[str, Any]]] = {}
        self._events_lock = threading.Lock()

        # Stderr log capture
        self._stderr_lines: list[str] = []
        self._stderr_lock = threading.Lock()

        # Initial ready frame captured on startup
        self._ready_frame: Optional[dict[str, Any]] = None
        self._ready_event = threading.Event()
        self._is_closed = False

    @property
    def pid(self) -> int:
        if self._proc is None:
            raise RuntimeError("Worker process is not running")
        return self._proc.pid

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def ready_frame(self) -> Optional[dict[str, Any]]:
        return self._ready_frame

    def start(self) -> None:
        """Spawn the worker process, start listener threads, and await the ready frame."""
        if self._proc is not None:
            return

        env = dict(os.environ)
        # Required zero-failure environment guarantees
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("TORCH_HOME", str(self.cwd / "worker" / ".torch"))
        env.setdefault("VOCALPRO_MODELS_DIR", str(self.cwd / "worker" / ".models"))
        env.setdefault("VOCALPRO_TEST_FAST_MODEL", "1")
        env.update(self.extra_env)

        cmd = [str(self.python_bin), "-m", "vocalpro_worker"]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.cwd),
            env=env,
            bufsize=0,
        )

        self._stdout_thread = threading.Thread(
            target=self._read_stdout_loop, name="ipc-stdout-reader", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr_loop, name="ipc-stderr-reader", daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        if not self._ready_event.wait(timeout=self.startup_timeout):
            self.terminate()
            stderr_preview = "\n".join(self.get_stderr_logs()[-20:])
            raise TimeoutError(
                f"Timed out waiting {self.startup_timeout}s for worker ready event. "
                f"Stderr logs:\n{stderr_preview}"
            )

    def _read_stdout_loop(self) -> None:
        """Read line-delimited JSON messages from worker stdout."""
        assert self._proc is not None and self._proc.stdout is not None
        stdout = self._proc.stdout

        while not self._is_closed:
            raw_line = stdout.readline()
            if not raw_line:
                break
            line_str = raw_line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue

            try:
                msg = json.loads(line_str)
            except json.JSONDecodeError:
                with self._stderr_lock:
                    self._stderr_lines.append(f"[IPC PROTOCOL WARNING] Malformed stdout: {line_str}")
                continue

            event_name = msg.get("event")
            msg_id = str(msg.get("id") or "")
            job_id = str(msg.get("job_id") or "")

            with self._events_lock:
                self._all_events.append(msg)
                if job_id:
                    self._events_by_job.setdefault(job_id, []).append(msg)

            # Check for initial ready frame
            if event_name == "ready" and not self._ready_event.is_set():
                self._ready_frame = msg
                self._ready_event.set()

            # Terminal events that fulfill a command request
            terminal_events = {
                "pong",
                "ready",
                "capabilities",
                "hardware_profile",
                "calibration_done",
                "job_done",
                "job_error",
                "job_cancelled",
                "analysis_done",
                "midi_done",
            }

            if event_name in terminal_events:
                with self._pending_lock:
                    q = self._pending_queues.get(msg_id)
                    if q is not None:
                        q.put(msg)
                    # Also deliver to job_id queue if tracked by job_id
                    if job_id and job_id != msg_id:
                        q_job = self._pending_queues.get(job_id)
                        if q_job is not None:
                            q_job.put(msg)

    def _read_stderr_loop(self) -> None:
        """Capture diagnostic and error output from worker stderr."""
        assert self._proc is not None and self._proc.stderr is not None
        stderr = self._proc.stderr

        while not self._is_closed:
            raw_line = stderr.readline()
            if not raw_line:
                break
            line_str = raw_line.decode("utf-8", errors="replace").rstrip()
            if line_str:
                with self._stderr_lock:
                    self._stderr_lines.append(line_str)

    def send_raw_command(self, cmd_dict: dict[str, Any]) -> str:
        """Send a command dictionary over stdin without waiting."""
        if not self.is_running or self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Worker process is not running")

        payload = dict(cmd_dict)
        if "v" not in payload:
            payload["v"] = 1
        if "id" not in payload:
            payload["id"] = f"cmd-{uuid.uuid4().hex[:8]}"

        cmd_id = str(payload["id"])
        with self._pending_lock:
            self._pending_queues[cmd_id] = queue.Queue()
            if "job_id" in payload and payload.get("cmd") != "cancel":
                self._pending_queues[str(payload["job_id"])] = self._pending_queues[cmd_id]

        raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            self._proc.stdin.write(raw)
            self._proc.stdin.flush()

        return cmd_id

    def wait_for_response(self, cmd_or_job_id: str, timeout: float = 30.0) -> dict[str, Any]:
        """Wait for the terminal response event for a previously dispatched command."""
        with self._pending_lock:
            q = self._pending_queues.get(cmd_or_job_id)
            if q is None:
                q = queue.Queue()
                self._pending_queues[cmd_or_job_id] = q

        try:
            resp = q.get(timeout=timeout)
            return resp
        except queue.Empty:
            stderr_tail = "\n".join(self.get_stderr_logs()[-25:])
            raise TimeoutError(
                f"Timed out ({timeout}s) waiting for response to {cmd_or_job_id}. "
                f"Stderr tail:\n{stderr_tail}"
            )

    def send_command(self, cmd_dict: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        """Send a command synchronously and wait for its completion response."""
        cmd_id = self.send_raw_command(cmd_dict)
        return self.wait_for_response(cmd_id, timeout=timeout)

    def ping(self, timeout: float = 5.0) -> dict[str, Any]:
        """Send a ping keepalive and verify pong response."""
        return self.send_command({"cmd": "ping"}, timeout=timeout)

    def hello(self, timeout: float = 5.0) -> dict[str, Any]:
        """Send a hello handshake and receive ready response."""
        return self.send_command({"cmd": "hello"}, timeout=timeout)

    def get_capabilities(self, timeout: float = 5.0) -> dict[str, Any]:
        """Query engine capabilities (supported models, devices, ffmpeg)."""
        return self.send_command({"cmd": "get_capabilities"}, timeout=timeout)

    def cancel_job(self, job_id: str, timeout: float = 5.0) -> dict[str, Any]:
        """Send a cooperative cancellation request for an active job."""
        cancel_id = self.send_raw_command({"cmd": "cancel", "job_id": job_id})
        try:
            return self.wait_for_response(cancel_id, timeout=0.05)
        except TimeoutError:
            return {"event": "cancel_dispatched", "job_id": job_id, "id": cancel_id}

    def separate(
        self,
        input_path: str | Path,
        output_dir: str | Path,
        options: Optional[dict[str, Any]] = None,
        job_id: Optional[str] = None,
        timeout: float = 45.0,
    ) -> dict[str, Any]:
        """Send a separation job and block until job_done, job_error, or job_cancelled."""
        j_id = job_id or f"job-{uuid.uuid4().hex[:8]}"
        default_opts = {
            "model": "htdemucs",
            "output_mode": "vocals",
            "output_format": "wav",
            "audio_bitrate": "320k",
            "device": "cpu",
            "shifts": 0,
            "overlap": 0.25,
            "segment": 4.0,
        }
        if options:
            default_opts.update(options)

        cmd = {
            "cmd": "separate",
            "job_id": j_id,
            "input_path": str(input_path),
            "output_dir": str(output_dir),
            "options": default_opts,
        }
        return self.send_command(cmd, timeout=timeout)

    def analyze(self, input_path: str | Path, timeout: float = 20.0) -> dict[str, Any]:
        """Run musical analysis on an audio file."""
        return self.send_command({"cmd": "analyze", "input_path": str(input_path)}, timeout=timeout)

    def stem_to_midi(
        self, stem_path: str | Path, output_midi_path: str | Path, timeout: float = 20.0
    ) -> dict[str, Any]:
        """Transcribe an isolated stem to MIDI."""
        return self.send_command(
            {
                "cmd": "stem_to_midi",
                "stem_path": str(stem_path),
                "output_midi_path": str(output_midi_path),
            },
            timeout=timeout,
        )

    def get_events(self, job_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Return captured event history, optionally filtered by job_id."""
        with self._events_lock:
            if job_id:
                return list(self._events_by_job.get(job_id, []))
            return list(self._all_events)

    def get_stderr_logs(self) -> list[str]:
        """Return all logged lines from stderr."""
        with self._stderr_lock:
            return list(self._stderr_lines)

    def close(self, timeout: float = 3.0) -> None:
        """Gracefully shut down the worker and close IPC pipes."""
        if self._is_closed:
            return
        self._is_closed = True

        if self.is_running:
            try:
                # Attempt cooperative shutdown command
                self.send_command({"cmd": "shutdown"}, timeout=1.0)
            except Exception:
                pass

        if self._proc is not None:
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()

        if self._stdout_thread and self._stdout_thread.is_alive():
            self._stdout_thread.join(timeout=1.0)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)

    def terminate(self) -> None:
        """Immediately terminate the worker process."""
        self._is_closed = True
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=2.0)
            except Exception:
                pass

    def __enter__(self) -> "IpcClient":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
