# Project: VocalPro v3.0.0 — Zero Points of Failure Architecture

## Architecture
VocalPro v3.0.0 is an offline-capable, high-performance desktop studio stem separator.
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS + Lucide Icons + Web Audio API.
- **Backend**: Tauri v2 + Rust (`src-tauri/`) with tokio async runtime, custom process supervision (`WorkerSupervisor`), JSON-RPC / line-delimited IPC protocol, and Win32 Job Object / Linux death signal lifecycle management.
- **Python Engine**: Python 3.10–3.12 worker pool (`vocalpro_worker`), PyTorch, Demucs (htdemucs, mdx_extra), Librosa / SOXR DSP resamplers, FFmpeg audio decoding and remuxing.
- **Packaging & Distribution**: Inno Setup (`installer.iss`), standalone portable bundle, batch launchers with UTF-8 codepage 65001, Microsoft Edge WebView2 and VC++ Redistributable runtime verification.

```
+-------------------------------------------------------------------------------+
|                                Frontend (React 19)                            |
|  - Playback Engine (Synchronized Web Audio / Drift Compensation)              |
|  - CanvasWaveform (Full-width accurate peak rendering)                        |
|  - Settings & State Persistence (Model, Device, Export, Bit Depth)            |
|  - Batch Queue & Error Notification Toasts                                    |
+-------------------------------------------------------------------------------+
                                      ▲
                                      │ Tauri v2 IPC (Events & Invocations)
                                      ▼
+-------------------------------------------------------------------------------+
|                              Tauri v2 Rust Backend                            |
|  - Application Lifecycle & Exit Hooks (.on_window_event, ExitRequested)      |
|  - WorkerSupervisor (Process Job Objects, Deadlock-Free IO, UTF-8 Env)        |
|  - Model Directory Mapping (TORCH_HOME, VOCALPRO_MODELS_DIR)                  |
|  - Command Bridge (Batch Error Isolation, Stem Solo/Mute Export Logic)        |
|  - Silent Execution (CREATE_NO_WINDOW on Windows)                             |
+-------------------------------------------------------------------------------+
                                      ▲
                                      │ Line-delimited JSON IPC (stdin/stdout)
                                      ▼
+-------------------------------------------------------------------------------+
|                           Python Worker Pool (Engine)                         |
|  - Windows Compatibility (No Unix-only resource import)                       |
|  - Resampling DSP (soxr_hq replacement for resampy)                           |
|  - Robust Imports (sys, json present for FFmpeg & Video probes)               |
|  - CUDA OOM Recovery (Rebind primary_model across chunk loops)                |
|  - Bundled FFmpeg & Offline Model Cache Discovery                             |
+-------------------------------------------------------------------------------+
```

---

## Feature Inventory
Every feature and failure remediation from the Survey phase is mapped to a specific milestone.

