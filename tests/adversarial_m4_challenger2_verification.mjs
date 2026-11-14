import assert from "node:assert";

// ============================================================================
// SUITE 1: Settings Persistence Round-Trip & Schema Parity (Feature 21)
// ============================================================================
console.log("=== Running Suite 1: Settings Persistence & Schema Parity ===");

// 1. Default Job Options (from appStores.ts)
const DEFAULT_JOB_OPTIONS = {
  model: "htdemucs",
  device: "auto",
  output_mode: "four_stems",
  output_format: "mp3",
  wav_bit_depth: "PCM_16",
  audio_bitrate: "320k",
  output_all_stems: false,
  output_video: true,
  video_output_mode: "video_only",
  delete_input_file: false,
  shifts: 1,
  overlap: 0.25,
  segment: 7.8,
  fp16_inference: true,
  ensemble_mode: false,
  song_mode: false,
  trim_silence: true,
  enable_vocal_gate: true,
  gate_threshold_db: -55.0,
  gate_floor_db: -60.0,
  denoise_strength: 0.55,
  min_vocal_duration: 0.08,
  enable_multiband_denoise: false,
  enable_sfx_separation: false,
  save_background_track: false,
  karaoke_mode: false,
  enable_hf_restore: true,
  hf_boost_db: 3.0,
  enable_loudness_normalize: true,
  enable_spectral_denoise: true,
};

// 2. Mock SQLite Settings Database Engine
class MockSqliteSettingsDb {
  constructor() {
    this.store = new Map(); // key -> { value_json, updated_at }
  }

  updateSettings(patch) {
    const now = new Date().toISOString();
    for (const [k, v] of Object.entries(patch)) {
      this.store.set(k, { value_json: JSON.stringify(v), updated_at: now });
    }
  }

  getAllSettings(defaultConfigMap = {}) {
    const result = { ...defaultConfigMap };
    for (const [k, entry] of this.store.entries()) {
      try {
        result[k] = JSON.parse(entry.value_json);
      } catch {
        result[k] = entry.value_json;
      }
    }
    return result;
  }
}

// 3. Mock Store Environment replicating appStores.ts logic
class MockVocalProAppStore {
  constructor(db) {
    this.db = db;
    this.jobsStore = {
      options: { ...DEFAULT_JOB_OPTIONS },
      customOutputDir: "",
      parallelWorkers: 2,
      autoOpenFolder: true,
    };
    this.systemStore = {
      locale: "en",
      theme: "dark",
      uiScale: 100,
      highContrast: false,
      reducedMotion: false,
      alwaysOnTop: false,
      minimizeToTray: false,
      onboardingDone: false,
      namingTemplate: "{track_name}_{stem}",
      conflictPolicy: "overwrite",
      preserveFolderStructure: false,
      maxCacheSizeGb: 10,
      activeProfileMode: "Balanced",
      systemBanner: null,
    };
    this.mixerStore = {
      exportFormat: "mp3",
      exportBitrate: "320k",
    };
  }

