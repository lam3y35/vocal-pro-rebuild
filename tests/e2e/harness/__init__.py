"""VocalPro v3.0.0 E2E Testing Harness Package."""

from .ipc_client import IpcClient
from .audio_validator import AudioValidator
from .process_monitor import ProcessMonitor

__all__ = ["IpcClient", "AudioValidator", "ProcessMonitor"]
