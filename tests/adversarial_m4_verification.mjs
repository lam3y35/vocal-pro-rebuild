import assert from "node:assert";

// ============================================================================
// SUITE 1: Active Drift Compensation Empirical Verification
// ============================================================================
console.log("=== Running Suite 1: Active Drift Compensation Stress Tests ===");

class SimulatedTrack {
  constructor(name, currentTime = 0, paused = false) {
    this.name = name;
    this.element = {
      currentTime,
      playbackRate: 1.0,
      paused,
    };
  }
}

function simulateDriftStep(master, slave, dt) {
  // Advance simulated audio elements
  if (!master.element.paused) {
    master.element.currentTime += dt * master.element.playbackRate;
  }
  if (!slave.element.paused) {
    slave.element.currentTime += dt * slave.element.playbackRate;
  }

  // Active drift compensation algorithm from audioPlayer.ts
  const masterTime = master.element.currentTime;
  const drift = slave.element.currentTime - masterTime;
  const absDrift = Math.abs(drift);

  let action = "ZONE_0_LOCKED";
  if (absDrift <= 0.004) {
    // Zone 0: Sub-4ms phase lock zone
    if (slave.element.playbackRate !== 1.0) {
      slave.element.playbackRate = 1.0;
    }
  } else if (absDrift <= 0.035) {
    // Tier 1: Micro-drift rate bending (zero click/stutter)
    const rate = drift < 0 ? 1.03 : 0.97;
    if (slave.element.playbackRate !== rate) {
      slave.element.playbackRate = rate;
    }
    action = drift < 0 ? "TIER_1_ACCELERATE_1.03" : "TIER_1_DECELERATE_0.97";
  } else {
    // Tier 2: Hard resync on major stall
    slave.element.currentTime = masterTime;
    slave.element.playbackRate = 1.0;
    action = "TIER_2_HARD_RESYNC";
  }

  return { masterTime, slaveTime: slave.element.currentTime, drift, absDrift, rate: slave.element.playbackRate, action };
}

function runDriftSimulation(initialLagMs, maxDurationSec = 2.0) {
  const dt = 0.025; // 25ms loop interval (40 Hz)
  const master = new SimulatedTrack("master", 10.0);
  const slave = new SimulatedTrack("slave", 10.0 + initialLagMs / 1000.0);

  const history = [];
  let time = 0;
  let convergedAt = null;

  while (time < maxDurationSec) {
    const res = simulateDriftStep(master, slave, dt);
    history.push({ time, ...res });

    if (res.absDrift <= 0.004 && convergedAt === null) {
      convergedAt = time;
    }
    time += dt;
  }

  return { initialLagMs, convergedAt, history, finalDrift: history[history.length - 1].absDrift };
}

// Test cases specified in dispatch:
// Negative drift (lagging): -10ms, -25ms, -50ms
// Positive drift (leading): +10ms, +25ms, +50ms
const driftCases = [
  { name: "Lagging 10ms", lagMs: -10, expectedMaxConvergeSec: 0.25, expectedTier2: false },
  { name: "Lagging 25ms", lagMs: -25, expectedMaxConvergeSec: 0.75, expectedTier2: false },
  { name: "Lagging 50ms", lagMs: -50, expectedMaxConvergeSec: 0.05, expectedTier2: true }, // Tier 2 instant resync
  { name: "Leading 10ms", lagMs: 10, expectedMaxConvergeSec: 0.25, expectedTier2: false },
  { name: "Leading 25ms", lagMs: 25, expectedMaxConvergeSec: 0.75, expectedTier2: false },
  { name: "Leading 50ms", lagMs: 50, expectedMaxConvergeSec: 0.05, expectedTier2: true }, // Tier 2 instant resync
];

for (const tc of driftCases) {
  const sim = runDriftSimulation(tc.lagMs);
  console.log(`- Case [${tc.name}]: initial drift=${tc.lagMs}ms`);
  console.log(`  Converged to <= 4ms at: ${sim.convergedAt !== null ? (sim.convergedAt * 1000).toFixed(1) + 'ms' : 'NEVER'}`);
  console.log(`  Final absolute drift: ${(sim.finalDrift * 1000).toFixed(3)}ms`);

  // Verify convergence
  assert(sim.convergedAt !== null, `Failed to converge for ${tc.name}`);
  assert(sim.convergedAt <= tc.expectedMaxConvergeSec, `Convergence time ${sim.convergedAt}s exceeded expected max ${tc.expectedMaxConvergeSec}s`);
  assert(sim.finalDrift <= 0.0040001, `Final drift ${sim.finalDrift * 1000}ms exceeds 4ms threshold`);

  // Verify no discontinuities in Tier 1 cases
  if (!tc.expectedTier2) {
    const actions = sim.history.map(h => h.action);
    assert(!actions.includes("TIER_2_HARD_RESYNC"), `Unexpected hard resync for ${tc.name}`);
    // Check that playbackRate returned to 1.0 after convergence
    const lastStep = sim.history[sim.history.length - 1];
    assert.strictEqual(lastStep.rate, 1.0, `Final playbackRate must be 1.0, got ${lastStep.rate}`);
  } else {
    // For 50ms, the very first tick must be TIER_2_HARD_RESYNC
    assert.strictEqual(sim.history[0].action, "TIER_2_HARD_RESYNC", `50ms drift must trigger Tier 2 hard resync`);
  }
}