  // Exact setOptions logic from appStores.ts:127-178
  setOptions(patch) {
    this.jobsStore.options = { ...this.jobsStore.options, ...patch };
    const settingsPatch = {};
    if (patch.model !== undefined) settingsPatch.model_name = patch.model;
    if (patch.device !== undefined) settingsPatch.device = patch.device;
    if (patch.output_mode !== undefined) settingsPatch.output_mode = patch.output_mode;
    if (patch.output_format !== undefined) settingsPatch.output_format = patch.output_format;
    if (patch.wav_bit_depth !== undefined) settingsPatch.wav_bit_depth = patch.wav_bit_depth;
    if (patch.audio_bitrate !== undefined) {
      settingsPatch.audio_bitrate = patch.audio_bitrate;
      settingsPatch.mp3_bitrate = patch.audio_bitrate;
    }
    if (patch.output_all_stems !== undefined) settingsPatch.output_all_stems = patch.output_all_stems;
    if (patch.output_video !== undefined) settingsPatch.output_video = patch.output_video;
    if (patch.video_output_mode !== undefined) settingsPatch.video_output_mode = patch.video_output_mode;
    if (patch.delete_input_file !== undefined) settingsPatch.delete_input_file = patch.delete_input_file;
    if (patch.shifts !== undefined) settingsPatch.shifts = patch.shifts;
    if (patch.overlap !== undefined) settingsPatch.overlap = patch.overlap;
    if (patch.segment !== undefined) settingsPatch.segment = patch.segment;
    if (patch.fp16_inference !== undefined) settingsPatch.fp16_inference = patch.fp16_inference;
    if (patch.ensemble_mode !== undefined) settingsPatch.ensemble_mode = patch.ensemble_mode;
    if (patch.song_mode !== undefined) settingsPatch.song_mode = patch.song_mode;
    if (patch.trim_silence !== undefined) settingsPatch.trim_silence = patch.trim_silence;
    if (patch.enable_vocal_gate !== undefined) settingsPatch.enable_vocal_gate = patch.enable_vocal_gate;
    if (patch.gate_threshold_db !== undefined) settingsPatch.gate_threshold_db = patch.gate_threshold_db;
    if (patch.gate_floor_db !== undefined) settingsPatch.gate_floor_db = patch.gate_floor_db;
    if (patch.denoise_strength !== undefined) settingsPatch.denoise_strength = patch.denoise_strength;
    if (patch.min_vocal_duration !== undefined) settingsPatch.min_vocal_duration = patch.min_vocal_duration;
    if (patch.enable_multiband_denoise !== undefined) {
      settingsPatch.enable_multiband_denoise = patch.enable_multiband_denoise;
    }
    if (patch.enable_sfx_separation !== undefined) {
      settingsPatch.enable_sfx_separation = patch.enable_sfx_separation;
    }
    if (patch.save_background_track !== undefined) {
      settingsPatch.save_background_track = patch.save_background_track;
    }
    if (patch.karaoke_mode !== undefined) settingsPatch.karaoke_mode = patch.karaoke_mode;
    if (patch.enable_hf_restore !== undefined) settingsPatch.enable_hf_restore = patch.enable_hf_restore;
    if (patch.hf_boost_db !== undefined) settingsPatch.hf_boost_db = patch.hf_boost_db;
    if (patch.enable_loudness_normalize !== undefined) {
      settingsPatch.enable_loudness_normalize = patch.enable_loudness_normalize;
    }
    if (patch.enable_spectral_denoise !== undefined) {
      settingsPatch.enable_spectral_denoise = patch.enable_spectral_denoise;
    }

    if (Object.keys(settingsPatch).length > 0) {
      this.db.updateSettings(settingsPatch);
    }
  }

  setCustomOutputDir(dir) {
    this.jobsStore.customOutputDir = dir;
    this.db.updateSettings({ custom_output_dir: dir, default_output_dir: dir });
  }

  setNamingTemplate(tpl) {
    this.systemStore.namingTemplate = tpl;
    this.db.updateSettings({
      naming_template: tpl,
      file_naming_template: tpl,
    });
  }

  setConflictPolicy(pol) {
    this.systemStore.conflictPolicy = pol;
    this.db.updateSettings({
      conflict_policy: pol,
      overwrite_behavior: pol,
    });
  }

  setAlwaysOnTop(v) {
    this.systemStore.alwaysOnTop = v;
    this.db.updateSettings({ always_on_top: v });
  }

  setUiScale(scale) {
    this.systemStore.uiScale = scale;
    this.db.updateSettings({ ui_scale: scale });
  }

  setLocale(loc) {
    this.systemStore.locale = loc;
    this.db.updateSettings({ locale: loc });
  }

  setTheme(th) {
    this.systemStore.theme = th;
    this.db.updateSettings({ theme: th });
  }

  setHighContrast(hc) {
    this.systemStore.highContrast = hc;
    this.db.updateSettings({ high_contrast: hc });
  }

  setReducedMotion(rm) {
    this.systemStore.reducedMotion = rm;
    this.db.updateSettings({ reduced_motion: rm });
  }

  setMinimizeToTray(mtt) {
    this.systemStore.minimizeToTray = mtt;
    this.db.updateSettings({ minimize_to_tray: mtt });
  }

  setPreserveFolderStructure(v) {
    this.systemStore.preserveFolderStructure = v;
    this.db.updateSettings({ preserve_folder_structure: v });
  }

  setMaxCacheSizeGb(gb) {
    this.systemStore.maxCacheSizeGb = gb;
    this.db.updateSettings({ max_cache_size_gb: gb });
  }

