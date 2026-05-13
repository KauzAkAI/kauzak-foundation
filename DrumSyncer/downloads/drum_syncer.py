#!/usr/bin/env python3
"""
DRUM SYNCER v1.0 — Kauzak Foundation
Automated drum cover video production pipeline.

Takes a drum cover video and an original song, then:
1. Separates drums from original song (Demucs)
2. Extracts drum audio from the cover video (Demucs)
3. Beat-aligns the drum track to the backing track
4. Mixes aligned drums + drumless backing
5. Syncs mixed audio to video
6. Exports finished video

TEST MODE: Takes a single drum cover video, separates it into parts,
then reassembles to verify the pipeline works.
"""

import os
import sys
import json
import subprocess
import tempfile
import shutil
import argparse
import time
from pathlib import Path

import numpy as np
import librosa
import soundfile as sf
from scipy import signal
from moviepy import VideoFileClip, AudioFileClip


def log(msg, level="INFO"):
    """Simple logger."""
    print(f"[{level}] {msg}")


def extract_audio(video_path, output_path, sr=44100):
    """Extract audio from video file using ffmpeg."""
    log(f"Extracting audio from {Path(video_path).name}")
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vn', '-acodec', 'pcm_s16le',
        '-ar', str(sr), '-ac', '2',
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    log(f"Audio extracted: {output_path}")
    return output_path


def separate_stems(audio_path, output_dir, model='htdemucs'):
    """Separate audio into stems using Demucs."""
    log(f"Running Demucs stem separation (model: {model})...")
    log("This may take a few minutes on CPU...")

    demucs_bin = shutil.which('demucs') or os.path.expanduser(
        '~/.local/bin/demucs'
    )

    cmd = [
        sys.executable, '-m', 'demucs',
        '-n', model,
        '--out', output_dir,
        '--device', 'cpu',
        '--two-stems', 'drums',  # Only separate drums vs other
        audio_path
    ]

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start

    if result.returncode != 0:
        log(f"Demucs stderr: {result.stderr}", "ERROR")
        raise RuntimeError(f"Demucs failed: {result.stderr}")

    log(f"Demucs finished in {elapsed:.1f}s")

    # Find output stems
    stem_name = Path(audio_path).stem
    stem_dir = os.path.join(output_dir, model, stem_name)

    drums_path = os.path.join(stem_dir, 'drums.wav')
    other_path = os.path.join(stem_dir, 'no_drums.wav')

    if not os.path.exists(drums_path):
        # List what's actually there
        if os.path.exists(stem_dir):
            files = os.listdir(stem_dir)
            log(f"Files in {stem_dir}: {files}", "DEBUG")
            # Try 'other.wav' if 'no_drums.wav' doesn't exist
            if 'other.wav' in files:
                other_path = os.path.join(stem_dir, 'other.wav')
        else:
            log(f"Stem dir not found: {stem_dir}", "ERROR")
            # Search for it
            for root, dirs, files in os.walk(output_dir):
                if 'drums.wav' in files:
                    drums_path = os.path.join(root, 'drums.wav')
                    for f in files:
                        if f != 'drums.wav' and f.endswith('.wav'):
                            other_path = os.path.join(root, f)
                    log(f"Found stems in: {root}")
                    break

    return drums_path, other_path


def detect_beats(audio_path, sr=44100):
    """Detect beats and tempo in an audio file."""
    log(f"Detecting beats in {Path(audio_path).name}")
    y, sr = librosa.load(audio_path, sr=sr, mono=True)

    # Get tempo and beat frames
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # Get onset strength for correlation
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)

    # Handle tempo - could be array or scalar
    if hasattr(tempo, '__len__'):
        tempo_val = float(tempo[0]) if len(tempo) > 0 else 120.0
    else:
        tempo_val = float(tempo)

    log(f"  Tempo: {tempo_val:.1f} BPM, Beats found: {len(beat_times)}")
    return {
        'tempo': tempo_val,
        'beat_times': beat_times,
        'onset_env': onset_env,
        'audio': y,
        'sr': sr
    }


def find_sync_offset(onset_env1, onset_env2):
    """Find the time offset between two audio tracks using cross-correlation."""
    log("Computing cross-correlation for sync offset...")

    # Normalize
    env1 = onset_env1 / (np.max(np.abs(onset_env1)) + 1e-8)
    env2 = onset_env2 / (np.max(np.abs(onset_env2)) + 1e-8)

    # Cross-correlate
    correlation = signal.correlate(env1, env2, mode='full')
    lag = np.argmax(correlation) - len(env2) + 1

    # Convert lag from frames to seconds (librosa default hop = 512, sr = 44100)
    hop_length = 512
    sr = 44100
    offset_seconds = lag * hop_length / sr

    confidence = np.max(correlation) / (np.sqrt(np.sum(env1**2) * np.sum(env2**2)) + 1e-8)

    log(f"  Sync offset: {offset_seconds:.4f}s (lag={lag} frames, confidence={confidence:.3f})")
    return offset_seconds, confidence


