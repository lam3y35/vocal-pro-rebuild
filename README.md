# VocalPro v3.0.0 — Native Rust + React 19 + Stdio AI Worker Rebuild

VocalPro v3.0.0 is an end-to-end architectural rebuild of [lam3y35/vocal-pro](https://github.com/lam3y35/vocal-pro), engineered for speed, reliability, offline execution, and **100% feature and DSP audio quality parity**.

---

## 📥 تحميل البرنامج للمستخدم النهائي (Download for Windows Users)

إذا كنت مستخدماً وتريد تشغيل البرنامج مباشرة دون الحاجة لأي أدوات برمجية:

* 📦 **[تحميل حزمة الويندوز الجاهزة (VocalPro-v3.0.0-Windows.zip - 4.9 MB)](https://github.com/lam3y35/vocal-pro-rebuild/raw/main/release/VocalPro-v3.0.0-Windows.zip)**
* 🚀 **طريقة التشغيل:** بعد التحميل، قم بفك ضغط الملف واضغط مرتين على `vocalpro.exe` وسيعمل البرنامج فوراً.
* 📂 **تصفح مجلد الإصدار:** يمكنك أيضاً الاطلاع على [مجلد release](release/) للحصول على ملف الـ `.exe` المنفرد وتعليمات التشغيل.

---

## 💻 دليل المطورين السريع (Developer Quickstart)

إذا كنت مطوراً وتريد تشغيل المشروع من الكود المصدري والمساهمة فيه:

### 1. المتطلبات (Prerequisites):
* **Node.js**: الإصدار 20 أو 22 LTS (`npm` أو `pnpm`)
* **Rust**: أحدث إصدار ثابت (`cargo` & `rustc`)
* **Python**: 3.10 أو 3.11 مع تثبيت `torch`, `demucs`, `soundfile`, `scipy`, `librosa`

### 2. التثبيت والتشغيل المحلي (Setup & Dev):
```bash
# تثبيت حزم واجهة المستخدم
npm install

# تشغيل التطبيق في وضع التطوير (Tauri Desktop Shell + React Hot Reload)
npm run tauri dev

# أو تشغيل واجهة الويب فقط للتعديل السريع:
npm run dev
```

### 3. تشغيل الاختبارات الشاملة (Run Tests):
```bash
# اختبارات بايثون ومحرك الذكاء الاصطناعي واختبارات التطابق الرياضي (Golden Null Tests):
pytest worker/tests -v

# اختبارات محرك الرست (Rust Core Integration Tests):
cargo test --manifest-path src-tauri/Cargo.toml

# فحص أنواع TypeScript وبناء الواجهة:
npm run build
```

---

## Highlights & Architectural Improvements

1. **Zero Localhost Ports (N4):** Replaces the legacy FastAPI HTTP/WebSocket server on port `8765` with a persistent, supervised Python AI worker communicating over **length-delimited JSON Lines (`stdio` JSONL)** with OS-level stdout descriptor duplication (`os.dup(1)` + `os.dup2(2, 1)`) so library chatter never corrupts the protocol.
2. **Real Per-Segment Progress & `<500 ms` Cooperative Cancellation (N5):** Hooks directly into `demucs.apply.apply_model(..., callback=...)` with bit-for-bit identical output (`0.0` max absolute difference) and measured `0.063 ms` (`63 µs`) cancellation latency.
3. **100% Feature Parity + File Settings Preserved (N1):**
   - All **8 separation models** (`htdemucs`, `htdemucs_ft`, `htdemucs_6s`, `hdemucs_mmi`, `mdx`, `mdx_extra`, `mdx_q`, `mdx_extra_q`) + **Ensemble mode** (`htdemucs_ft` + `mdx_extra` blend).
   - All **3 separation modes** (`vocals`, `background`, `karaoke`) and **7 quality presets** (`fast`, `balanced`, `high`, `ultra`, `6stem`, `karaoke_pro`, `ensemble`).
   - All **11 post-processing DSP functions** (`separate_sfx`, `spectral_denoise`, `apply_vocal_gate`, `restore_high_frequencies`, `normalize_loudness`, `smooth_crossfade_chunks`, `post_process_vocals`, `post_process_background`, `mix_sfx_into_background`, `reduce_noise`, `enhance_vocals`) verified at `0.0` float64 difference against the legacy reference set.
   - All **file-related settings and capabilities**: Windows file associations (`register_file_associations`), desktop shortcut creation (`create_desktop_shortcut`), multi-file batch queue with per-file progress, drag-and-drop import, video extraction + remuxing (`video_with_separated_audio.mp4`), comparison sample snippet generator (`comparison_samples/`), Stem-to-MIDI (`librosa.pyin`), and all 16 UI languages (including Arabic RTL).
4. **Native Rust Audio Engine (`symphonia` + `hound`) (N8):**
   - 8,000-point waveform extraction in **4.8 ms** (down from ~850 ms in Python).
   - Live in-memory stem mixer with solo/mute/gain/pan and multi-format export (`wav`, `flac`, `mp3`, `ogg`).
5. **Automatic Legacy Data Migration (`SQLite WAL`) (N9):**
   - Automatically imports `~/.vocalpro_config.json`, `~/.vocal_remover_pro_config.json`, `%APPDATA%/VocalPro/config.json`, `separation_history.json`, `download_history.json`, and scans legacy `output_vocals/` folders on first launch while backing up originals to `*.bak`.

---

## Repository Structure

```text
vocal-pro-rebuild/
├── docs/
│   ├── adr/                          # Architecture Decision Records (0001..0004)
│   ├── migration/                    # Legacy JSON & output directory migration specs
│   └── parity/
│       ├── matrix.md                 # Expanded 86-row Feature Parity Matrix [V]
│       └── phase0-report.md          # Complete Phase 0 Audit & Verification Report
├── schemas/
│   └── worker-protocol.schema.json   # Versioned v1 Rust <-> Python JSONL protocol schema
├── benchmarks/
│   ├── generate_reference_set.py     # Deterministic reference audio/video generator
│   ├── run_old_engine.py             # Legacy baseline runner & Demucs callback spike
│   ├── null_test.py                  # Golden null-test & SDR verification harness
│   └── baseline/metrics.json         # Recorded baseline & spike metrics
├── worker/
│   ├── pyproject.toml
│   ├── vocalpro_worker/              # Python AI & DSP stdio worker package
│   │   ├── protocol.py               # OS-level stdout isolation & JSONL framing
│   │   ├── dsp.py                    # Bit-exact port of audio_postprocess.py
│   │   ├── analysis.py               # BPM, musical key, and 8,000-point waveform
│   │   ├── midi.py                   # librosa.pyin pitch tracking & SMF Format-0 MIDI
│   │   ├── engine.py                 # Demucs separation, chunking, and post-processing
│   │   └── __main__.py               # Main stdio event loop
│   └── tests/                        # Pytest suite (golden null-tests, engine, protocol)
├── src-tauri/                        # Rust core (SQLite WAL, worker supervisor, native audio)
│   ├── Cargo.toml
│   ├── src/
│   │   ├── audio/                    # symphonia decode, waveform, live mixer, export
│   │   ├── db/                       # SQLite WAL store & legacy JSON/folder migration
│   │   ├── worker/                   # Process supervisor, job queue, typed protocol
│   │   ├── models/                   # SHA-256 verified model manager
│   │   ├── system/                   # GPU detection, Windows file assoc & shortcuts
│   │   └── commands/                 # Typed IPC command handlers
│   └── tests/                        # Rust integration tests
└── src/                              # React 19 + TypeScript + Tailwind + Zustand frontend
    ├── bindings.ts                   # End-to-end typed contracts
    ├── i18n/translations.ts          # 16 languages with RTL support
    ├── state/appStores.ts            # Split stores (UI, Jobs, Library, Settings)
    ├── components/                   # CanvasWaveform, StemMixerStrip, JobQueueBar, Sidebar
    └── screens/                      # Home, Separation, Results, History, Settings
```

---

## Verification & Testing

### 1. Python AI Worker & Golden Null-Tests
```bash
pytest worker/tests -v
```

### 2. Rust Core Integration Tests (Migration, Native Waveform, Live Mixer, Supervisor E2E)
```bash
cargo test --manifest-path src-tauri/Cargo.toml
```

### 3. Frontend TypeScript & Production Bundle Build
```bash
pnpm build
```