  setAutoOpenFolder(v) {
    this.jobsStore.autoOpenFolder = v;
    this.db.updateSettings({ auto_open_folder: v });
  }

  // Exact initApp rehydration logic from appStores.ts:1446-1560
  initApp() {
    const settings = this.db.getAllSettings();
    if (settings && Object.keys(settings).length > 0) {
      if (settings.locale) this.systemStore.locale = settings.locale;
      if (settings.theme) this.systemStore.theme = settings.theme;
      if (settings.ui_scale) this.systemStore.uiScale = Number(settings.ui_scale);
      if (settings.high_contrast !== undefined) this.systemStore.highContrast = Boolean(settings.high_contrast);
      if (settings.reduced_motion !== undefined) this.systemStore.reducedMotion = Boolean(settings.reduced_motion);
      if (settings.always_on_top !== undefined) this.systemStore.alwaysOnTop = Boolean(settings.always_on_top);
      if (settings.minimize_to_tray !== undefined) this.systemStore.minimizeToTray = Boolean(settings.minimize_to_tray);
      if (settings.onboarding_completed !== undefined || settings.onboarding_done !== undefined) {
        this.systemStore.onboardingDone = Boolean(settings.onboarding_completed ?? settings.onboarding_done);
      }

      const namingTpl = settings.naming_template || settings.file_naming_template;
      if (namingTpl) this.systemStore.namingTemplate = namingTpl;

      const conflict = settings.conflict_policy || settings.overwrite_behavior;
      if (conflict) this.systemStore.conflictPolicy = conflict;

      if (settings.preserve_folder_structure !== undefined) {
        this.systemStore.preserveFolderStructure = Boolean(settings.preserve_folder_structure);
      }
      if (settings.max_cache_size_gb !== undefined) {
        this.systemStore.maxCacheSizeGb = Number(settings.max_cache_size_gb);
      }

      const outDir = settings.custom_output_dir || settings.default_output_dir;
      if (outDir) {
        this.jobsStore.customOutputDir = outDir;
      }
      if (settings.auto_open_folder !== undefined) {
        this.jobsStore.autoOpenFolder = Boolean(settings.auto_open_folder);
      }
      if (settings.max_concurrent_jobs) {
        this.jobsStore.parallelWorkers = Number(settings.max_concurrent_jobs);
      }

      if (settings.hardware_profile_mode) {
        const raw = String(settings.hardware_profile_mode).toLowerCase();
        const modeMap = {
          auto: "Auto",
          eco: "Eco",
          balanced: "Balanced",
          max_quality: "Max Quality",
        };
        if (modeMap[raw]) this.systemStore.activeProfileMode = modeMap[raw];
      }

      // Restore complete separation & DSP options
      const jobPatch = {};
      if (settings.model_name) jobPatch.model = settings.model_name;
      if (settings.device) jobPatch.device = settings.device;
      if (settings.output_mode) jobPatch.output_mode = settings.output_mode;
      if (settings.output_format) jobPatch.output_format = settings.output_format;
      if (settings.wav_bit_depth) jobPatch.wav_bit_depth = settings.wav_bit_depth;
      const bitrate = settings.audio_bitrate || settings.mp3_bitrate;
      if (bitrate) jobPatch.audio_bitrate = bitrate;
      if (settings.output_all_stems !== undefined) jobPatch.output_all_stems = Boolean(settings.output_all_stems);
      if (settings.output_video !== undefined) jobPatch.output_video = Boolean(settings.output_video);
      if (settings.video_output_mode) jobPatch.video_output_mode = settings.video_output_mode;
      if (settings.delete_input_file !== undefined) jobPatch.delete_input_file = Boolean(settings.delete_input_file);
      if (settings.shifts !== undefined) jobPatch.shifts = Number(settings.shifts);
      if (settings.overlap !== undefined) jobPatch.overlap = Number(settings.overlap);
      if (settings.segment !== undefined) jobPatch.segment = Number(settings.segment);
      if (settings.fp16_inference !== undefined) jobPatch.fp16_inference = Boolean(settings.fp16_inference);
      if (settings.ensemble_mode !== undefined) jobPatch.ensemble_mode = Boolean(settings.ensemble_mode);
      if (settings.song_mode !== undefined) jobPatch.song_mode = Boolean(settings.song_mode);
      if (settings.trim_silence !== undefined) jobPatch.trim_silence = Boolean(settings.trim_silence);
      if (settings.enable_vocal_gate !== undefined) jobPatch.enable_vocal_gate = Boolean(settings.enable_vocal_gate);
      if (settings.gate_threshold_db !== undefined) jobPatch.gate_threshold_db = Number(settings.gate_threshold_db);
      if (settings.gate_floor_db !== undefined) jobPatch.gate_floor_db = Number(settings.gate_floor_db);
      if (settings.denoise_strength !== undefined) jobPatch.denoise_strength = Number(settings.denoise_strength);
      if (settings.min_vocal_duration !== undefined) jobPatch.min_vocal_duration = Number(settings.min_vocal_duration);
      if (settings.enable_multiband_denoise !== undefined) {
        jobPatch.enable_multiband_denoise = Boolean(settings.enable_multiband_denoise);
      }
      if (settings.enable_sfx_separation !== undefined) {
        jobPatch.enable_sfx_separation = Boolean(settings.enable_sfx_separation);
      }
      if (settings.save_background_track !== undefined) {
        jobPatch.save_background_track = Boolean(settings.save_background_track);
      }
      if (settings.karaoke_mode !== undefined) jobPatch.karaoke_mode = Boolean(settings.karaoke_mode);
      if (settings.enable_hf_restore !== undefined) jobPatch.enable_hf_restore = Boolean(settings.enable_hf_restore);
      if (settings.hf_boost_db !== undefined) jobPatch.hf_boost_db = Number(settings.hf_boost_db);
      if (settings.enable_loudness_normalize !== undefined) {
        jobPatch.enable_loudness_normalize = Boolean(settings.enable_loudness_normalize);
      }
      if (settings.enable_spectral_denoise !== undefined) {
        jobPatch.enable_spectral_denoise = Boolean(settings.enable_spectral_denoise);
      }

      if (Object.keys(jobPatch).length > 0) {
        this.jobsStore.options = { ...this.jobsStore.options, ...jobPatch };
      }

      if (settings.output_format) {
        this.mixerStore.exportFormat = settings.output_format;
      }
      if (bitrate) {
        this.mixerStore.exportBitrate = bitrate;
      }
    }
  }
}