def time_stretch_audio(y, sr, rate):
    """Time-stretch audio without changing pitch."""
    if abs(rate - 1.0) < 0.001:
        log("  No time-stretching needed (tempos match)")
        return y
    log(f"  Time-stretching by factor {rate:.4f}")
    return librosa.effects.time_stretch(y, rate=rate)


def mix_audio(backing_path, drums_path, output_path, drum_offset=0.0,
              drum_gain_db=0.0, backing_gain_db=0.0, sr=44100):
    """Mix backing track and drums with offset and gain adjustment."""
    log("Mixing audio tracks...")

    # Load
    backing, _ = librosa.load(backing_path, sr=sr, mono=False)
    drums, _ = librosa.load(drums_path, sr=sr, mono=False)

    # Ensure stereo
    if backing.ndim == 1:
        backing = np.stack([backing, backing])
    if drums.ndim == 1:
        drums = np.stack([drums, drums])

    # Apply gain
    backing *= 10 ** (backing_gain_db / 20)
    drums *= 10 ** (drum_gain_db / 20)

    # Apply offset (in samples)
    offset_samples = int(drum_offset * sr)

    # Determine output length
    if offset_samples >= 0:
        drum_start = offset_samples
        back_start = 0
    else:
        drum_start = 0
        back_start = -offset_samples

    out_len = max(backing.shape[1] + back_start, drums.shape[1] + drum_start)
    mixed = np.zeros((2, out_len), dtype=np.float32)

    # Add backing
    mixed[:, back_start:back_start + backing.shape[1]] += backing

    # Add drums
    end = min(drum_start + drums.shape[1], out_len)
    drum_len = end - drum_start
    mixed[:, drum_start:end] += drums[:, :drum_len]

    # Normalize to prevent clipping
    peak = np.max(np.abs(mixed))
    if peak > 0.95:
        mixed *= 0.95 / peak
        log(f"  Normalized peak from {peak:.2f} to 0.95")

    # Write
    sf.write(output_path, mixed.T, sr)
    log(f"  Mixed audio written: {output_path}")
    return output_path


def sync_video_audio(video_path, audio_path, output_path, audio_offset=0.0):
    """Combine video with new audio track."""
    log("Syncing video with mixed audio...")

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', audio_path,
        '-map', '0:v',
        '-map', '1:a',
        '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        output_path
    ]

    if audio_offset > 0:
        # Delay audio
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-itsoffset', str(audio_offset),
            '-i', audio_path,
            '-map', '0:v',
            '-map', '1:a',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            output_path
        ]
    elif audio_offset < 0:
        # Delay video (trim audio start)
        cmd = [
            'ffmpeg', '-y',
            '-itsoffset', str(-audio_offset),
            '-i', video_path,
            '-i', audio_path,
            '-map', '0:v',
            '-map', '1:a',
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            output_path
        ]

    subprocess.run(cmd, capture_output=True, check=True)
    log(f"Output video: {output_path}")
    return output_path


def run_test_mode(video_path, work_dir):
    """
    Test mode: Take a drum cover video, separate it, then reassemble.
    If the output sounds like the original, the pipeline works.
    """
    log("=" * 60)
    log("DRUM SYNCER — TEST MODE")
    log("=" * 60)
    log(f"Input: {video_path}")
    log(f"Work dir: {work_dir}")
    log("")

    os.makedirs(work_dir, exist_ok=True)
    sr = 44100

    # Step 1: Extract audio from video
    log("STEP 1: Extract audio from video")
    raw_audio = os.path.join(work_dir, 'raw_audio.wav')
    extract_audio(video_path, raw_audio, sr=sr)

    # Step 2: Separate into drums + backing using Demucs
    log("\nSTEP 2: Separate stems (Demucs)")
    stems_dir = os.path.join(work_dir, 'stems')
    drums_path, backing_path = separate_stems(raw_audio, stems_dir)

    if not os.path.exists(drums_path):
        log("FATAL: Drums stem not found!", "ERROR")
        return None

    log(f"  Drums: {drums_path}")
    log(f"  Backing: {backing_path}")

    # Step 3: Detect beats in both tracks
    log("\nSTEP 3: Beat detection")
    drums_info = detect_beats(drums_path, sr=sr)
    backing_info = detect_beats(backing_path, sr=sr)

    log(f"  Drums tempo: {drums_info['tempo']:.1f} BPM")
    log(f"  Backing tempo: {backing_info['tempo']:.1f} BPM")

    # Step 4: Find sync offset
    log("\nSTEP 4: Find sync offset via cross-correlation")
    offset, confidence = find_sync_offset(
        backing_info['onset_env'],
        drums_info['onset_env']
    )

    # Step 5: Check if tempo alignment needed
    log("\nSTEP 5: Tempo analysis")
    tempo_ratio = drums_info['tempo'] / backing_info['tempo']
    log(f"  Tempo ratio: {tempo_ratio:.4f}")

    if abs(tempo_ratio - 1.0) > 0.02:
        log("  Tempos differ — would need time-stretching in production mode")
        log("  (Skipping in test mode since both came from same source)")

    # Step 6: Mix
    log("\nSTEP 6: Mix drums + backing")
    mixed_audio = os.path.join(work_dir, 'mixed_audio.wav')
    mix_audio(backing_path, drums_path, mixed_audio,
              drum_offset=0.0,  # No offset in test mode (same source)
              sr=sr)

    # Step 7: Sync to video
    log("\nSTEP 7: Sync mixed audio to video")
    output_video = os.path.join(work_dir, 'output_synced.mp4')
    sync_video_audio(video_path, mixed_audio, output_video)

    # Report
    log("\n" + "=" * 60)
    log("TEST COMPLETE")
    log("=" * 60)

    orig_size = os.path.getsize(video_path)
    out_size = os.path.getsize(output_video)
    log(f"  Original: {orig_size/1024/1024:.1f} MB")
    log(f"  Output:   {out_size/1024/1024:.1f} MB")

    # Also save individual stems for comparison
    log("\nFiles produced:")
    log(f"  Drums only:    {drums_path}")
    log(f"  Backing only:  {backing_path}")
    log(f"  Mixed audio:   {mixed_audio}")
    log(f"  Final video:   {output_video}")

    return output_video