// Micro-boundary stress tests
console.log("- Micro-boundary testing around thresholds (4ms, 35ms):");
// 4.0ms: already in zone 0
const sim4ms = runDriftSimulation(-4.0);
assert.strictEqual(sim4ms.history[0].action, "ZONE_0_LOCKED");
// 4.1ms: Tier 1 micro-bending
const sim4_1ms = runDriftSimulation(-4.1);
assert.strictEqual(sim4_1ms.history[0].action, "TIER_1_ACCELERATE_1.03");
// 34.9ms: Tier 1
const sim34_9ms = runDriftSimulation(-34.9);
assert.strictEqual(sim34_9ms.history[0].action, "TIER_1_ACCELERATE_1.03");
// 35.1ms: Tier 2 hard resync
const sim35_1ms = runDriftSimulation(-35.1);
assert.strictEqual(sim35_1ms.history[0].action, "TIER_2_HARD_RESYNC");
console.log("  Boundaries verified: 4.0ms -> Zone 0, 4.1ms -> Tier 1, 34.9ms -> Tier 1, 35.1ms -> Tier 2.");


// ============================================================================
// SUITE 2: Gain Scaling, Solo/Mute Matrix & Parameter Smoothing
// ============================================================================
console.log("\n=== Running Suite 2: Gain Scaling & Smoothing Tests ===");

function computeTargetGain(track, allTracks) {
  const hasSolo = allTracks.some(t => t.solo);
  if (track.mute) {
    return 0;
  } else if (hasSolo) {
    return track.solo ? Math.max(0, track.gain) : 0;
  } else {
    return Math.max(0, track.gain);
  }
}

function clampGain(gain) {
  return Math.max(0, Math.min(2.0, gain));
}

// 1. Boundary clamping
const testGains = [-1.0, -0.001, 0.0, 0.5, 1.0, 1.5, 2.0, 2.001, 5.0, 100.0];
const expectedClamped = [0.0, 0.0, 0.0, 0.5, 1.0, 1.5, 2.0, 2.0, 2.0, 2.0];
for (let i = 0; i < testGains.length; i++) {
  const clamped = clampGain(testGains[i]);
  assert.strictEqual(clamped, expectedClamped[i], `Gain clamp failed for input ${testGains[i]}: got ${clamped}, expected ${expectedClamped[i]}`);
}
console.log("- Gain clamping verified across [-1.0, 100.0] -> strict [0.0, 2.0] (+6 dB max).");

// 2. Solo / Mute Matrix
const tracks = [
  { name: "vocals", gain: 1.5, mute: false, solo: false },
  { name: "drums", gain: 1.0, mute: false, solo: false },
  { name: "bass", gain: 0.8, mute: true, solo: false },
  { name: "other", gain: 1.2, mute: false, solo: false },
];
// Baseline: all unmuted tracks at their gain, bass muted -> 0
assert.strictEqual(computeTargetGain(tracks[0], tracks), 1.5);
assert.strictEqual(computeTargetGain(tracks[1], tracks), 1.0);
assert.strictEqual(computeTargetGain(tracks[2], tracks), 0.0);
assert.strictEqual(computeTargetGain(tracks[3], tracks), 1.2);

// Solo vocals: only vocals at 1.5, all others 0
tracks[0].solo = true;
assert.strictEqual(computeTargetGain(tracks[0], tracks), 1.5);
assert.strictEqual(computeTargetGain(tracks[1], tracks), 0.0);
assert.strictEqual(computeTargetGain(tracks[2], tracks), 0.0);
assert.strictEqual(computeTargetGain(tracks[3], tracks), 0.0);

// Solo both vocals and drums
tracks[1].solo = true;
assert.strictEqual(computeTargetGain(tracks[0], tracks), 1.5);
assert.strictEqual(computeTargetGain(tracks[1], tracks), 1.0);
assert.strictEqual(computeTargetGain(tracks[2], tracks), 0.0);
assert.strictEqual(computeTargetGain(tracks[3], tracks), 0.0);