// Adversarial Test 1.1: 30+ Non-Default Settings Keys Full Round-Trip
console.log("- Test 1.1: Round-trip persistence of 30+ non-default parameters");
const mockDb = new MockSqliteSettingsDb();
const app1 = new MockVocalProAppStore(mockDb);

// Apply aggressive non-default parameters
const testPatch = {
  model: "mdx_extra",
  device: "cuda:0",
  output_mode: "two_stems",
  output_format: "flac",
  wav_bit_depth: "PCM_24",
  audio_bitrate: "192k",
  output_all_stems: true,
  output_video: false,
  video_output_mode: "audio_only",
  delete_input_file: true,
  shifts: 3,
  overlap: 0.75,
  segment: 15.0,
  fp16_inference: false,
  ensemble_mode: true,
  song_mode: true,
  trim_silence: false,
  enable_vocal_gate: false,
  gate_threshold_db: -45.0,
  gate_floor_db: -50.0,
  denoise_strength: 0.85,
  min_vocal_duration: 0.15,
  enable_multiband_denoise: true,
  enable_sfx_separation: true,
  save_background_track: true,
  karaoke_mode: true,
  enable_hf_restore: false,
  hf_boost_db: 5.5,
  enable_loudness_normalize: false,
  enable_spectral_denoise: false,
};

app1.setOptions(testPatch);
app1.setCustomOutputDir("/var/data/custom_vocalpro_output");
app1.setNamingTemplate("{track_name}_custom_{stem}");
app1.setConflictPolicy("rename");
app1.setAlwaysOnTop(true);
app1.setUiScale(125);
app1.setLocale("ar");
app1.setTheme("light");
app1.setHighContrast(true);
app1.setReducedMotion(true);
app1.setMinimizeToTray(true);
app1.setPreserveFolderStructure(true);
app1.setMaxCacheSizeGb(30);
app1.setAutoOpenFolder(false);

// Simulate application shutdown and fresh startup with new empty store
const app2 = new MockVocalProAppStore(mockDb);
// Verify app2 initially has defaults
assert.strictEqual(app2.jobsStore.options.shifts, 1);
assert.strictEqual(app2.jobsStore.options.overlap, 0.25);
assert.strictEqual(app2.jobsStore.options.wav_bit_depth, "PCM_16");
assert.strictEqual(app2.jobsStore.options.audio_bitrate, "320k");
assert.strictEqual(app2.jobsStore.options.gate_threshold_db, -55.0);

