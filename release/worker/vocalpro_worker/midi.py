"""Stem-to-MIDI pitch tracking and Standard MIDI File (SMF Format 0) export for VocalPro v3 Worker."""

from __future__ import annotations

import os
import struct
from pathlib import Path

import librosa
import numpy as np
import scipy.ndimage

from .engine import resolve_ffmpeg


def stem_to_midi_file(stem_path: str | Path, output_midi_path: str | Path) -> int:
    """Extract monophonic pitch contour via librosa.pyin and write a Format-0 MIDI file.

    Matches api_server/main.py:1199-1277:
    - sr=22050, hop_length=512, fmin=C2 (~65.41 Hz), fmax=C7 (~2093.0 Hz)
    - 5-frame median filter on quantized MIDI note numbers
    - Minimum note duration: 3 frames (~69.7 ms)
    - 480 ticks/beat, 120 BPM (500,000 us/quarter-note), velocity 100
    """
    ffmpeg_bin = resolve_ffmpeg()
    if ffmpeg_bin and Path(ffmpeg_bin).is_file():
        ffmpeg_dir = str(Path(ffmpeg_bin).parent)
        cur_path = os.environ.get("PATH", "")
        if ffmpeg_dir not in cur_path.split(os.pathsep):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + cur_path

    y, sr = librosa.load(str(stem_path), sr=22050, mono=True)
    if len(y) == 0:
        raise ValueError(f"Empty audio file: {stem_path}")

    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=sr,
        hop_length=512,
    )

    midi_notes = np.where(
        voiced_flag & ~np.isnan(f0),
        np.round(librosa.hz_to_midi(np.nan_to_num(f0, nan=1.0))),
        0,
    ).astype(int)
    midi_notes = scipy.ndimage.median_filter(midi_notes, size=5)

    hop_time = 512.0 / float(sr)
    ticks_per_beat = 480
    tempo_bpm = 120.0
    ticks_per_sec = ticks_per_beat * (tempo_bpm / 60.0)

    events: list[tuple[int, int, int, int]] = []
    cur_note = 0
    note_start = 0

    for i, note in enumerate(midi_notes):
        if note != cur_note:
            if cur_note > 0 and (i - note_start) >= 3:
                start_tick = int(note_start * hop_time * ticks_per_sec)
                end_tick = int(i * hop_time * ticks_per_sec)
                events.append((start_tick, 0x90, int(cur_note), 100))
                events.append((end_tick, 0x80, int(cur_note), 0))
            cur_note = int(note)
            note_start = i

    if cur_note > 0 and (len(midi_notes) - note_start) >= 3:
        start_tick = int(note_start * hop_time * ticks_per_sec)
        end_tick = int(len(midi_notes) * hop_time * ticks_per_sec)
        events.append((start_tick, 0x90, int(cur_note), 100))
        events.append((end_tick, 0x80, int(cur_note), 0))

    events.sort(key=lambda x: x[0])

    def encode_varlen(val: int) -> bytes:
        buf = [val & 0x7F]
        val >>= 7
        while val > 0:
            buf.append((val & 0x7F) | 0x80)
            val >>= 7
        return bytes(reversed(buf))

    track_data = bytearray()
    # Tempo meta-event: 120 BPM = 500,000 microseconds per quarter note
    track_data += b"\x00\xff\x51\x03" + (500000).to_bytes(3, "big")

    last_tick = 0
    for tick, status, note, vel in events:
        delta = max(0, tick - last_tick)
        track_data += encode_varlen(delta) + bytes([status, note & 0x7F, vel & 0x7F])
        last_tick = tick

    # End-of-track meta-event
    track_data += b"\x00\xff\x2f\x00"

    midi_bytes = bytearray()
    midi_bytes += b"MThd" + struct.pack(">IHHH", 6, 0, 1, ticks_per_beat)
    midi_bytes += b"MTrk" + struct.pack(">I", len(track_data)) + track_data

    out_path = Path(output_midi_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(midi_bytes))

    return len(events) // 2