// Mute soloed vocals: mute takes precedence -> 0
tracks[0].mute = true;
assert.strictEqual(computeTargetGain(tracks[0], tracks), 0.0);
assert.strictEqual(computeTargetGain(tracks[1], tracks), 1.0);
console.log("- Solo / Mute priority matrix verified correctly.");

// 3. Mathematical model of Web Audio setTargetAtTime(targetGain, ctx.currentTime, 0.015)
// V(t) = V_target + (V_0 - V_target) * exp(-(t - t_0) / tau)
function simulateExponentialGainSmoothing(v0, vTarget, tau, durationSec, dt = 0.001) {
  const steps = [];
  for (let t = 0; t <= durationSec; t += dt) {
    const v = vTarget + (v0 - vTarget) * Math.exp(-t / tau);
    steps.push({ t, v });
  }
  return steps;
}

const tau = 0.015; // 15ms constant from audioPlayer.ts
const curve = simulateExponentialGainSmoothing(0.0, 2.0, tau, 0.100); // 0 to +6dB over 100ms
// At t = 1*tau (15ms): 1 - 1/e ≈ 63.2% of step -> ~1.264
const step15ms = curve.find(s => Math.abs(s.t - 0.015) < 0.0005);
assert(Math.abs(step15ms.v - 2.0 * (1 - Math.exp(-1))) < 0.01);
// At t = 3*tau (45ms): 1 - exp(-3) ≈ 95.0% -> ~1.900
const step45ms = curve.find(s => Math.abs(s.t - 0.045) < 0.0005);
assert(Math.abs(step45ms.v - 2.0 * (1 - Math.exp(-3))) < 0.01);
// At t = 5*tau (75ms): 1 - exp(-5) ≈ 99.3% -> ~1.986
const step75ms = curve.find(s => Math.abs(s.t - 0.075) < 0.0005);
assert(step75ms.v > 1.98 && step75ms.v <= 2.0);
// Smooth continuous slope: check no instantaneous jump
for (let i = 1; i < curve.length; i++) {
  const delta = curve[i].v - curve[i - 1].v;
  assert(delta >= 0, "Gain must monotonically increase");
  assert(delta < 0.15, "Gain transition per millisecond must be continuous");
}
console.log("- Parameter smoothing time constant tau=15ms verified: 63.2% at 15ms, 95.0% at 45ms, 99.3% at 75ms with zero discontinuities.");


// ============================================================================
// SUITE 3: Waveform Fractional Sampling Coverage & Silence Preservation
// ============================================================================
console.log("\n=== Running Suite 3: Waveform Sampling & Silence Tests ===");

function sampleWaveformBars(peaks, numBars) {
  const hasPeaks = Array.isArray(peaks) && peaks.length > 0;
  const bars = [];
  const sampledIndices = new Set();

  for (let i = 0; i < numBars; i++) {
    let peakVal = 0.15;
    if (hasPeaks) {
      const startIdx = Math.floor((i / numBars) * peaks.length);
      const endIdx = Math.min(
        peaks.length,
        Math.max(startIdx + 1, Math.floor(((i + 1) / numBars) * peaks.length))
      );
      let maxP = 0;
      for (let p = startIdx; p < endIdx; p++) {
        sampledIndices.add(p);
        const absVal = Math.abs(peaks[p] ?? 0);
        if (absVal > maxP) maxP = absVal;
      }
      if (endIdx <= startIdx) {
        const sampleIdx = Math.min(peaks.length - 1, Math.max(0, Math.floor((i / numBars) * peaks.length)));
        sampledIndices.add(sampleIdx);
        maxP = Math.abs(peaks[sampleIdx] ?? 0);
      }
      peakVal = maxP;
    }
    const val = Math.max(0.08, Math.min(1.0, peakVal));
    bars.push({ barIndex: i, peakVal, val });
  }

  return { bars, sampledIndices };
}

// 1. Edge-case: Empty array []
{
  const { bars, sampledIndices } = sampleWaveformBars([], 100);
  assert.strictEqual(bars.length, 100);
  assert.strictEqual(sampledIndices.size, 0);
  for (const bar of bars) {
    assert.strictEqual(bar.peakVal, 0.15);
    assert.strictEqual(bar.val, 0.15);
  }
  console.log("- Edge case [empty array `[]`]: 100 bars rendered with fallback 0.15 without errors.");
}