// Perform rehydration
app2.initApp();

// Verify all 30+ values restored identically
for (const [key, expectedVal] of Object.entries(testPatch)) {
  const actualVal = app2.jobsStore.options[key];
  assert.strictEqual(
    actualVal,
    expectedVal,
    `Key '${key}' failed to rehydrate: expected ${expectedVal}, got ${actualVal}`
  );
}
assert.strictEqual(app2.jobsStore.customOutputDir, "/var/data/custom_vocalpro_output");
assert.strictEqual(app2.systemStore.namingTemplate, "{track_name}_custom_{stem}");
assert.strictEqual(app2.systemStore.conflictPolicy, "rename");
assert.strictEqual(app2.systemStore.alwaysOnTop, true);
assert.strictEqual(app2.systemStore.uiScale, 125);
assert.strictEqual(app2.systemStore.locale, "ar");
assert.strictEqual(app2.systemStore.theme, "light");
assert.strictEqual(app2.systemStore.highContrast, true);
assert.strictEqual(app2.systemStore.reducedMotion, true);
assert.strictEqual(app2.systemStore.minimizeToTray, true);
assert.strictEqual(app2.systemStore.preserveFolderStructure, true);
assert.strictEqual(app2.systemStore.maxCacheSizeGb, 30);
assert.strictEqual(app2.jobsStore.autoOpenFolder, false);
assert.strictEqual(app2.mixerStore.exportFormat, "flac");
assert.strictEqual(app2.mixerStore.exportBitrate, "192k");
console.log("  ✓ All 30+ non-default parameters survived round-trip rehydration flawlessly!");

// Adversarial Test 1.2: Dual-Key Schema Parity (Backend SQLite vs Frontend Store)
console.log("- Test 1.2: Dual-key SQLite schema aliasing resilience");
const dualKeyDb = new MockSqliteSettingsDb();
// Populate DB with backend SQLite schema field names
dualKeyDb.updateSettings({
  file_naming_template: "{track_name}_from_sqlite_{stem}",
  overwrite_behavior: "skip",
  default_output_dir: "/default/output/path",
  mp3_bitrate: "256k",
  onboarding_completed: true,
  hardware_profile_mode: "max_quality",
});
const dualKeyApp = new MockVocalProAppStore(dualKeyDb);
dualKeyApp.initApp();

assert.strictEqual(dualKeyApp.systemStore.namingTemplate, "{track_name}_from_sqlite_{stem}");
assert.strictEqual(dualKeyApp.systemStore.conflictPolicy, "skip");
assert.strictEqual(dualKeyApp.jobsStore.customOutputDir, "/default/output/path");
assert.strictEqual(dualKeyApp.jobsStore.options.audio_bitrate, "256k");
assert.strictEqual(dualKeyApp.mixerStore.exportBitrate, "256k");
assert.strictEqual(dualKeyApp.systemStore.onboardingDone, true);
assert.strictEqual(dualKeyApp.systemStore.activeProfileMode, "Max Quality");
console.log("  ✓ Dual-key aliases (file_naming_template, overwrite_behavior, default_output_dir, mp3_bitrate) resolved seamlessly.");

// Adversarial Test 1.3: Type Coercion & Boundary Values
console.log("- Test 1.3: Type coercion & numerical boundary persistence");
const boundaryDb = new MockSqliteSettingsDb();
boundaryDb.updateSettings({
  ui_scale: "150", // stringified number
  shifts: "0",
  overlap: "0.0",
  gate_threshold_db: "-90.0",
  max_cache_size_gb: "100",
  always_on_top: 1, // numeric truthy
  high_contrast: 0, // numeric falsy
  trim_silence: "true", // stringified bool
});
const boundaryApp = new MockVocalProAppStore(boundaryDb);
boundaryApp.initApp();

