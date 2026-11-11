"""Process & Lifecycle Monitor for VocalPro v3.0.0.

Provides verification of process tree hierarchy, child process cleanup,
OS signal handling (SIGTERM, SIGINT), zombie process detection, and memory RSS bounds.
"""

from __future__ import annotations

import os
import signal
import time
from typing import Any, Optional

import psutil


class ProcessMonitor:
    """Inspector for process lifecycles, memory consumption, and signals."""

    @staticmethod
    def get_process_info(pid: int) -> dict[str, Any]:
        """Fetch memory, CPU, and thread metrics for a specific PID."""
        try:
            proc = psutil.Process(pid)
            mem = proc.memory_info()
            cpu_pct = proc.cpu_percent(interval=None)
            threads = proc.num_threads()
            status = proc.status()
            return {
                "pid": pid,
                "name": proc.name(),
                "status": status,
                "cpu_percent": cpu_pct,
                "rss_bytes": mem.rss,
                "rss_mb": round(mem.rss / (1024.0 * 1024.0), 2),
                "vms_mb": round(mem.vms / (1024.0 * 1024.0), 2),
                "num_threads": threads,
                "is_running": proc.is_running(),
            }
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return {
                "pid": pid,
                "status": "terminated",
                "is_running": False,
                "rss_mb": 0.0,
            }

    @staticmethod
    def get_children(pid: int, recursive: bool = True) -> list[psutil.Process]:
        """Return all child processes spawned by this PID."""
        try:
            parent = psutil.Process(pid)
            return parent.children(recursive=recursive)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return []

    @staticmethod
    def assert_no_zombies(pid: int) -> None:
        """Verify that neither the process nor any of its descendants are zombies."""
        try:
            parent = psutil.Process(pid)
            if parent.status() == psutil.STATUS_ZOMBIE:
                raise AssertionError(f"Parent PID {pid} is in zombie state")
            for child in parent.children(recursive=True):
                if child.status() == psutil.STATUS_ZOMBIE:
                    raise AssertionError(f"Child PID {child.pid} of parent {pid} is a zombie")
        except psutil.NoSuchProcess:
            pass

    @staticmethod
    def is_alive(pid: int) -> bool:
        """Check if a process is actively alive and not a zombie."""
        try:
            proc = psutil.Process(pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return False

    @staticmethod
    def test_signal_termination(
        pid: int, sig: signal.Signals = signal.SIGTERM, timeout: float = 3.0
    ) -> bool:
        """Send an OS signal to a PID and confirm it terminates within timeout."""
        if not ProcessMonitor.is_alive(pid):
            return True

        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return True

        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if not ProcessMonitor.is_alive(pid):
                return True
            time.sleep(0.05)

        return not ProcessMonitor.is_alive(pid)

    @staticmethod
    def monitor_rss_bounded(pid: int, max_mb: float = 4096.0) -> float:
        """Assert that process RSS memory does not exceed max_mb."""
        info = ProcessMonitor.get_process_info(pid)
        rss_mb = info.get("rss_mb", 0.0)
        if rss_mb > max_mb:
            raise AssertionError(f"Process PID {pid} exceeded memory bound: {rss_mb} MB > {max_mb} MB")
        return rss_mb