def run_production_mode(original_song, drum_recording, video_path, output_path, work_dir):
    """
    Production mode: Full pipeline with separate inputs.
    """
    log("=" * 60)
    log("DRUM SYNCER — PRODUCTION MODE")
    log("=" * 60)
    log(f"Original song: {original_song}")
    log(f"Drum recording: {drum_recording}")
    log(f"Video: {video_path}")
    log(f"Output: {output_path}")
    log("")

    os.makedirs(work_dir, exist_ok=True)
    sr = 44100

    # Step 1: Separate drums from original song to get clean backing
    log("STEP 1: Strip drums from original song")
    stems_dir = os.path.join(work_dir, 'stems_original')
    _, backing_path = separate_stems(original_song, stems_dir)

    # Step 2: Load drum recording (could be audio file or extract from video)
    log("\nSTEP 2: Prepare drum recording")
    if drum_recording.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
        drum_audio = os.path.join(work_dir, 'drum_recording.wav')
        extract_audio(drum_recording, drum_audio, sr=sr)
    else:
        drum_audio = drum_recording

    # Step 3: Beat detection
    log("\nSTEP 3: Beat detection")
    backing_info = detect_beats(backing_path, sr=sr)
    drums_info = detect_beats(drum_audio, sr=sr)

    # Step 4: Tempo alignment
    log("\nSTEP 4: Tempo alignment")
    tempo_ratio = drums_info['tempo'] / backing_info['tempo']
    log(f"  Tempo ratio: {tempo_ratio:.4f}")

    aligned_drums = drum_audio
    if abs(tempo_ratio - 1.0) > 0.02:
        log("  Applying time-stretch to match tempos")
        y_stretched = time_stretch_audio(
            drums_info['audio'], drums_info['sr'], tempo_ratio
        )
        aligned_drums = os.path.join(work_dir, 'drums_stretched.wav')
        sf.write(aligned_drums, y_stretched, sr)

        # Re-detect beats on stretched version
        drums_info = detect_beats(aligned_drums, sr=sr)

    # Step 5: Find sync offset
    log("\nSTEP 5: Find sync offset")
    offset, confidence = find_sync_offset(
        backing_info['onset_env'],
        drums_info['onset_env']
    )

    # Step 6: Mix
    log("\nSTEP 6: Mix")
    mixed_audio = os.path.join(work_dir, 'mixed_audio.wav')
    mix_audio(backing_path, aligned_drums, mixed_audio,
              drum_offset=offset, sr=sr)

    # Step 7: Sync to video
    log("\nSTEP 7: Sync to video")
    sync_video_audio(video_path, mixed_audio, output_path)

    log("\n" + "=" * 60)
    log("PRODUCTION COMPLETE")
    log("=" * 60)
    log(f"  Output: {output_path}")
    log(f"  Size: {os.path.getsize(output_path)/1024/1024:.1f} MB")

    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Drum Syncer — Automated drum cover video pipeline')

    subparsers = parser.add_subparsers(dest='mode', help='Operating mode')

    # Test mode
    test_parser = subparsers.add_parser('test', help='Test mode: separate and reassemble a video')
    test_parser.add_argument('video', help='Path to drum cover video')
    test_parser.add_argument('--workdir', default='./work', help='Working directory')

    # Production mode
    prod_parser = subparsers.add_parser('produce', help='Production mode: full pipeline')
    prod_parser.add_argument('--song', required=True, help='Original song audio file')
    prod_parser.add_argument('--drums', required=True, help='Drum recording (audio or video)')
    prod_parser.add_argument('--video', required=True, help='Video of drummer')
    prod_parser.add_argument('--output', required=True, help='Output video path')
    prod_parser.add_argument('--workdir', default='./work', help='Working directory')

    args = parser.parse_args()

    if args.mode == 'test':
        run_test_mode(args.video, args.workdir)
    elif args.mode == 'produce':
        run_production_mode(args.song, args.drums, args.video, args.output, args.workdir)
    else:
        parser.print_help()
