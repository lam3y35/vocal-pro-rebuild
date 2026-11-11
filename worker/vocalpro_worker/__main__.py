"""Main entry point for `python -m vocalpro_worker` (stdio UTF-8 JSON-Lines loop)."""

from __future__ import annotations

import json
import shutil
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import torch

from . import __version__
from .analysis import analyze_audio_file
from .engine import (
    MODEL_POOL,
    JobCancelledError,
    WorkerEngineError,
    resolve_ffmpeg,
    run_separation_job,
)
from .hardware import detect_hardware_profile, run_hardware_calibration
from .midi import stem_to_midi_file
from .protocol import StdioProtocol


def _gpu_info() -> tuple[bool, str | None, int | None]:
    cuda_ok = bool(torch.cuda.is_available())
    if not cuda_ok:
        return False, None, None
    try:
        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        vram_mb = int(props.total_memory // (1024 * 1024))
        return True, name, vram_mb
    except Exception:
        return True, "CUDA Device", None


class WorkerApp:
    """Persistent JSON-Lines worker handling control commands concurrently with heavy jobs."""

    def __init__(self, isolate_fd: bool = True) -> None:
        self.proto = StdioProtocol(isolate_fd=isolate_fd)
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vocalpro-job")
        self._shutdown_flag = threading.Event()

    def emit_ready(self, cmd_id: str | None = None) -> None:
        cuda_ok, gpu_name, vram_mb = _gpu_info()
        payload: dict[str, Any] = {
            "v": 1,
            "event": "ready",
            "worker_version": __version__,
            "torch_version": torch.__version__,
            "cuda_available": cuda_ok,
            "gpu_name": gpu_name,
            "vram_mb": vram_mb,
        }
        if cmd_id is not None:
            payload["id"] = cmd_id
        self.proto.send(payload)

    def _run_separate_task(self, cmd: dict[str, Any], cancel_ev: threading.Event) -> None:
        cmd_id = str(cmd.get("id", ""))
        job_id = str(cmd.get("job_id", ""))
        try:
            if cancel_ev.is_set():
                raise JobCancelledError()
            res = run_separation_job(
                job_id=job_id,
                input_path_str=str(cmd["input_path"]),
                output_dir_str=str(cmd.get("output_dir", "")),
                options=dict(cmd.get("options") or {}),
                cancel_event=cancel_ev,
                emit_event=self.proto.send,
            )
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "job_done",
                    "job_id": job_id,
                    "output_dir": res["output_dir"],
                    "stems": res["stems"],
                    "comparison_samples": res["comparison_samples"],
                    "elapsed_s": res["elapsed_s"],
                }
            )
        except JobCancelledError:
            out_d = cmd.get("output_dir")
            if out_d:
                try:
                    p = Path(out_d)
                    if p.is_dir():
                        for f in p.glob("*.*"):
                            f.unlink(missing_ok=True)
                except Exception:
                    pass
            self.proto.send({"v": 1, "id": cmd_id, "event": "job_cancelled", "job_id": job_id})
        except WorkerEngineError as exc:
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "job_error",
                    "job_id": job_id,
                    "code": exc.code,
                    "message": exc.message,
                    "detail": exc.detail,
                }
            )
        except Exception as exc:
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "job_error",
                    "job_id": job_id,
                    "code": "INTERNAL",
                    "message": str(exc),
                    "detail": traceback.format_exc()[-800:],
                }
            )
        finally:
            with self._cancel_lock:
                self._cancel_events.pop(job_id, None)

    def _run_analyze_task(self, cmd: dict[str, Any]) -> None:
        cmd_id = str(cmd.get("id", ""))
        input_path = str(cmd.get("input_path", ""))
        try:
            res = analyze_audio_file(input_path)
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "analysis_done",
                    "bpm": res["bpm"],
                    "key": res["key"],
                    "scale": res["scale"],
                    "duration_s": res["duration_s"],
                    "waveform": res["waveform"],
                }
            )
        except Exception as exc:
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "job_error",
                    "job_id": cmd_id,
                    "code": "DECODE_FAILED",
                    "message": f"Audio analysis failed: {exc}",
                    "detail": str(exc),
                }
            )

    def _run_midi_task(self, cmd: dict[str, Any]) -> None:
        cmd_id = str(cmd.get("id", ""))
        stem_path = str(cmd.get("stem_path", ""))
        output_midi_path = str(cmd.get("output_midi_path", ""))
        try:
            note_count = stem_to_midi_file(stem_path, output_midi_path)
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "midi_done",
                    "output_midi_path": output_midi_path,
                    "note_count": note_count,
                }
            )
        except Exception as exc:
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "job_error",
                    "job_id": cmd_id,
                    "code": "INTERNAL",
                    "message": f"Stem-to-MIDI failed: {exc}",
                    "detail": str(exc),
                }
            )

    def _run_calibrate_task(self, cmd: dict[str, Any]) -> None:
        cmd_id = str(cmd.get("id", ""))
        dur = float(cmd.get("duration_s", 2.0))
        try:
            cal = run_hardware_calibration(duration_s=dur).to_dict()
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "calibration_done",
                    "calibration": cal,
                }
            )
        except Exception as exc:
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "job_error",
                    "job_id": cmd_id,
                    "code": "INTERNAL",
                    "message": f"Hardware calibration failed: {exc}",
                    "detail": str(exc),
                }
            )

    def handle_command(self, cmd: dict[str, Any]) -> bool:
        """Dispatch a single command dict. Returns False when shutdown is requested."""
        cmd_name = cmd.get("cmd")
        cmd_id = str(cmd.get("id", ""))

        if cmd_name == "hello":
            self.emit_ready(cmd_id=cmd_id)
            return True

        if cmd_name == "ping":
            self.proto.send({"v": 1, "id": cmd_id, "event": "pong"})
            return True

        if cmd_name == "get_capabilities":
            cuda_ok, gpu_name, vram_mb = _gpu_info()
            hw = detect_hardware_profile().to_dict()
            devices = ["auto", "cpu"] + (["cuda"] if cuda_ok else [])
            resolved_ffmpeg = resolve_ffmpeg()
            ffmpeg_available = bool(
                resolved_ffmpeg
                and (shutil.which(resolved_ffmpeg) is not None or Path(resolved_ffmpeg).is_file())
            )
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "capabilities",
                    "models": list(MODEL_POOL),
                    "devices": devices,
                    "ffmpeg_available": ffmpeg_available,
                    "cuda_available": cuda_ok,
                    "gpu_name": gpu_name,
                    "vram_mb": vram_mb,
                    "hardware_profile": hw,
                }
            )
            return True

        if cmd_name == "get_hardware_profile":
            mode = str(cmd.get("profile_mode") or "auto")
            hw = detect_hardware_profile(profile_mode=mode).to_dict()
            self.proto.send(
                {
                    "v": 1,
                    "id": cmd_id,
                    "event": "hardware_profile",
                    "profile": hw,
                }
            )
            return True

        if cmd_name == "calibrate_hardware":
            self._executor.submit(self._run_calibrate_task, cmd)
            return True

        if cmd_name == "separate":
            job_id = str(cmd["job_id"])
            cancel_ev = threading.Event()
            with self._cancel_lock:
                self._cancel_events[job_id] = cancel_ev
            self._executor.submit(self._run_separate_task, cmd, cancel_ev)
            return True

        if cmd_name == "cancel":
            job_id = str(cmd.get("job_id", ""))
            with self._cancel_lock:
                ev = self._cancel_events.get(job_id)
                if ev is not None:
                    ev.set()
                else:
                    # Job not currently active; acknowledge cancellation immediately
                    self.proto.send({"v": 1, "id": cmd_id, "event": "job_cancelled", "job_id": job_id})
            return True

        if cmd_name == "analyze":
            self._executor.submit(self._run_analyze_task, cmd)
            return True

        if cmd_name == "stem_to_midi":
            self._executor.submit(self._run_midi_task, cmd)
            return True

        if cmd_name == "shutdown":
            with self._cancel_lock:
                for ev in self._cancel_events.values():
                    ev.set()
            self._shutdown_flag.set()
            self.proto.send({"v": 1, "id": cmd_id, "event": "pong"})
            return False

        self.proto.log("warn", f"Unknown command: {cmd_name}")
        return True

    def run_forever(self) -> int:
        # Emit initial ready frame immediately on startup
        self.emit_ready()

        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError as exc:
                self.proto.log("error", f"Malformed JSON command: {exc}")
                continue
            if not self.handle_command(cmd):
                break

        self._executor.shutdown(wait=False, cancel_futures=True)
        return 0


def main() -> None:
    app = WorkerApp(isolate_fd=True)
    raise SystemExit(app.run_forever())


if __name__ == "__main__":
    main()