assert.strictEqual(boundaryApp.systemStore.uiScale, 150);
assert.strictEqual(typeof boundaryApp.systemStore.uiScale, "number");
assert.strictEqual(boundaryApp.jobsStore.options.shifts, 0);
assert.strictEqual(boundaryApp.jobsStore.options.overlap, 0.0);
assert.strictEqual(boundaryApp.jobsStore.options.gate_threshold_db, -90.0);
assert.strictEqual(boundaryApp.systemStore.maxCacheSizeGb, 100);
assert.strictEqual(boundaryApp.systemStore.alwaysOnTop, true);
assert.strictEqual(boundaryApp.systemStore.highContrast, false);
console.log("  ✓ Type coercion handles stringified numbers and numeric booleans cleanly.");


// ============================================================================
// SUITE 2: Banner Typing Inference & Semantic Notification (Feature 22)
// ============================================================================
console.log("\n=== Running Suite 2: Banner Typing Inference & Formatting ===");

// Exact inferBannerType implementation from appStores.ts:30-54
function inferBannerType(msg) {
  const lower = msg.toLowerCase();
  if (
    lower.includes("error") ||
    lower.includes("failed") ||
    lower.includes("fatal") ||
    lower.includes("exception") ||
    lower.includes("corrupt")
  ) {
    return "error";
  }
  if (lower.includes("warning") || lower.includes("warn") || lower.includes("⚠️")) {
    return "warning";
  }
  if (
    lower.includes("success") ||
    lower.includes("complete") ||
    lower.includes("saved") ||
    lower.includes("imported") ||
    lower.includes("created")
  ) {
    return "success";
  }
  return "info";
}

function makeBanner(msg, type) {
  return {
    message: msg,
    type: type || inferBannerType(msg),
  };
}

// 2.1 Standard keyword tests
const standardCases = [
  { msg: "Separation error: invalid wav header", expected: "error" },
  { msg: "Job failed: unexpected EOF on stdout", expected: "error" },
  { msg: "Fatal memory corruption in DSP worker", expected: "error" },
  { msg: "Unhandled exception while parsing Demucs JSON", expected: "error" },
  { msg: "Corrupt FLAC file detected", expected: "error" },
  { msg: "Warning: VRAM capacity at 92%", expected: "warning" },
  { msg: "Warn: Model fallback triggered", expected: "warning" },
  { msg: "⚠️ Worker slot 1 restarted", expected: "warning" },
  { msg: "Separation finished with success!", expected: "success" },
  { msg: "Hardware micro-benchmark complete in 120ms", expected: "success" },
  { msg: "Saved mix to disk: output.wav", expected: "success" },
  { msg: "Imported settings JSON successfully", expected: "success" },
  { msg: "Created Desktop Shortcut (VocalPro.lnk)", expected: "success" },
  { msg: "Running benchmark...", expected: "info" },
  { msg: "Theme changed to LIGHT", expected: "info" },
  { msg: "Window Always-on-Top: Enabled", expected: "info" },
];

for (const tc of standardCases) {
  const result = inferBannerType(tc.msg);
  assert.strictEqual(
    result,
    tc.expected,
    `inferBannerType('${tc.msg}') returned '${result}', expected '${tc.expected}'`
  );
}
console.log(`- Standard keyword inference: ${standardCases.length} test cases passed.`);

// 2.2 Case insensitivity & precedence
assert.strictEqual(inferBannerType("FATAL ERROR IN PROCESSING"), "error");
assert.strictEqual(inferBannerType("JOB COMPLETED SUCCESSFULLY"), "success");
assert.strictEqual(inferBannerType("WARNING: LOW DISK SPACE"), "warning");

// Precedence test: "Error: Failed to save completed mix" -> contains "error", "failed", "saved", "complete"
// In inferBannerType, 'error' check comes FIRST -> must return "error"
assert.strictEqual(
  inferBannerType("Error: Failed to save completed mix"),
  "error",
  "Error keywords must take precedence over success keywords"
);
console.log("- Precedence verification: Error takes precedence over embedded success keywords.");

// 2.3 Explicit type override in makeBanner
const override1 = makeBanner("PyTorch CUDA out of memory", "error");
assert.strictEqual(override1.type, "error", "Explicit type 'error' must override default inference");
const override2 = makeBanner("AI model not found", "warning");
assert.strictEqual(override2.type, "warning", "Explicit type 'warning' must override default inference");
console.log("- Explicit type override in makeBanner verified.");

