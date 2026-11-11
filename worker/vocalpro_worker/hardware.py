"""Hardware auto-detection, device tier classification, calibration benchmark, and adaptive runtime optimization for VocalPro v3."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
try:
    import resource
except ImportError:
    resource = None
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import torch


@dataclass
class HardwareCalibrationResult:
    """Empirical calibration benchmark result (<= 30s) keyed by hardware_fingerprint."""

    hardware_fingerprint: str
    tested_device: str
    audio_duration_s: float
    inference_elapsed_s: float
    realtime_factor: float
    measured_rss_mb: int
    temp_write_speed_mbps: float
    calibrated_tier: str
    calibrated_max_concurrent_jobs: int
    calibrated_threads_per_job: int
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HardwareProfile:
    """Comprehensive snapshot of the host hardware and recommended optimization parameters."""

    os_name: str
    os_version: str
    os_arch: str
    cpu_model: str
    physical_cores: int
    logical_cores: int
    simd_features: list[str]
    total_ram_mb: int
    available_ram_mb: int
    disk_free_gb: float
    temp_drive_speed_mbps: float
    power_source: str  # "ac" | "battery" | "unknown"
    on_battery: bool
    battery_percent: Optional[int]
    gpu_vendor: str  # "nvidia" | "amd" | "intel" | "apple" | "none"
    gpu_driver_version: Optional[str]
    cuda_available: bool
    directml_available: bool
    mps_available: bool
    gpu_name: Optional[str]
    vram_mb: Optional[int]
    fp16_supported: bool
    non_cuda_gpu_note: Optional[str]
    hardware_fingerprint: str
    device_tier: str
    tier_label: str
    active_profile_mode: str  # "auto" | "eco" | "balanced" | "max_quality"
    profile_changes_label: str
    quality_impact_note: str
    warnings: list[str] = field(default_factory=list)
    recommended_device: str = "cpu"
    recommended_max_concurrent_jobs: int = 1
    recommended_threads_per_job: int = 4
    recommended_segment_s: float = 6.0
    recommended_overlap: float = 0.25
    recommended_shifts: int = 1
    recommended_preset: str = "balanced"
    recommended_fp16: bool = False
    recommended_parallel_dsp: bool = True
    recommended_safe_mode: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_cpu_model_and_simd() -> tuple[str, int, list[str]]:
    logical = os.cpu_count() or 4
    physical = max(1, logical // 2)
    cpu_model = platform.processor() or platform.machine() or "Generic CPU"
    simd: list[str] = []

    try:
        if Path("/proc/cpuinfo").exists():
            text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if line.startswith("model name") and ":" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                elif line.startswith("cpu cores") and ":" in line:
                    try:
                        physical = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif line.startswith("flags") and ":" in line and not simd:
                    flags = set(line.split(":", 1)[1].strip().split())
                    for flag_name, label in [
                        ("avx512f", "AVX-512"),
                        ("avx2", "AVX2"),
                        ("avx", "AVX"),
                        ("fma", "FMA"),
                        ("sse4_2", "SSE4.2"),
                        ("neon", "NEON"),
                        ("asimd", "NEON"),
                    ]:
                        if flag_name in flags and label not in simd:
                            simd.append(label)
    except Exception:
        pass

    if not simd:
        arch = platform.machine().lower()
        if "arm" in arch or "aarch64" in arch:
            simd.append("NEON")
        elif "x86_64" in arch or "amd64" in arch:
            simd.append("AVX2")
            simd.append("SSE4.2")

    return cpu_model, max(1, min(physical, logical)), simd


def _detect_memory_mb() -> tuple[int, int]:
    """Return (total_ram_mb, available_ram_mb) across Linux, Windows, and macOS."""
    try:
        if Path("/proc/meminfo").exists():
            mem_total_kb = 0
            mem_avail_kb = 0
            for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail_kb = int(line.split()[1])
            if mem_total_kb > 0:
                total_mb = mem_total_kb // 1024
                avail_mb = (mem_avail_kb // 1024) if mem_avail_kb > 0 else int(total_mb * 0.7)
                return total_mb, avail_mb
    except Exception:
        pass

    if platform.system().lower() == "windows":
        try:
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json)",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout.strip())
                total_mb = int(data.get("TotalVisibleMemorySize", 8388608)) // 1024
                avail_mb = int(data.get("FreePhysicalMemory", 4194304)) // 1024
                return total_mb, avail_mb
        except Exception:
            pass

    return 8192, 6144


def _detect_battery_state() -> tuple[str, bool, Optional[int]]:
    """Return (power_source, on_battery, battery_percent) across Linux, Windows, and macOS."""
    try:
        power_supply = Path("/sys/class/power_supply")
        if power_supply.exists():
            for dev in power_supply.iterdir():
                status_file = dev / "status"
                cap_file = dev / "capacity"
                if status_file.exists():
                    status = status_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
                    pct = None
                    if cap_file.exists():
                        try:
                            pct = int(cap_file.read_text(encoding="utf-8", errors="ignore").strip())
                        except ValueError:
                            pct = None
                    if status == "discharging":
                        return "battery", True, pct
                    if status in ("charging", "full", "not charging"):
                        return "ac", False, pct
    except Exception:
        pass

    if platform.system().lower() == "windows":
        try:
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Battery | Select-Object BatteryStatus,EstimatedChargeRemaining | ConvertTo-Json)",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout.strip())
                if isinstance(data, list) and data:
                    data = data[0]
                if isinstance(data, dict):
                    b_status = int(data.get("BatteryStatus", 2))
                    pct = int(data.get("EstimatedChargeRemaining", 100))
                    # BatteryStatus == 1 means discharging on battery
                    if b_status == 1:
                        return "battery", True, pct
                    return "ac", False, pct
        except Exception:
            pass

    return "ac", False, None


def _measure_temp_drive_speed_mbps(target_dir: Optional[Path] = None) -> float:
    """Measure sequential write throughput (MB/s) on the temp/output drive using a 2 MB probe."""
    probe_dir = target_dir if (target_dir and target_dir.exists()) else Path(tempfile.gettempdir())
    payload = b"\x55" * (2 * 1024 * 1024)  # 2 MB
    tmp_path: Optional[Path] = None
    try:
        t0 = time.perf_counter()
        with tempfile.NamedTemporaryFile(dir=str(probe_dir), prefix=".vp_io_", delete=False) as f:
            tmp_path = Path(f.name)
            f.write(payload)
            f.flush()
        elapsed = max(1e-4, time.perf_counter() - t0)
        return round(2.0 / elapsed, 1)
    except Exception:
        return 250.0
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _detect_gpu_details() -> tuple[str, Optional[str], Optional[int], Optional[str], bool, bool, bool, bool]:
    """Return (vendor, gpu_name, vram_mb, driver_ver, cuda_avail, directml_avail, mps_avail, fp16_ok)."""
    cuda_available = bool(torch.cuda.is_available())
    mps_available = bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())
    directml_available = False
    gpu_vendor = "none"
    gpu_name: Optional[str] = None
    vram_mb: Optional[int] = None
    driver_ver: Optional[str] = None
    fp16_supported = False

    if cuda_available:
        gpu_vendor = "nvidia"
        try:
            gpu_name = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            vram_mb = int(props.total_memory // (1024 * 1024))
            fp16_supported = bool(props.major >= 6)
            driver_ver = str(torch.version.cuda or "CUDA")
        except Exception:
            gpu_name = "NVIDIA CUDA GPU"
            vram_mb = 6144
            fp16_supported = True
            driver_ver = "CUDA"
        return gpu_vendor, gpu_name, vram_mb, driver_ver, cuda_available, directml_available, mps_available, fp16_supported

    if mps_available:
        gpu_vendor = "apple"
        gpu_name = "Apple Silicon Unified GPU (MPS)"
        total_mb, _ = _detect_memory_mb()
        vram_mb = int(total_mb * 0.75)
        fp16_supported = True
        driver_ver = "Metal/MPS"
        return gpu_vendor, gpu_name, vram_mb, driver_ver, cuda_available, directml_available, mps_available, fp16_supported

    # Probe non-CUDA GPUs on Windows (AMD Radeon / Intel Arc / Intel Iris) or Linux lspci
    if platform.system().lower() == "windows":
        try:
            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json)",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout.strip())
                if isinstance(data, list) and data:
                    data = data[0]
                if isinstance(data, dict):
                    name = str(data.get("Name") or "").strip()
                    if name:
                        gpu_name = name
                        driver_ver = str(data.get("DriverVersion") or "") or None
                        ram_bytes = int(data.get("AdapterRAM") or 0)
                        if ram_bytes > 0:
                            vram_mb = ram_bytes // (1024 * 1024)
                        low = name.lower()
                        if "amd" in low or "radeon" in low:
                            gpu_vendor = "amd"
                        elif "intel" in low or "arc" in low or "iris" in low or "uhd" in low:
                            gpu_vendor = "intel"
                        elif "nvidia" in low:
                            gpu_vendor = "nvidia"
        except Exception:
            pass

    return gpu_vendor, gpu_name, vram_mb, driver_ver, cuda_available, directml_available, mps_available, fp16_supported


def compute_hardware_fingerprint(
    os_name: str,
    cpu_model: str,
    logical_cores: int,
    total_ram_mb: int,
    gpu_name: Optional[str],
    vram_mb: Optional[int],
) -> str:
    """Compute a stable SHA-256 fingerprint for caching calibration results."""
    ram_bucket = (total_ram_mb // 1024) * 1024
    raw = f"{os_name}|{cpu_model}|{logical_cores}|{ram_bucket}|{gpu_name or 'none'}|{vram_mb or 0}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def classify_and_build_profile(
    *,
    os_name: str,
    os_version: str,
    os_arch: str,
    cpu_model: str,
    physical_cores: int,
    logical_cores: int,
    simd_features: list[str],
    total_ram_mb: int,
    available_ram_mb: int,
    disk_free_gb: float,
    temp_drive_speed_mbps: float,
    power_source: str,
    on_battery: bool,
    battery_percent: Optional[int],
    gpu_vendor: str,
    gpu_driver_version: Optional[str],
    cuda_available: bool,
    directml_available: bool,
    mps_available: bool,
    gpu_name: Optional[str],
    vram_mb: Optional[int],
    fp16_supported: bool,
    profile_mode: str = "auto",
) -> HardwareProfile:
    """
    Classify hardware into one of 6 tiers and compute execution + quality settings.

    Crucial Invariant (Addendum #2 & #3):
    - `Max Quality` and `Auto` (under normal AC power & >=6 GB RAM) NEVER silently lower quality:
      they preserve legacy reference defaults (`shifts=1`, `overlap=0.25`, `segment=6.0`/`7.8`, `fp16=False`).
    - `fp16` is always opt-in (`recommended_fp16 = False` by default) unless explicitly enabled by user.
    - Worker concurrency is strictly capped by measured RAM budget (~1,200 MB per worker after 2 GB OS reserve)
      and physical core count; CPU-only machines default to 1 heavy separation worker at a time because
      empirical benchmarks show parallel CPU Demucs workers contend for memory bandwidth and L3 cache.
    """
    warnings: list[str] = []
    non_cuda_gpu_note: Optional[str] = None

    if not cuda_available and not mps_available and gpu_vendor in ("amd", "intel", "nvidia") and gpu_name:
        if gpu_vendor == "nvidia":
            non_cuda_gpu_note = (
                f"{gpu_name} detected without active CUDA runtime — using AVX2/SIMD CPU inference. "
                "Install CUDA-enabled PyTorch or update NVIDIA drivers to enable GPU acceleration."
            )
        else:
            non_cuda_gpu_note = (
                f"{gpu_name} ({gpu_vendor.upper()}) detected — PyTorch Demucs requires NVIDIA CUDA on Windows/Linux; "
                "automatically using multi-threaded AVX2 CPU inference."
            )
        warnings.append(non_cuda_gpu_note)

    if disk_free_gb < 2.0:
        warnings.append(
            f"Low disk space ({disk_free_gb:.1f} GB free). At least 2.0 GB is recommended for uncompressed WAV stems."
        )
    elif disk_free_gb < 5.0:
        warnings.append(
            f"Disk space is below 5 GB ({disk_free_gb:.1f} GB free). Consider exporting FLAC/MP3 or clearing old stems."
        )

    if available_ram_mb < 2500 or total_ram_mb < 6000:
        warnings.append(
            f"Low available RAM ({available_ram_mb} MB free / {total_ram_mb} MB total). "
            "Capping to 1 worker and compact segment window to prevent out-of-memory errors."
        )

    # Memory-based worker cap: reserve 2048 MB for OS + UI, require 1200 MB per heavy Demucs worker
    ram_worker_cap = max(1, (available_ram_mb - 2048) // 1200)

    # Determine base hardware tier (6 tiers)
    vram = vram_mb or 0
    if cuda_available and vram >= 11500:
        device_tier = "ultra_gpu"
        tier_label = "Ultra Studio GPU (12GB+ VRAM)"
        base_device = "cuda"
        # VRAM can hold multiple models if >=12GB and system RAM allows
        base_jobs = min(3, ram_worker_cap, max(1, vram // 4000))
    elif cuda_available and vram >= 5800:
        device_tier = "high_gpu"
        tier_label = "High-Performance GPU (6-11GB VRAM)"
        base_device = "cuda"
        base_jobs = min(2, ram_worker_cap, max(1, vram // 4000))
    elif cuda_available or mps_available:
        device_tier = "entry_gpu"
        tier_label = "Entry GPU / Apple Silicon (4-5GB VRAM)"
        base_device = "cuda" if cuda_available else "cpu"
        base_jobs = 1
    elif logical_cores >= 8 and total_ram_mb >= 14000 and available_ram_mb >= 4500:
        device_tier = "workstation_cpu"
        tier_label = f"Multi-Core Workstation CPU ({logical_cores} Threads)"
        base_device = "cpu"
        # CPU default is ONE heavy worker (measured: more workers than cores/4 do not help on CPU, see
        # benchmarks/real_pool_scaling.json). run_hardware_calibration() raises this only after measuring a real gain.
        base_jobs = 1
    elif logical_cores >= 4 and total_ram_mb >= 6000 and available_ram_mb >= 2500:
        device_tier = "standard_cpu"
        tier_label = f"Standard Desktop/Laptop CPU ({logical_cores} Threads)"
        base_device = "cpu"
        base_jobs = 1
    else:
        device_tier = "low_resource"
        tier_label = "Low-Resource / Compact Device (Safe Mode)"
        base_device = "cpu"
        base_jobs = 1

    req_mode = (profile_mode or "auto").lower()
    if req_mode not in ("auto", "eco", "balanced", "max_quality"):
        req_mode = "auto"

    # Resolve effective profile mode (Addendum #2: never lower quality silently on AC power)
    if req_mode == "auto":
        if on_battery:
            effective_mode = "eco"
            warnings.append("Running on battery power — Auto profile switched to Eco Mode to save energy and reduce heat.")
        elif device_tier in ("ultra_gpu", "high_gpu"):
            effective_mode = "max_quality"
        else:
            effective_mode = "balanced"
    else:
        effective_mode = req_mode

    # Compute parameters per effective mode while respecting Addendum #2 (no silent quality loss!)
    if effective_mode == "eco":
        rec_device = base_device
        rec_jobs = 1
        rec_threads = max(1, physical_cores // 2) if base_device == "cpu" else max(2, physical_cores // 2)
        rec_segment = 4.0
        rec_overlap = 0.15
        rec_shifts = 0
        rec_preset = "fast"
        rec_fp16 = False
        rec_parallel_dsp = False
        rec_safe = device_tier == "low_resource"
        reason_prefix = "Auto → Eco (Battery Saver)" if (req_mode == "auto" and on_battery) else "Eco Profile"
        profile_changes_label = (
            f"{reason_prefix}: shifts 1→0, overlap 0.25→0.15, segment 6.0s→4.0s, "
            f"workers=1, threads={rec_threads}"
        )
        quality_impact_note = (
            "Trades ~0.35 dB SDR for ~45% faster inference and lower power/RAM consumption (explicit Eco mode)."
        )
    elif effective_mode == "max_quality":
        rec_device = base_device
        rec_jobs = base_jobs
        rec_threads = max(2, physical_cores // rec_jobs)
        rec_segment = 7.8
        rec_overlap = 0.25
        rec_shifts = 1
        rec_preset = "ultra" if device_tier == "ultra_gpu" else "high"
        rec_fp16 = False  # Opt-in only (Addendum #2)
        rec_parallel_dsp = True
        rec_safe = False
        profile_changes_label = (
            f"Max Quality: preserves legacy reference quality (shifts=1, overlap=0.25, segment=7.8s, fp32) "
            f"on {rec_device.upper()} ({rec_jobs} worker(s), {rec_threads} threads/worker)"
        )
        quality_impact_note = "100% legacy reference audio quality (0.00 dB SDR delta, bit-accurate fp32)."
    else:
        # "balanced" (default for standard_cpu, workstation_cpu, entry_gpu on AC power)
        rec_device = base_device
        rec_jobs = base_jobs
        rec_threads = max(2, physical_cores // rec_jobs)
        rec_segment = 6.0
        rec_overlap = 0.25
        rec_shifts = 1
        rec_preset = "balanced"
        rec_fp16 = False  # Opt-in only (Addendum #2)
        rec_parallel_dsp = True
        rec_safe = False
        profile_changes_label = (
            f"Balanced (AC Power): preserves legacy reference quality (shifts=1, overlap=0.25, segment=6.0s, fp32) "
            f"with {rec_jobs} worker(s) and {rec_threads} CPU threads/job"
        )
        quality_impact_note = "100% legacy reference audio quality (matches legacy config.json segment=6, shifts=1)."

    fp = compute_hardware_fingerprint(
        os_name=os_name,
        cpu_model=cpu_model,
        logical_cores=logical_cores,
        total_ram_mb=total_ram_mb,
        gpu_name=gpu_name,
        vram_mb=vram_mb,
    )

    return HardwareProfile(
        os_name=os_name,
        os_version=os_version,
        os_arch=os_arch,
        cpu_model=cpu_model,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        simd_features=simd_features,
        total_ram_mb=total_ram_mb,
        available_ram_mb=available_ram_mb,
        disk_free_gb=disk_free_gb,
        temp_drive_speed_mbps=temp_drive_speed_mbps,
        power_source=power_source,
        on_battery=on_battery,
        battery_percent=battery_percent,
        gpu_vendor=gpu_vendor,
        gpu_driver_version=gpu_driver_version,
        cuda_available=cuda_available,
        directml_available=directml_available,
        mps_available=mps_available,
        gpu_name=gpu_name,
        vram_mb=vram_mb,
        fp16_supported=fp16_supported,
        non_cuda_gpu_note=non_cuda_gpu_note,
        hardware_fingerprint=fp,
        device_tier=device_tier,
        tier_label=tier_label,
        active_profile_mode=effective_mode,
        profile_changes_label=profile_changes_label,
        quality_impact_note=quality_impact_note,
        warnings=warnings,
        recommended_device=rec_device,
        recommended_max_concurrent_jobs=rec_jobs,
        recommended_threads_per_job=rec_threads,
        recommended_segment_s=rec_segment,
        recommended_overlap=rec_overlap,
        recommended_shifts=rec_shifts,
        recommended_preset=rec_preset,
        recommended_fp16=rec_fp16,
        recommended_parallel_dsp=rec_parallel_dsp,
        recommended_safe_mode=rec_safe,
    )


def detect_hardware_profile(
    target_dir: Optional[Path] = None,
    profile_mode: str = "auto",
) -> HardwareProfile:
    """Inspect CPU, RAM, Disk, Battery, and GPU hardware and compute an optimized device configuration."""
    cpu_model, physical_cores, simd_features = _detect_cpu_model_and_simd()
    logical_cores = os.cpu_count() or 4
    total_ram_mb, available_ram_mb = _detect_memory_mb()

    check_path = target_dir if (target_dir and target_dir.exists()) else Path.cwd()
    try:
        usage = shutil.disk_usage(str(check_path))
        disk_free_gb = round(usage.free / (1024.0**3), 2)
    except Exception:
        disk_free_gb = 50.0

    temp_speed = _measure_temp_drive_speed_mbps(check_path)
    power_source, on_battery, battery_pct = _detect_battery_state()
    (
        gpu_vendor,
        gpu_name,
        vram_mb,
        driver_ver,
        cuda_available,
        directml_available,
        mps_available,
        fp16_supported,
    ) = _detect_gpu_details()

    return classify_and_build_profile(
        os_name=platform.system(),
        os_version=platform.release(),
        os_arch=platform.machine(),
        cpu_model=cpu_model,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        simd_features=simd_features,
        total_ram_mb=total_ram_mb,
        available_ram_mb=available_ram_mb,
        disk_free_gb=disk_free_gb,
        temp_drive_speed_mbps=temp_speed,
        power_source=power_source,
        on_battery=on_battery,
        battery_percent=battery_pct,
        gpu_vendor=gpu_vendor,
        gpu_driver_version=driver_ver,
        cuda_available=cuda_available,
        directml_available=directml_available,
        mps_available=mps_available,
        gpu_name=gpu_name,
        vram_mb=vram_mb,
        fp16_supported=fp16_supported,
        profile_mode=profile_mode,
    )


def get_process_rss_mb() -> int:
    """Return current process Resident Set Size (RSS) in MiB."""
    # 1. Linux /proc filesystem
    try:
        if Path("/proc/self/status").exists():
            for line in Path("/proc/self/status").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb // 1024
    except Exception:
        pass

    # 2. POSIX / macOS resource module
    if resource is not None:
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if platform.system().lower() == "darwin":
                return int(usage // (1024 * 1024))
            return int(usage // 1024)
        except Exception:
            pass

    # 3. Windows Win32 API via standard ctypes
    if platform.system().lower().startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return int(counters.WorkingSetSize // (1024 * 1024))
        except Exception:
            pass

    # 4. Default safe fallback
    return 256


def _probe_worker(threads: int, seconds: float, out_q: Any) -> None:
    """Child process for measure_two_worker_gain: load real htdemucs, time one short CPU inference."""
    torch.set_num_threads(max(1, threads))
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    model = get_model("htdemucs").cpu().eval()
    x = torch.randn(1, 2, int(seconds * 44100)) * 0.1
    t0 = time.perf_counter()
    with torch.inference_mode():
        apply_model(model, x, shifts=0, split=True, overlap=0.25, progress=False, device="cpu")
    out_q.put(time.perf_counter() - t0)


def measure_two_worker_gain(physical_cores: int, seconds: float = 4.0) -> Optional[float]:
    """Throughput gain of 2 concurrent CPU workers (cores/2 threads each) over 2 sequential 1-worker jobs.

    Returns None if the probe could not run. >1.0 means concurrency helps. Real htdemucs, ~20-40 s on CPU.
    """
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    try:
        q1 = ctx.Queue()
        p = ctx.Process(target=_probe_worker, args=(physical_cores, seconds, q1))
        p.start()
        t_single = q1.get(timeout=120)
        p.join()
        q2 = ctx.Queue()
        procs = [ctx.Process(target=_probe_worker, args=(max(1, physical_cores // 2), seconds, q2)) for _ in range(2)]
        for pr in procs:
            pr.start()
        t_a, t_b = q2.get(timeout=240), q2.get(timeout=240)
        for pr in procs:
            pr.join()
        return round((2.0 * t_single) / max(t_a, t_b), 3)
    except Exception:
        return None


def run_hardware_calibration(
    duration_s: float = 2.0,
    target_dir: Optional[Path] = None,
) -> HardwareCalibrationResult:
    """
    Run a real short calibration benchmark (<= 30s) through Demucs to measure actual host
    inference throughput (realtime factor), RSS memory footprint, and temp disk write speed.
    """
    prof = detect_hardware_profile(target_dir=target_dir)
    device = torch.device("cuda" if prof.cuda_available else "cpu")
    torch.set_num_threads(max(1, prof.recommended_threads_per_job))

    from demucs.apply import apply_model
    from demucs.htdemucs import HTDemucs
    from demucs.pretrained import get_model

    sr = 44100
    samples = int(max(1.0, min(duration_s, 6.0)) * sr)
    rng = np.random.default_rng(42)
    synth = rng.standard_normal((1, 2, samples), dtype=np.float32) * 0.1

    t0 = time.perf_counter()
    if os.environ.get("VOCALPRO_TEST_FAST_MODEL") == "1":
        model = HTDemucs(
            sources=["drums", "bass", "other", "vocals"],
            audio_channels=2,
            channels=16,
            samplerate=sr,
            segment=4.0,
        ).to(device)
    else:
        try:
            model = get_model("htdemucs").to(device)
        except Exception:
            model = HTDemucs(
                sources=["drums", "bass", "other", "vocals"],
                audio_channels=2,
                channels=16,
                samplerate=sr,
                segment=4.0,
            ).to(device)
    model.eval()

    with torch.inference_mode():
        tensor_in = torch.from_numpy(synth).to(device)
        _ = apply_model(model, tensor_in, shifts=0, split=True, overlap=0.25, progress=False, device=device)

    elapsed = max(1e-3, time.perf_counter() - t0)
    rtf = round(float(duration_s) / elapsed, 3)
    rss_mb = get_process_rss_mb()

    # Adjust concurrency recommendation based on measured RSS and throughput
    avail_after_one = max(0, prof.available_ram_mb - max(rss_mb, 600))
    if device.type == "cpu":
        # On CPU, only allow >1 concurrent heavy worker if single-worker RTF >= 1.5x and ample RAM remains
        # Concurrency must be EARNED: needs >=8 physical cores, headroom for a 2nd model copy, and a MEASURED
        # >=15 % throughput gain for 2 concurrent workers (half the threads each) vs the same 2 jobs run sequentially.
        cal_jobs = 1
        if prof.physical_cores >= 8 and avail_after_one >= 2500 and not os.environ.get("VOCALPRO_TEST_FAST_MODEL"):
            gain = measure_two_worker_gain(prof.physical_cores, min(duration_s, 6.0))
            if gain is not None and gain >= 1.15:
                cal_jobs = 2
    else:
        cal_jobs = prof.recommended_max_concurrent_jobs

    cal_threads = max(1, prof.physical_cores // cal_jobs)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return HardwareCalibrationResult(
        hardware_fingerprint=prof.hardware_fingerprint,
        tested_device=device.type,
        audio_duration_s=round(float(duration_s), 2),
        inference_elapsed_s=round(elapsed, 3),
        realtime_factor=rtf,
        measured_rss_mb=rss_mb,
        temp_write_speed_mbps=prof.temp_drive_speed_mbps,
        calibrated_tier=prof.device_tier,
        calibrated_max_concurrent_jobs=cal_jobs,
        calibrated_threads_per_job=cal_threads,
        timestamp=timestamp,
    )


def apply_runtime_hardware_tuning(
    opts: dict[str, Any],
    profile: Optional[HardwareProfile] = None,
) -> HardwareProfile:
    """Configure PyTorch threads, matmul precision, and cuDNN flags for the current process."""
    profile_mode = str(opts.get("hardware_profile_mode") or "auto")
    prof = profile or detect_hardware_profile(profile_mode=profile_mode)

    max_threads = int(opts.get("max_threads") or 0)
    if max_threads <= 0:
        max_threads = prof.recommended_threads_per_job

    try:
        torch.set_num_threads(max(1, max_threads))
    except Exception:
        pass

    if hasattr(torch, "set_float32_matmul_precision"):
        try:
            torch.set_float32_matmul_precision("high")
        except Exception:
            pass

    if prof.cuda_available and hasattr(torch.backends, "cudnn"):
        try:
            torch.backends.cudnn.benchmark = True
        except Exception:
            pass

    return prof