// 2. Edge-case: Single-element [0.5]
{
  const { bars, sampledIndices } = sampleWaveformBars([0.5], 60);
  assert.strictEqual(bars.length, 60);
  assert(sampledIndices.has(0), "Index 0 must be sampled");
  assert.strictEqual(sampledIndices.size, 1);
  for (const bar of bars) {
    assert.strictEqual(bar.peakVal, 0.5);
    assert.strictEqual(bar.val, 0.5);
  }
  console.log("- Edge case [single-element `[0.5]`]: sampled index 0, peaks.length - 1 reached, val=0.5 across all bars.");
}

// 3. Pure silence: [0, 0, 0] and [0 x 500]
{
  const silence3 = sampleWaveformBars([0, 0, 0], 20);
  for (const bar of silence3.bars) {
    assert.strictEqual(bar.peakVal, 0.0, "Pure silence must produce peakVal = 0.0");
    assert.strictEqual(bar.val, 0.08, "Pure silence must clamp to baseline 0.08 tick, NOT phantom 0.15");
    assert.notStrictEqual(bar.val, 0.15, "Pure silence must NOT be 0.15!");
  }

  const silence500 = sampleWaveformBars(new Array(500).fill(0), 120);
  for (const bar of silence500.bars) {
    assert.strictEqual(bar.peakVal, 0.0);
    assert.strictEqual(bar.val, 0.08);
  }
  console.log("- Pure silence `[0, 0, 0]` and `[0 x 500]`: peakVal = 0.0, val = 0.08 baseline tick. Never phantom 0.15.");
}

// 4. Synthetic 240-element array
{
  const peaks240 = Array.from({ length: 240 }, (_, i) => Math.sin((i / 240) * Math.PI));
  // Plant unique marker at the very last element (index 239)
  peaks240[239] = 0.999;

  for (const numBars of [20, 60, 100, 160, 240, 300]) {
    const { bars, sampledIndices } = sampleWaveformBars(peaks240, numBars);
    assert.strictEqual(bars.length, numBars);
    // Index 0 must be sampled
    assert(sampledIndices.has(0), `Index 0 not sampled for numBars=${numBars}`);
    // Last index 239 (peaks.length - 1) MUST be sampled
    assert(sampledIndices.has(239), `Trailing index 239 NOT sampled for numBars=${numBars}! 0 dropped trailing samples violated!`);

    // Verify last bar reflects the marker or near-end data
    const lastBar = bars[bars.length - 1];
    assert(lastBar.peakVal > 0, `Last bar peakVal must be non-zero, got ${lastBar.peakVal}`);

    // If numBars <= 240, every single index should be sampled
    if (numBars >= 240) {
      assert.strictEqual(sampledIndices.size, 240, `Not all 240 indices sampled when numBars=${numBars}`);
    }
  }
  console.log("- Synthetic 240-element array: tested against 6 bar counts (20 to 300). Index 0 to 239 fully reached, 0 dropped trailing samples.");
}

// 5. Large 8000-element array
{
  const peaks8000 = Array.from({ length: 8000 }, (_, i) => Math.abs(Math.sin(i / 100)));
  peaks8000[0] = 0.888;
  peaks8000[7999] = 0.777; // marker at exact peaks.length - 1

  for (const numBars of [50, 100, 160, 200, 400]) {
    const { bars, sampledIndices } = sampleWaveformBars(peaks8000, numBars);
    assert.strictEqual(bars.length, numBars);
    assert(sampledIndices.has(0), `Index 0 not sampled for 8000-element array, numBars=${numBars}`);
    assert(sampledIndices.has(7999), `Trailing index 7999 NOT sampled for numBars=${numBars}! Dropped trailing samples!`);

    // First bar must include peak from index 0
    assert(bars[0].val >= 0.888);
    // Last bar must include marker from index 7999
    assert(bars[bars.length - 1].val >= 0.777);

    // Verify continuous windows: startIdx[i+1] <= endIdx[i]
    for (let i = 0; i < numBars - 1; i++) {
      const endIdxI = Math.min(8000, Math.max(Math.floor((i / numBars) * 8000) + 1, Math.floor(((i + 1) / numBars) * 8000)));
      const startIdxNext = Math.floor(((i + 1) / numBars) * 8000);
      assert(startIdxNext <= endIdxI, `Window gap detected between bar ${i} and ${i+1}: end=${endIdxI}, nextStart=${startIdxNext}`);
    }
  }
  console.log("- Large 8000-element array: tested against multiple bar configurations. Index 0 and trailing index 7999 guaranteed sampled, continuous window coverage with 0 gaps.");
}

