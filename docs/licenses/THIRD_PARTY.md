# VocalPro v3 — Third-Party Licenses & Software Bill of Materials (SBOM)

This document catalogs every open-source library, crate, engine component, and model architecture bundled, linked, or consumed by VocalPro v3.0.0.

---

## 1. Rust Core Engine & Desktop Shell (`src-tauri/`)

| Crate | Version | License | Upstream Repository | Purpose in VocalPro |
|---|---|---|---|---|
| `symphonia` | `0.5.4` | MPL-2.0 | `https://github.com/pdeljanov/Symphonia` | Native audio decoding (MP3, FLAC, WAV, OGG, AAC) and fast waveform extraction. |
| `rubato` | `0.16.1` | LGPL-3.0-or-later | `https://github.com/HEnquist/rubato` | High-quality sinc and polynomial audio resampling. |
| `hound` | `3.5.1` | Apache-2.0 | `https://github.com/ruuda/hound` | High-performance 16-bit, 24-bit, and 32-bit float WAV reading and writing. |
| `rusqlite` | `0.32.1` | MIT | `https://github.com/rusqlite/rusqlite` | SQLite database client for settings, history, and outputs with WAL journaling. |
| `tokio` | `1.42` | MIT | `https://github.com/tokio-rs/tokio` | Async runtime for multi-process worker supervisor and IPC channels. |
| `serde` & `serde_json` | `1.0` | MIT / Apache-2.0 | `https://github.com/serde-rs/serde` | JSON serialization/deserialization for worker protocol and config. |
| `sysinfo` | `0.40.1` | MIT | `https://github.com/GuillaumeGomez/sysinfo` | Cross-platform RAM, CPU core count, and system metrics inspection. |
| `sha2` | `0.10.8` | MIT / Apache-2.0 | `https://github.com/RustCrypto/hashes` | SHA-256 fingerprinting for model weights and hardware profiles. |
| `dirs` | `5.0` | MIT / Apache-2.0 | `https://github.com/soc/dirs-rs` | Platform-standard configuration and data directory resolution. |
| `tracing` & `subscriber` | `0.1` | MIT | `https://github.com/tokio-rs/tracing` | Structured application logging. |

---

## 2. Python Worker & Separation Engine (`worker/`)

| Package | Pinned Target | License | Upstream Repository | Purpose in VocalPro |
|---|---|---|---|---|
| `torch` | `>= 2.0.0` | BSD-3-Clause | `https://github.com/pytorch/pytorch` | Deep learning tensor engine and CUDA GPU acceleration. |
| `demucs` | `>= 4.0.1` | MIT | `https://github.com/facebookresearch/demucs` | Hybrid Transformer Demucs (`htdemucs`, `htdemucs_ft`, `htdemucs_6s`) separation architecture. |
| `soundfile` | `>= 0.12.1` | BSD-3-Clause | `https://github.com/bastibe/python-soundfile` | Audio file I/O wrapper for `libsndfile`. |
| `librosa` | `>= 0.10.1` | ISC | `https://github.com/librosa/librosa` | STFT analysis, pitch extraction (`pyin`), and harmonic-percussive separation (`hpss`). |
| `scipy` | `>= 1.11.0` | BSD-3-Clause | `https://github.com/scipy/scipy` | Butterworth filter design and zero-phase SOS filtering (`sosfiltfilt`). |
| `numpy` | `>= 1.24.0` | BSD-3-Clause | `https://github.com/numpy/numpy` | Fast N-dimensional audio buffer math. |
| `noisereduce` | `>= 3.0.0` | MIT | `https://github.com/timsainb/noisereduce` | Spectral noise reduction for vocal isolation. |

---

## 3. Web UI & Frontend (`src/`)

| Package | Version | License | Upstream Repository | Purpose in VocalPro |
|---|---|---|---|---|
| `react` | `^19.0.0` | MIT | `https://github.com/facebook/react` | Core user interface component library. |
| `react-dom` | `^19.0.0` | MIT | `https://github.com/facebook/react` | DOM renderer for React. |
| `lucide-react` | `^0.460.0` | ISC | `https://github.com/lucide-icons/lucide` | Studio audio icons (faders, waveforms, speakers, knobs). |
| `tailwindcss` | `^3.4.15` | MIT | `https://github.com/tailwindlabs/tailwindcss` | Utility-first CSS styling and layout engine. |
| `vite` | `^6.0.1` | MIT | `https://github.com/vitejs/vite` | Fast frontend bundler and dev server. |
| `zustand` | `^5.0.1` | MIT | `https://github.com/pmndrs/zustand` | Reactive state management for job queue, mixer strips, and settings. |

---

## 4. Pretrained AI Model Weights

- **HTDemucs Models (`htdemucs`, `htdemucs_ft`, `htdemucs_6s`, `hdemucs_mmi`):**
  - **Author:** Alexandre Défossez et al., Meta AI Research.
  - **License:** Creative Commons Attribution-NonCommercial 4.0 International (`CC BY-NC 4.0`).
  - **Verification:** Downloaded via `vocalpro_worker.model_installer` and verified against published SHA-256 signatures before use.
- **MDX Models (`mdx`, `mdx_extra`, `mdx_q`, `mdx_extra_q`):**
  - **Author:** Demucs team / KUIELab.
  - **License:** MIT / CC BY-NC 4.0.

---

## 5. Reference Audio Test Suite (`benchmarks/reference-real/`)

Every reference audio excerpt used in the quality evaluation is freely licensed under Creative Commons or Public Domain. No copyrighted music is stored in the repository. Full details in `benchmarks/reference-real/MANIFEST.json`:

1. **`real_01` ("The Shelby Blues" by David Mumford):** `CC BY 4.0`
2. **`real_02` ("The Vistas Missing Views" by The Rope River Blues Band):** `CC BY 3.0 US`
3. **`real_03` ("Rainy Weather Blues" by Bessie Smith):** `Public Domain` (1920s historical recording)
4. **`real_04` ("Skyscrapers" by Airmen of Note, US Air Force Band):** `Public Domain`
5. **`real_05` ("Friendly Evil Gangsta Synth Hip Hop"):** `CC0 1.0 Universal` (Public Domain Dedication)