| # | Feature / Remediation | Description | Milestone | Source |
|---|-----------------------|-------------|-----------|--------|
| 1 | Windows-Safe Hardware Module | Guard `import resource` with `platform.system() != "Windows"` and Win32 fallback in `hardware.py` | M1 | Survey 3 |
| 2 | Python Missing Standard Imports | Add `import sys` and `import json` to `engine.py` for FFmpeg resolution & video offset probing | M1 | Survey 3 |
| 3 | Audio Resampling DSP Fix | Switch `res_type="kaiser_fast"` to `res_type="soxr_hq"` in `analysis.py` to eliminate `resampy` crash | M1 | Survey 2 & 3 |
| 4 | PyTorch CUDA OOM Multi-Chunk Rebinding | In `engine.py`, rebind `primary_model = cpu_mdl` across job scope so chunk N+1 doesn't throw device mismatch | M1 | Survey 3 |
| 5 | DSP Golden Fixtures Restoration | Restore missing golden test fixtures so test suite passes 100% cleanly | M1 | Survey 3 |
| 6 | Application Exit Hooks & Window Close | Register `.on_window_event()` and `RunEvent::ExitRequested` in `main.rs` to guarantee process shutdown | M2 | Survey 2 |
| 7 | Zero Zombie Process Lifecycle | Assign Python workers to Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) and Linux `PR_SET_PDEATHSIG` | M2 | Survey 2 |
| 8 | Silent Windows Execution (`CREATE_NO_WINDOW`) | Pass `0x08000000` to all `Command::new` calls (`supervisor.rs`, `audio/decode.rs`, `export.rs`, `system/mod.rs`) | M2 | Survey 1 & 2 |
| 9 | UTF-8 IO Encoding Environment | Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` on worker spawn in `supervisor.rs` for Arabic/Unicode paths | M2 | Survey 1 & 2 |
| 10 | Offline Model Directory Propagation | Set `TORCH_HOME` and `VOCALPRO_MODELS_DIR` in `supervisor.rs` pointing to app data models directory | M2 | Survey 1 & 3 |
| 11 | Startup IPC Pipe Deadlock Prevention | Spawn child stderr listener thread *before* reading stdout handshake line in `supervisor.rs` | M2 | Survey 2 |
| 12 | Batch Separation Fault Isolation | Replace `h.await??` in `commands/mod.rs` with error collection so one bad file doesn't fail entire batch | M2 | Survey 2 |
| 13 | Stem Solo Mix Export Fix | Evaluate `s.solo` in `tauri_bridge.rs` so soloed stems export correctly without unmuted bleed | M2 | Survey 3 |
| 14 | Inno Setup Runtime Prerequisite Checks | Add Pascal checks for WebView2 Evergreen and VC++ 2015-2022 x64 Redistributable in `installer.iss` | M3 | Survey 1 |
| 15 | Inno Setup Asset Bundling & Sanity | Bundle static `ffmpeg.exe`, align model paths, remove `skipifsourcedoesntexist` on critical files | M3 | Survey 1 |
| 16 | Relocatable Python Environment | Fix `pyvenv.cfg` absolute host paths and provide relocatable virtualenv/embedded python configuration | M3 | Survey 1 |
| 17 | Batch Scripts UTF-8 Codepage | Add `chcp 65001 >nul 2>&1` to `setup.bat`, `run.bat`, `Start-VocalPro.bat`, and installer scripts | M3 | Survey 1 |
| 18 | Bundled FFmpeg Discovery | Update `__main__.py` to check adjacent and bundled `ffmpeg.exe` in addition to system PATH | M3 | Survey 1 |
| 19 | Synchronized Multi-Track Playback | Implement Web Audio API / synchronized audio clock with drift compensation across stem tracks | M4 | Survey 3 |
| 20 | Complete Waveform Rendering | Fix step calculation in `CanvasWaveform.tsx` to render full track peaks without truncating last 33% | M4 | Survey 3 |
| 21 | Full Settings State Persistence | Restore model, device, export format, bit depth, bitrate, and naming template on startup in `appStores.ts` | M4 | Survey 3 |
| 22 | Responsive UI Error Notifications | Add toast notifications for individual file batch errors and clear offline model guidance | M4 | Survey 3 |
| 23 | E2E Requirement-Driven Test Suite | Implement comprehensive 4-tier opaque-box test suite verifying all user workflows | M5 (Test Track) | Orchestrator |
| 24 | Adversarial Hardening & Verification | Stress test under corrupted audio, OOM, Arabic paths, network disconnection, and rapid window kill | M5 (Phase 2) | Orchestrator |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Windows Compatibility & Python Worker Engine Core | Features #1, #2, #3, #4, #5 (`hardware.py`, `engine.py`, `analysis.py`, golden fixtures, worker tests) | none | DONE |
| M2 | Tauri v2 Backend, Process Supervision & Robust IPC | Features #6, #7, #8, #9, #10, #11, #12, #13 (`main.rs`, `supervisor.rs`, `commands/`, `tauri_bridge.rs`, cargo tests) | M1 | DONE |
| M3 | Installer, Packaging, Launchers & Runtime Bootstrapping | Features #14, #15, #16, #17, #18 (`installer.iss`, `.github/workflows/release.yml`, batch scripts, FFmpeg discovery) | M1, M2 | DONE |
| M4 | Frontend UI/UX, Playback Synchronization & State Persistence | Features #19, #20, #21, #22 (`CanvasWaveform.tsx`, `appStores.ts`, settings, Web Audio clock, build check) | M2 | DONE |
| M5 | Final Milestone: E2E Test Suite Pass & Adversarial Hardening | Features #23, #24: 58/58 E2E tests, 24/24 Cargo tests, 125/125 Python tests, Adversarial suites | M1, M2, M3, M4 | DONE |

---

## Dual Track: E2E Testing Track
Runs in parallel with Implementation Track:
- **E2E Testing Orchestrator**: Designs requirement-driven opaque-box test suite (Tiers 1–4) covering all features from ORIGINAL_REQUEST.md.
- Outputs `TEST_INFRA.md` and `TEST_READY.md`.
- **Status**: **COMPLETE** (51/51 tests passing across Tiers 1-4; `TEST_READY.md` published at project root).

---

## Interface Contracts

### 1. Tauri Backend ↔ Python Worker IPC Contract
- **Protocol**: Line-delimited JSON over `stdin` (requests) and `stdout` (responses/progress), `stderr` (logging/diagnostics).
- **Environment Guarantee**: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `TORCH_HOME=<localappdata>/VocalPro`, `VOCALPRO_MODELS_DIR=<localappdata>/VocalPro/models`.
- **Termination Guarantee**: Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) on Windows; `prctl(PR_SET_PDEATHSIG, SIGTERM)` on Linux. On exit, all child processes are killed instantly.
- **Request Format**: `{"id": "<uuid>", "cmd": "separate"|"analyze"|"ping"|"cancel", "payload": { ... }}\n`
- **Response Format**: `{"id": "<uuid>", "status": "ok"|"error", "data": { ... }, "error": { "code": "...", "message": "..." } }\n`

### 2. Frontend ↔ Tauri Backend Bridge Contract
- **Commands**: `separate_stems`, `cancel_task`, `analyze_audio`, `export_mix`, `get_app_settings`, `save_app_settings`.
- **Batch Processing**: Returns per-track status records `Vec<TrackResult>` where `TrackResult = { id, status: "completed"|"failed", error: Option<String>, stems: Option<Vec<Stem>> }` so single file errors do not invalidate the batch.
- **Mix Export**: Evaluates `s.solo` state: if any stem is soloed, only soloed unmuted stems are exported.

---

## Code Layout
- `worker/vocalpro_worker/`: Python engine, models, DSP routines, IPC entrypoint.
- `src-tauri/src/`: Rust backend, process supervisor, audio decoders/exporters, Tauri commands.
- `src/`: React 19 frontend, UI state (`src/state/appStores.ts`), components, audio playback.
- `scripts/`, `installer.iss`, `.github/workflows/`: Packaging, installers, CI release automation.
- `benchmarks/`, `tests/`: Reference sets, unit tests, integration test suites.