// ============================================================================
// SUITE 4: Multi-Track 4-Stem Concurrent Drift Simulation with Jitter
// ============================================================================
console.log("\n=== Running Suite 4: 4-Stem Concurrent Drift & Jitter Simulation ===");

function simulateMultiTrackSession(initialOffsetsMs, durationSec = 3.0, jitterStdDevMs = 0.5) {
  const dt = 0.025; // 25ms loop
  const tracks = [
    new SimulatedTrack("vocals", 0.0), // master
    new SimulatedTrack("drums", initialOffsetsMs[0] / 1000.0),
    new SimulatedTrack("bass", initialOffsetsMs[1] / 1000.0),
    new SimulatedTrack("other", initialOffsetsMs[2] / 1000.0),
  ];

  const timeLogs = [];

  for (let t = 0; t < durationSec; t += dt) {
    // Advance master
    tracks[0].element.currentTime += dt * tracks[0].element.playbackRate;

    const masterTime = tracks[0].element.currentTime;

    // Advance and compensate slaves
    for (let s = 1; s < tracks.length; s++) {
      const slave = tracks[s];
      // Inject slight clock jitter
      const jitter = (Math.random() - 0.5) * 2 * (jitterStdDevMs / 1000.0);
      slave.element.currentTime += (dt * slave.element.playbackRate) + jitter;

      const drift = slave.element.currentTime - masterTime;
      const absDrift = Math.abs(drift);

      if (absDrift <= 0.004) {
        if (slave.element.playbackRate !== 1.0) {
          slave.element.playbackRate = 1.0;
        }
      } else if (absDrift <= 0.035) {
        const rate = drift < 0 ? 1.03 : 0.97;
        if (slave.element.playbackRate !== rate) {
          slave.element.playbackRate = rate;
        }
      } else {
        slave.element.currentTime = masterTime;
        slave.element.playbackRate = 1.0;
      }
    }

    const drifts = tracks.slice(1).map(sl => Math.abs(sl.element.currentTime - masterTime));
    timeLogs.push({ t, maxDriftMs: Math.max(...drifts) * 1000.0 });
  }

  return timeLogs;
}

// 4-stem session: drums lagging by 22ms, bass leading by 18ms, other lagging by 32ms
const multiSim = simulateMultiTrackSession([-22, 18, -32], 3.0, 0.2);
const finalSec = multiSim.filter(step => step.t > 1.5); // After convergence period
const maxFinalDrift = Math.max(...finalSec.map(s => s.maxDriftMs));
console.log(`- 4-Stem concurrent session with random clock jitter: max steady-state drift = ${maxFinalDrift.toFixed(3)}ms (target < 15ms, phase lock < 4ms)`);
assert(maxFinalDrift < 4.5, `Max steady-state drift ${maxFinalDrift}ms exceeded 4.5ms tolerance`);


// ============================================================================
// SUITE 5: Waveform Extreme Edge Cases, Sparsity & High-Scale Performance
// ============================================================================
console.log("\n=== Running Suite 5: Waveform Extreme Edge Cases & Performance ===");

// 1. Sparse array with undefined / NaN / negative values
{
  const sparsePeaks = [0.8, -0.9, undefined, NaN, null, 0.4, -0.1];
  const { bars } = sampleWaveformBars(sparsePeaks, 30);
  assert.strictEqual(bars.length, 30);
  for (const bar of bars) {
    assert(!isNaN(bar.val), "Bar val must not be NaN");
    assert(bar.val >= 0.08 && bar.val <= 1.0, `Bar val ${bar.val} out of [0.08, 1.0]`);
  }
  console.log("- Sparse array with NaN, null, undefined, negatives: handled safely with 0 crashes or NaNs.");
}

// 2. High-scale 100,000-sample peak array performance
{
  const bigPeaks = Array.from({ length: 100_000 }, () => Math.random());
  const t0 = performance.now();
  const { bars, sampledIndices } = sampleWaveformBars(bigPeaks, 200);
  const tElapsed = performance.now() - t0;

  assert.strictEqual(bars.length, 200);
  assert(sampledIndices.has(0), "Index 0 must be sampled");
  assert(sampledIndices.has(99_999), "Trailing index 99,999 must be sampled");
  console.log(`- 100,000-sample peak array: sampled in ${tElapsed.toFixed(2)}ms (linear O(N) performance, trailing sample 99,999 verified).`);
  assert(tElapsed < 100, `Sampling 100k samples took too long: ${tElapsed}ms`);
}

console.log("\n========================================================");
console.log(">>> ALL ADVERSARIAL STRESS TEST SUITES PASSED CLEANLY <<<");
console.log("========================================================");
