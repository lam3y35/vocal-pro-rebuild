# VocalPro v3 — Project Sentinel Guide & Architecture

## Overview
**VocalPro v3** is a native, offline-first Studio AI Audio & Movie Stem Separation Workstation for Windows (and cross-platform), built with:
- **Core Desktop Runtime:** Tauri v2 + Native Rust backend (`src-tauri/`)
- **Frontend / DAW UI:** React 19 + TypeScript + Vite + Tailwind CSS (`src/`)
- **AI Separation Engine:** Multi-process Python worker pool over stdio JSON-Lines (`worker/`), leveraging PyTorch and Demucs (`htdemucs`, `htdemucs_ft`, `htdemucs_6s`, `mdx_extra_q`).
- **Database & Persistence:** SQLite WAL (`src-tauri/src/db/`) for jobs, presets, history, and outputs.

---

## Architectural Breakdown

### 1. Tauri v2 Desktop Bridge (`src-tauri/`)
- `src/main.rs`: Application entrypoint, system tray, single instance lock, window lifecycle.
- `src/commands/`: Strongly-typed IPC handlers bridging frontend commands to backend engines:
  - `pick_audio_files`, `open_folder`, `resolve_ffmpeg_path`, `download_media_url`, `start_batch_separation`, etc.
- `src/audio/`:
  - `decode.rs`: Fast, zero-allocation native audio decoding and waveform extraction via Symphonia (< 300ms).
  - `export.rs`: Multi-track 6-band live stem mixer export (WAV 16/24/32-bit float, MP3, FLAC).
  - `video.rs`: Cinema studio engine; sample-accurate audio demuxing, video stream passthrough, and remuxing without re-encoding video.
- `src/worker/`: Supervisor managing multi-process AI worker pool (`supervisor.rs`), heartbeats, and graceful cancellation.

### 2. Frontend DAW Workstation (`src/`)
- `screens/`:
  - `SeparationScreen.tsx`: Batch queue, persistent drag-and-drop zone (songs & cinema movies), model selection, DSP controls, media downloader.
  - `ResultsScreen.tsx`: Real-time 6-track stem mixer (Solo, Mute, Volume, Pan, EQ, Reverb, Speed, Pitch), waveform scrubbing.
  - `HistoryScreen.tsx`: Persistent separation and media download history with direct send-to-mixer workflow.
  - `SettingsScreen.tsx`: Hardware intelligence calibration, auto-optimizer, audio quality, and system settings.
  - `HomeScreen.tsx`: System overview, hardware status, and quick-start actions.
- `state/appStores.ts`: Zustand stores (`useJobsStore`, `useMixerStore`, `useLibraryStore`, `useSystemStore`).

---

## Key Workflows & Guidelines
1. **Persistent Drag & Drop:**
   Users can drag audio or video files into the queue at any time, even when the queue already contains items.
2. **Notification Management:**
   Global `systemBanner` notifications in `App.tsx` auto-dismiss after 4.5 seconds and do not duplicate across screens.
3. **100% Offline & Private:**
   No telemetry or audio data leaves the local machine. All processing is on-device.

---

## Testing & Verification
- **Rust Integration Tests:**
  `cargo test --test integration_tests` inside `src-tauri/`
- **Frontend Typecheck & Build:**
  `npx tsc --noEmit` and `npx vite build`
- **Python Worker Regressions:**
  `pytest worker/tests/test_regressions_p01_p19.py`