// 2.4 Adversarial observation on uncovered error phrasing
const oomRaw = inferBannerType("PyTorch CUDA out of memory");
console.log(`- Adversarial Observation: inferBannerType("PyTorch CUDA out of memory") without explicit type yields '${oomRaw}'.`);
const notFoundRaw = inferBannerType("AI model not found");
console.log(`- Adversarial Observation: inferBannerType("AI model not found") without explicit type yields '${notFoundRaw}'.`);


// ============================================================================
// SUITE 3: Real Job Retries Logic Verification (Feature 22)
// ============================================================================
console.log("\n=== Running Suite 3: Real Job Retries State Machine Tests ===");

class MockJobsStoreWithRetry {
  constructor() {
    this.jobs = [];
    this.activeJobId = null;
    this.customOutputDir = "/custom/dir";
    this.options = { ...DEFAULT_JOB_OPTIONS };
    this.logs = [];
    this.systemBanner = null;
    this.ipcCalls = [];
    this.ipcResponses = {};
    this.pollIntervalsCleared = [];
  }

  appendLog(l) {
    this.logs.push(l);
  }

  showBanner(message, type) {
    this.systemBanner = { message, type };
  }

  // Model the exact retryFailedJob implementation from appStores.ts:256-340
  async retryFailedJob(jobId) {
    const failed = this.jobs.find((j) => j.job_id === jobId);
    if (!failed) return;

    const targetFile = failed.input_path;
    const targetOptions = failed.options || this.options;
    const targetOutDir = this.customOutputDir || failed.output_dir || "";

    // Immediate UI feedback
    this.jobs = this.jobs.map((j) =>
      j.job_id === jobId
        ? {
            ...j,
            status: "loading_model",
            phase: "loading_model",
            percent: 5,
            error_code: null,
            error_message: null,
            message: `Retrying separation for ${targetFile.split(/[\\/]/).pop()}...`,
          }
        : j
    );
    this.activeJobId = jobId;
    this.appendLog(`[retry] Re-dispatching backend separation for ${targetFile}...`);

    let pollTimer = null;
    try {
      this.ipcCalls.push({
        cmd: "start_separation_batch",
        args: {
          inputs: [targetFile],
          outputDir: targetOutDir,
          options: targetOptions,
        },
      });

      // Simulated polling loop
      let pollCount = 0;
      pollTimer = setInterval(async () => {
        pollCount += 1;
        const liveJobs = this.ipcResponses["list_jobs"] || [];
        if (liveJobs && Array.isArray(liveJobs) && liveJobs.length > 0) {
          const live = liveJobs.find((lj) => lj.input_path === targetFile);
          if (live) {
            this.jobs = this.jobs.map((j) =>
              j.job_id === jobId ? { ...j, ...live, job_id: jobId } : j
            );
          }
        }
      }, 50);

      // Await start_separation_batch promise
      const records = await this.ipcResponses["start_separation_batch"];
      if (pollTimer) {
        clearInterval(pollTimer);
        this.pollIntervalsCleared.push(true);
      }

      const rec = records && Array.isArray(records) ? records[0] : null;
      if (!rec || rec.status === "failed" || !rec.stems || rec.stems.length === 0) {
        const errMsg = rec?.error_message || "Separation worker failed to generate stems on retry.";
        this.jobs = this.jobs.map((j) =>
          j.job_id === jobId ? { ...j, status: "failed", error_message: errMsg } : j
        );
        this.showBanner(`Retry failed: ${errMsg}`, "error");
        this.appendLog(`[retry_error] Retry failed for ${targetFile}: ${errMsg}`);
        return;
      }

      this.jobs = this.jobs.map((j) =>
        j.job_id === jobId ? { ...j, ...rec, job_id: jobId, status: "done", percent: 100 } : j
      );

      const fname = targetFile.split(/[\\/]/).pop() || "track";
      this.showBanner(`Successfully separated "${fname}" into ${rec.stems.length} stems!`, "success");
      this.appendLog(`[retry_done] Successfully separated ${targetFile} -> ${rec.stems.length} stems`);

      this.ipcCalls.push({ cmd: "list_outputs" });
      this.ipcCalls.push({ cmd: "list_separation_history" });
    } catch (err) {
      if (pollTimer) {
        clearInterval(pollTimer);
        this.pollIntervalsCleared.push(true);
      }
      this.jobs = this.jobs.map((j) =>
        j.job_id === jobId ? { ...j, status: "failed", error_message: String(err?.message || err) } : j
      );
      this.showBanner(`Retry failed: ${err?.message || err}`, "error");
    }
  }
}

