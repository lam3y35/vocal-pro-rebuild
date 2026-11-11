# VocalPro v3.0.0 — E2E Test Infrastructure Specification

## 1. Overview & Testing Philosophy

VocalPro v3.0.0 requires an exhaustive, resilient, opaque-box end-to-end testing infrastructure. The primary objective is to verify that the application satisfies all user requirements and operates with zero points of failure under both standard and adversarial conditions.

### Core Testing Tenets
1. **Opaque-Box Verification**: The test suite treats the VocalPro system strictly as an external executable and IPC protocol server. Tests do NOT monkey-patch internals, mock private functions, or rely on internal module state. All interactions occur via:
   - Command-line arguments and process invocations (`vocalpro_worker`, Tauri backend CLI).
   - Line-delimited JSON IPC messages over `stdin`, `stdout`, and `stderr`.
   - File system input and output artifacts (audio stems, video containers, MIDI files, SQLite database files).
   - Operating system process lifecycle signals and exit status codes.
2. **Requirement-Driven**: Every test case directly derives from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory`.
3. **Reproducibility & Zero Dependency on Live Internet**: All models, reference files, and test fixtures are generated deterministically or resolved from local offline caches (`TORCH_HOME`, `VOCALPRO_MODELS_DIR`).
4. **4-Tier Comprehensive Coverage**:
   - **Tier 1**: Core Feature Functional Coverage (>= 5 tests per core feature).
   - **Tier 2**: Boundary, Edge & Corner Cases (>= 5 tests per boundary category).
   - **Tier 3**: Cross-Feature Combinations & Concurrency (Pairwise and stress combinations).
   - **Tier 4**: Real-World User Journeys & Studio Workflows.

---

## 2. Directory Structure & Layout

The E2E testing framework is structured under `tests/e2e/`:

```
vocal-pro-rebuild/
├── tests/
│   ├── e2e/
│   │   ├── conftest.py                # Pytest fixtures, sandbox creation, test audio generator
│   │   ├── harness/
│   │   │   ├── __init__.py
│   │   │   ├── ipc_client.py          # Opaque-box Line-Delimited JSON IPC Client
│   │   │   ├── audio_validator.py     # Independent audio/stem/MIDI verification utilities
│   │   │   └── process_monitor.py     # Process tree, signal, and memory verification
│   │   ├── test_tier1_features.py     # Tier 1: Separation, Analysis, Models, Export, Lifecycle
│   │   ├── test_tier2_boundaries.py   # Tier 2: 0-byte, corrupt, extreme durations, Arabic paths, OOM
│   │   ├── test_tier3_combinations.py # Tier 3: Mixed batches, cancel-and-switch, concurrent ops
│   │   ├── test_tier4_scenarios.py    # Tier 4: Studio mastering, Karaoke remix, Vocal-to-MIDI, Album queue
│   │   └── run_e2e.py                 # Standalone unified CLI runner and report generator
├── TEST_INFRA.md                      # This specification
└── TEST_READY.md                      # Verification sign-off document
```

---

## 3. Opaque-Box Test Harness Details

### 3.1 IPC Protocol Client (`harness/ipc_client.py`)
- Spawns the worker subprocess using `worker/.venv/bin/python -m vocalpro_worker`.
- Establishes communication strictly over `stdin` (requests) and `stdout` (line-delimited JSON events and responses).
- Monitors `stderr` concurrently for diagnostic logs.
- Features:
  - Synchronous request/response dispatch with configurable timeouts.
  - Asynchronous event streaming (listening for `progress`, `status`, `stage` updates).
  - Cooperative cancellation dispatch (`cmd: cancel`).
  - Strict schema validation against the official IPC contract:
    - Request: `{"id": "<uuid>", "cmd": "<cmd>", "payload": { ... }}`
    - Response: `{"id": "<uuid>", "status": "ok"|"error", "data": { ... }, "error": { "code": "...", "message": "..." }}`

### 3.2 Audio & Artifact Validator (`harness/audio_validator.py`)
- Independently inspects output files using standard libraries (`soundfile`, `wave`, `scipy.io.wavfile`).
- Validates:
  - Header integrity, codec format, sample rate, bit depth (PCM 16, PCM 24, Float 32).
  - Channel count (mono, stereo).
  - Duration parity (ensuring stem duration matches original source audio).
  - RMS level, peak level (dBFS), clipping check (no un-normalized overflow).
  - Null test (summing complementary separated stems to verify reconstruction phase alignment).
  - Standard MIDI File (SMF 1.0) header verification and MIDI note track parsing.
  - Video remuxing validation (MP4/MKV video stream intact with replaced audio track).

### 3.3 Process & Lifecycle Monitor (`harness/process_monitor.py`)
- Verifies process tree health using `psutil`.
- Confirms child process cleanup on job completion or cancellation (zero zombie processes).
- Verifies worker responsiveness to OS signals (`SIGTERM`, `SIGINT`).
- Monitors RSS memory usage and verifies bounded memory consumption during large chunked audio processing.

---

## 4. 4-Tier Test Matrix

| Tier | Category / Feature | Test ID | Description | Target Signal |
|------|-------------------|---------|-------------|---------------|
| **Tier 1** | Separation | `T1_SEP_01` | 2-stem vocal/instrumental separation | Vocals + Instrumental stems created and valid |
| **Tier 1** | Separation | `T1_SEP_02` | 4-stem htdemucs separation | 4 stems (vocals, drums, bass, other) verified |
| **Tier 1** | Separation | `T1_SEP_03` | 6-stem htdemucs_6s separation | 6 stems (vocals, drums, bass, guitar, piano, other) |
| **Tier 1** | Separation | `T1_SEP_04` | Multi-format decoding (WAV, MP3, FLAC, OGG, M4A) | Audio decoded and separated cleanly |
| **Tier 1** | Separation | `T1_SEP_05` | Video container audio extraction (MP4, MKV) | Audio extracted from video container and processed |
| **Tier 1** | Analysis | `T1_ANA_01` | Musical key and BPM tempo estimation | BPM and key returned in data payload |
| **Tier 1** | Analysis | `T1_ANA_02` | Dynamic range, RMS, and peak level calculation | Valid float metrics within expected acoustic range |
| **Tier 1** | Analysis | `T1_ANA_03` | Fast waveform peak generation (8000 points) | Full normalized peak array returned without truncation |
| **Tier 1** | Analysis | `T1_ANA_04` | Audio duration and channel format detection | Accurate duration and channel metadata |
| **Tier 1** | Analysis | `T1_ANA_05` | Spectral centroid and pitch tracking | Valid pitch contour and frequency statistics |
| **Tier 1** | Model Mgmt | `T1_MDL_01` | Model registry enumeration | All 8 supported models enumerated |
| **Tier 1** | Model Mgmt | `T1_MDL_02` | Offline model cache discovery (`TORCH_HOME`) | Local model checkpoint resolved without network |
| **Tier 1** | Model Mgmt | `T1_MDL_03` | Persistent worker model caching across jobs | Second job reuses warm in-memory model |
| **Tier 1** | Model Mgmt | `T1_MDL_04` | Device selection (CPU vs CUDA auto-fallback) | Device binding conforms to system capability |
| **Tier 1** | Model Mgmt | `T1_MDL_05` | Missing/invalid model error handling | Returns structured error code `MODEL_NOT_FOUND` |
| **Tier 1** | Export & Mix | `T1_EXP_01` | Stem solo mix export | Only soloed stem is exported, unmuted stems silenced |
| **Tier 1** | Export & Mix | `T1_EXP_02` | Multi-stem mix with custom volume and pan | Stereo mix exported with accurate balance |
| **Tier 1** | Export & Mix | `T1_EXP_03` | Multi-format bit depth export (16-bit, 24-bit, 32f) | Accurate bit depth in exported WAV headers |
| **Tier 1** | Export & Mix | `T1_EXP_04` | Compressed export formats (MP3 320k, FLAC, OGG) | Valid compressed audio containers created |
| **Tier 1** | Export & Mix | `T1_EXP_05` | Output stem deduplication and file naming | File naming adheres to template without overwriting |
| **Tier 1** | Lifecycle | `T1_CAN_01` | Cancellation under active inference (< 500ms) | Subprocess halts inference within 500ms of cancel |
| **Tier 1** | Lifecycle | `T1_CAN_02` | Temporary file cleanup on cancellation | No dangling partial stem files left on disk |
| **Tier 1** | Lifecycle | `T1_CAN_03` | Worker process reuse after cancellation | Worker immediately accepts next job after cancel |
| **Tier 1** | Lifecycle | `T1_CAN_04` | Process tree shutdown signal (`PR_SET_PDEATHSIG`) | Worker terminates when parent process exits |
| **Tier 1** | Lifecycle | `T1_CAN_05` | JSON IPC ping/pong handshake & keepalive | Responds immediately with status `ok` to ping |
| **Tier 2** | Boundaries | `T2_BND_01` | 0-byte audio file input | Structured error `DECODE_FAILED` / `EMPTY_FILE`, no crash |
| **Tier 2** | Boundaries | `T2_BND_02` | Corrupted audio header / truncated file | Structured error `DECODE_FAILED`, no segfault |
| **Tier 2** | Boundaries | `T2_BND_03` | Ultra-short audio clip (< 0.25s) | Handles short audio padding gracefully |
| **Tier 2** | Boundaries | `T2_BND_04` | Large multi-chunk audio (> 5 minutes) | Seamless chunk recombination with no boundary clicks |
| **Tier 2** | Boundaries | `T2_BND_05` | Digital silence (0.0 amplitude) | No division-by-zero, NaN, or inf in DSP outputs |
| **Tier 2** | Boundaries | `T2_BND_06` | Max amplitude clipped audio (0 dBFS square/sine) | No integer wrap or distortion overflow |
| **Tier 2** | Path/Unicode | `T2_PTH_01` | Arabic and RTL Unicode filenames (`موسيقى_2026.wav`) | Stems written cleanly with accurate UTF-8 names |
| **Tier 2** | Path/Unicode | `T2_PTH_02` | Deeply nested directory path (> 200 characters) | Deep path created and file accessible |
| **Tier 2** | Path/Unicode | `T2_PTH_03` | Special characters, spaces, and punctuation in path | Escaping handled cleanly without shell injection |
| **Tier 2** | Path/Unicode | `T2_PTH_04` | Read-only output directory | Structured error `IO_ERROR`, graceful failure |
| **Tier 2** | Path/Unicode | `T2_PTH_05` | Input file deleted prior to processing | Structured error `FILE_NOT_FOUND`, no unhandled exception |
| **Tier 2** | Resource/OOM | `T2_RES_01` | Simulated CUDA OOM fallback to CPU | Switches to CPU model seamlessly without job failure |
| **Tier 2** | Resource/OOM | `T2_RES_02` | Multi-chunk memory leak verification | RSS memory remains flat across consecutive chunk loops |
| **Tier 2** | Resource/OOM | `T2_RES_03` | Unusual channel layouts (mono, 5.1 surround) | Converted to stereo or processed per channel map |
| **Tier 2** | Resource/OOM | `T2_RES_04` | Non-standard sample rates (8kHz, 22.05kHz, 96kHz, 192k) | Resampled accurately with `soxr_hq` |
| **Tier 3** | Combinations | `T3_CMB_01` | Mixed-format batch with corrupt file fault isolation | Valid files succeed, corrupt file reports error |
| **Tier 3** | Combinations | `T3_CMB_02` | Rapid cancel mid-inference followed by new job | Worker terminates first job and starts second cleanly |
| **Tier 3** | Combinations | `T3_CMB_03` | Separation with custom shifts + overlap + solo export | Full pipeline integration from inference to export |
| **Tier 3** | Combinations | `T3_CMB_04` | Audio analysis executed concurrently with separation | Both commands execute without pipe deadlock |
| **Tier 3** | Combinations | `T3_CMB_05` | Rapid process startup, job submission, and kill | No orphan child processes left in process table |
| **Tier 3** | Combinations | `T3_CMB_06` | Arabic path + 6-stem model + 24-bit FLAC export | Full Unicode stress test across model, DSP, and export |
| **Tier 4** | Real-World | `T4_SCN_01` | Studio Mastering Workflow: Full pop song 4-stem separation | Complete stems + waveform peaks + 24-bit master export |
| **Tier 4** | Real-World | `T4_SCN_02` | Karaoke Producer Workflow: Video -> stem extraction -> remux | Video output created with vocal eliminated |
| **Tier 4** | Real-World | `T4_SCN_03` | Musician / Transcriber Workflow: Vocal -> MIDI transcription | Valid SMF 1.0 MIDI file generated with note events |
| **Tier 4** | Real-World | `T4_SCN_04` | Album Batch Production Workflow: Multi-track queue | Comprehensive batch status report with per-track timings |
| **Tier 4** | Real-World | `T4_SCN_05` | Air-Gapped Offline Operation: Full run without internet | Validates local model discovery and zero network calls |

---

## 5. Test Execution & Reporting

The test suite can be run via:
```bash
# Full E2E suite with detailed summary report
worker/.venv/bin/python tests/e2e/run_e2e.py

# Or via pytest directly
worker/.venv/bin/pytest tests/e2e/ -v
```

The runner produces:
1. Console real-time pass/fail stream with timing and tier metrics.
2. Structured report: `tests/e2e/e2e_report.json`.
3. Human-readable markdown summary: `tests/e2e/E2E_REPORT.md`.