// 3.1 Non-existent job ID
{
  const store = new MockJobsStoreWithRetry();
  await store.retryFailedJob("non_existent_id");
  assert.strictEqual(store.ipcCalls.length, 0, "Non-existent job must not issue IPC calls");
  console.log("- Test 3.1: Non-existent job ID rejected cleanly with 0 side effects.");
}

// 3.2 Integrity Check: Does it freeze at 35%?
{
  const store = new MockJobsStoreWithRetry();
  const failedJob = {
    job_id: "job_001",
    input_path: "/music/song.mp3",
    output_dir: "/out",
    options: { model: "htdemucs" },
    status: "failed",
    phase: "failed",
    percent: 0,
    error_message: "CUDA OOM",
  };
  store.jobs.push(failedJob);

  // Setup successful IPC response
  store.ipcResponses["start_separation_batch"] = Promise.resolve([
    {
      job_id: "backend_new_001",
      input_path: "/music/song.mp3",
      status: "done",
      percent: 100,
      stems: ["vocals.wav", "no_vocals.wav"],
    },
  ]);

  await store.retryFailedJob("job_001");

  const retried = store.jobs.find((j) => j.job_id === "job_001");
  assert.strictEqual(retried.status, "done");
  assert.strictEqual(retried.percent, 100);
  assert.notStrictEqual(retried.percent, 35, "CRITICAL: Job must NOT freeze at fake 35% state!");
  assert.strictEqual(store.systemBanner.type, "success");
  assert(store.systemBanner.message.includes("Successfully separated"));
  assert.strictEqual(store.pollIntervalsCleared.length, 1);
  assert(store.ipcCalls.some((c) => c.cmd === "start_separation_batch"));
  assert(store.ipcCalls.some((c) => c.cmd === "list_outputs"));
  console.log("- Test 3.2: Successful retry completed to 100%, stems verified, ZERO freeze at fake 35%.");
}

// 3.3 Retry Failure Handling
{
  const store = new MockJobsStoreWithRetry();
  const failedJob = {
    job_id: "job_002",
    input_path: "/music/corrupt.wav",
    output_dir: "/out",
    options: { model: "htdemucs" },
    status: "failed",
    phase: "failed",
    percent: 0,
    error_message: "Initial fail",
  };
  store.jobs.push(failedJob);

  // Setup failed IPC response
  store.ipcResponses["start_separation_batch"] = Promise.resolve([
    {
      job_id: "backend_new_002",
      input_path: "/music/corrupt.wav",
      status: "failed",
      percent: 10,
      stems: [],
      error_message: "Invalid PCM audio chunk",
    },
  ]);

  await store.retryFailedJob("job_002");

  const retried = store.jobs.find((j) => j.job_id === "job_002");
  assert.strictEqual(retried.status, "failed");
  assert.strictEqual(retried.error_message, "Invalid PCM audio chunk");
  assert.strictEqual(store.systemBanner.type, "error");
  assert(store.systemBanner.message.includes("Retry failed: Invalid PCM audio chunk"));
  assert.strictEqual(store.pollIntervalsCleared.length, 1);
  console.log("- Test 3.3: Retry failure cleanly sets status='failed' with typed error banner and cleans up polling timer.");
}

// 3.4 IPC Exception / Network Throw Handling
{
  const store = new MockJobsStoreWithRetry();
  const failedJob = {
    job_id: "job_003",
    input_path: "/music/crash.wav",
    status: "failed",
    percent: 0,
  };
  store.jobs.push(failedJob);

  // Setup rejected IPC promise
  store.ipcResponses["start_separation_batch"] = Promise.reject(new Error("IPC Channel Closed"));

  await store.retryFailedJob("job_003");

  const retried = store.jobs.find((j) => j.job_id === "job_003");
  assert.strictEqual(retried.status, "failed");
  assert.strictEqual(retried.error_message, "IPC Channel Closed");
  assert.strictEqual(store.systemBanner.type, "error");
  assert.strictEqual(store.pollIntervalsCleared.length, 1);
  console.log("- Test 3.4: IPC exception caught, timer cleared, and error banner dispatched.");
}

console.log("\n========================================================");
console.log(">>> ALL CHALLENGER 2 VERIFICATION SUITES PASSED CLEANLY <<<");
console.log("========================================================");
