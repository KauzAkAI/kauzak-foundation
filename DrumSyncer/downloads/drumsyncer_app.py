#!/usr/bin/env python3
"""
DRUM SYNCER v2.0 — Kauzak Foundation
드럼싱커 v2.0 — 카우작 재단

Web-based drum cover video production tool.
Bilingual English/Korean interface.
Supports YouTube URL input + file upload.

Usage:
    python drumsyncer_app.py
    → Opens http://localhost:5151 in your browser

"""

import os
import sys
import json
import subprocess
import threading
import time
import webbrowser
import uuid
import shutil
import re
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_file, send_from_directory

import numpy as np
import librosa
import soundfile as sf
from scipy import signal

# ── App Setup ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

UPLOAD_DIR = os.path.join(BASE_DIR, 'data', 'uploads')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data', 'output')
WORK_DIR = os.path.join(BASE_DIR, 'data', 'work')

for d in [UPLOAD_DIR, OUTPUT_DIR, WORK_DIR]:
    os.makedirs(d, exist_ok=True)

# Global job tracking
jobs = {}


# ── YouTube Download ──────────────────────────────────────
def find_ytdlp():
    """Find yt-dlp binary or Python module."""
    # Check PATH for CLI binary
    path = shutil.which('yt-dlp')
    if path:
        return ('binary', path)
    # Check local bin
    local = os.path.join(BASE_DIR, 'bin', 'yt-dlp.exe')
    if os.path.exists(local):
        return ('binary', local)
    local2 = os.path.join(BASE_DIR, 'bin', 'yt-dlp')
    if os.path.exists(local2):
        return ('binary', local2)
    # Check Python module
    try:
        import yt_dlp
        return ('module', sys.executable)
    except ImportError:
        pass
    return None


def download_youtube(url, output_dir, job_id=None):
    """Download video from YouTube URL using yt-dlp."""
    ytdlp_info = find_ytdlp()
    if not ytdlp_info:
        raise RuntimeError("yt-dlp not found. Please install it: pip install yt-dlp")

    file_id = str(uuid.uuid4())[:8]
    output_template = os.path.join(output_dir, f'{file_id}_%(title).50s.%(ext)s')

    mode, path = ytdlp_info
    if mode == 'binary':
        cmd = [path]
    else:
        cmd = [path, '-m', 'yt_dlp']

    cmd += [
        '-f', 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best',
        '--merge-output-format', 'mp4',
        '--no-playlist',
        '-o', output_template,
        '--progress',
        url
    ]

    if job_id:
        update_job(job_id,
                   message=f'Downloading video from YouTube...',
                   message_kr='YouTube에서 영상 다운로드 중...')

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[-300:]}")

    # Find the downloaded file
    for f in os.listdir(output_dir):
        if f.startswith(file_id) and f.endswith('.mp4'):
            return os.path.join(output_dir, f), f

    # Fallback: find any recent mp4
    files = sorted(Path(output_dir).glob('*.mp4'), key=os.path.getmtime, reverse=True)
    if files:
        return str(files[0]), files[0].name

    raise RuntimeError("Download completed but output file not found")


def is_youtube_url(text):
    """Check if text is a YouTube URL."""
    patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=',
        r'(https?://)?(www\.)?youtu\.be/',
        r'(https?://)?(www\.)?youtube\.com/shorts/',
    ]
    return any(re.search(p, text) for p in patterns)


# ── Processing Pipeline ───────────────────────────────────
def update_job(job_id, **kwargs):
    if job_id in jobs:
        jobs[job_id].update(kwargs)
        jobs[job_id]['updated'] = time.time()


def extract_audio(video_path, output_path, sr=44100):
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vn', '-acodec', 'pcm_s16le',
        '-ar', str(sr), '-ac', '2',
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def separate_stems(audio_path, output_dir, job_id):
    update_job(job_id, step=2, step_name='stem_separation',
               message='Running AI stem separation (Demucs)...',
               message_kr='AI 스템 분리 실행 중 (Demucs)...')

    cmd = [
        sys.executable, '-m', 'demucs',
        '-n', 'htdemucs',
        '--out', output_dir,
        '--device', 'cpu',
        '--two-stems', 'drums',
        audio_path
    ]

    # Check for GPU
    try:
        import torch
        if torch.cuda.is_available():
            cmd[cmd.index('cpu')] = 'cuda'
    except:
        pass

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start

    if result.returncode != 0:
        raise RuntimeError(f"Demucs failed: {result.stderr[-500:]}")

    stem_name = Path(audio_path).stem
    stem_dir = os.path.join(output_dir, 'htdemucs', stem_name)

    drums_path = os.path.join(stem_dir, 'drums.wav')
    other_path = os.path.join(stem_dir, 'no_drums.wav')

    if not os.path.exists(other_path):
        other_path = os.path.join(stem_dir, 'other.wav')

    if not os.path.exists(drums_path):
        for root, dirs, files in os.walk(output_dir):
            if 'drums.wav' in files:
                drums_path = os.path.join(root, 'drums.wav')
                for f in files:
                    if f != 'drums.wav' and f.endswith('.wav'):
                        other_path = os.path.join(root, f)
                break

    return drums_path, other_path, elapsed


def detect_beats(audio_path, sr=44100):
    y, sr = librosa.load(audio_path, sr=sr, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)

    if hasattr(tempo, '__len__'):
        tempo_val = float(tempo[0]) if len(tempo) > 0 else 120.0
    else:
        tempo_val = float(tempo)

    return {
        'tempo': tempo_val,
        'beat_count': len(beat_times),
        'onset_env': onset_env,
        'audio': y,
        'sr': sr
    }


def find_sync_offset(onset_env1, onset_env2):
    env1 = onset_env1 / (np.max(np.abs(onset_env1)) + 1e-8)
    env2 = onset_env2 / (np.max(np.abs(onset_env2)) + 1e-8)
    correlation = signal.correlate(env1, env2, mode='full')
    lag = np.argmax(correlation) - len(env2) + 1
    offset_seconds = lag * 512 / 44100
    confidence = np.max(correlation) / (np.sqrt(np.sum(env1**2) * np.sum(env2**2)) + 1e-8)
    return offset_seconds, confidence


def mix_audio(backing_path, drums_path, output_path, drum_offset=0.0,
              drum_gain_db=0.0, backing_gain_db=0.0, sr=44100):
    backing, _ = librosa.load(backing_path, sr=sr, mono=False)
    drums, _ = librosa.load(drums_path, sr=sr, mono=False)

    if backing.ndim == 1:
        backing = np.stack([backing, backing])
    if drums.ndim == 1:
        drums = np.stack([drums, drums])

    backing *= 10 ** (backing_gain_db / 20)
    drums *= 10 ** (drum_gain_db / 20)

    offset_samples = int(drum_offset * sr)
    drum_start = max(0, offset_samples)
    back_start = max(0, -offset_samples)

    out_len = max(backing.shape[1] + back_start, drums.shape[1] + drum_start)
    mixed = np.zeros((2, out_len), dtype=np.float32)
    mixed[:, back_start:back_start + backing.shape[1]] += backing
    end = min(drum_start + drums.shape[1], out_len)
    mixed[:, drum_start:end] += drums[:, :end - drum_start]

    peak = np.max(np.abs(mixed))
    if peak > 0.95:
        mixed *= 0.95 / peak

    sf.write(output_path, mixed.T, sr)
    return output_path


def sync_video_audio(video_path, audio_path, output_path, audio_offset=0.0):
    if audio_offset > 0:
        cmd = ['ffmpeg', '-y', '-i', video_path, '-itsoffset', str(audio_offset),
               '-i', audio_path, '-map', '0:v', '-map', '1:a',
               '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', output_path]
    elif audio_offset < 0:
        cmd = ['ffmpeg', '-y', '-itsoffset', str(-audio_offset), '-i', video_path,
               '-i', audio_path, '-map', '0:v', '-map', '1:a',
               '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', output_path]
    else:
        cmd = ['ffmpeg', '-y', '-i', video_path, '-i', audio_path,
               '-map', '0:v', '-map', '1:a',
               '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', output_path]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def run_pipeline(job_id, mode, files):
    """Main pipeline runner - runs in background thread."""
    try:
        sr = 44100
        job_work = os.path.join(WORK_DIR, job_id)
        os.makedirs(job_work, exist_ok=True)
        total_start = time.time()

        if mode == 'test':
            video_path = files['video']

            # Step 1: Extract audio
            update_job(job_id, step=1, step_name='extract_audio',
                       message='Extracting audio from video...',
                       message_kr='비디오에서 오디오 추출 중...')
            raw_audio = os.path.join(job_work, 'raw_audio.wav')
            extract_audio(video_path, raw_audio, sr=sr)

            # Step 2: Stem separation
            stems_dir = os.path.join(job_work, 'stems')
            drums_path, backing_path, demucs_time = separate_stems(raw_audio, stems_dir, job_id)
            update_job(job_id, demucs_time=f"{demucs_time:.1f}s")

            # Step 3: Beat detection
            update_job(job_id, step=3, step_name='beat_detection',
                       message='Detecting beats and tempo...',
                       message_kr='비트 및 템포 감지 중...')
            drums_info = detect_beats(drums_path, sr=sr)
            backing_info = detect_beats(backing_path, sr=sr)
            update_job(job_id,
                       drums_tempo=f"{drums_info['tempo']:.1f}",
                       backing_tempo=f"{backing_info['tempo']:.1f}",
                       drums_beats=drums_info['beat_count'],
                       backing_beats=backing_info['beat_count'])

            # Step 4: Sync offset
            update_job(job_id, step=4, step_name='sync_offset',
                       message='Computing sync alignment...',
                       message_kr='동기화 정렬 계산 중...')
            offset, confidence = find_sync_offset(
                backing_info['onset_env'], drums_info['onset_env'])
            update_job(job_id, sync_offset=f"{offset:.4f}s", sync_confidence=f"{confidence:.3f}")

            # Step 5: Mix
            update_job(job_id, step=5, step_name='mixing',
                       message='Mixing audio tracks...',
                       message_kr='오디오 트랙 믹싱 중...')
            mixed_audio = os.path.join(job_work, 'mixed_audio.wav')
            mix_audio(backing_path, drums_path, mixed_audio, drum_offset=0.0, sr=sr)

            # Step 6: Sync video
            update_job(job_id, step=6, step_name='video_sync',
                       message='Syncing audio to video...',
                       message_kr='오디오를 비디오에 동기화 중...')
            output_video = os.path.join(OUTPUT_DIR, f'{job_id}_output.mp4')
            sync_video_audio(video_path, mixed_audio, output_video)

            # Copy stems
            drums_out = os.path.join(OUTPUT_DIR, f'{job_id}_drums.wav')
            backing_out = os.path.join(OUTPUT_DIR, f'{job_id}_backing.wav')
            shutil.copy2(drums_path, drums_out)
            shutil.copy2(backing_path, backing_out)

            total_time = time.time() - total_start
            update_job(job_id, step=7, step_name='complete', status='complete',
                       message='Complete! Your files are ready.',
                       message_kr='완료! 파일이 준비되었습니다.',
                       output_video=f'{job_id}_output.mp4',
                       output_drums=f'{job_id}_drums.wav',
                       output_backing=f'{job_id}_backing.wav',
                       output_size=f"{os.path.getsize(output_video)/1024/1024:.1f} MB",
                       total_time=f"{total_time:.1f}s")

        elif mode == 'produce':
            song_path = files['song']
            drum_path = files['drums']
            video_path = files['video']

            # Step 1: Strip drums from original
            update_job(job_id, step=1, step_name='strip_drums',
                       message='Removing drums from original song...',
                       message_kr='원곡에서 드럼 제거 중...')
            song_audio = os.path.join(job_work, 'song_audio.wav')
            if song_path.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
                extract_audio(song_path, song_audio, sr=sr)
            else:
                shutil.copy2(song_path, song_audio)

            stems_dir = os.path.join(job_work, 'stems')
            _, backing_path, demucs_time = separate_stems(song_audio, stems_dir, job_id)
            update_job(job_id, demucs_time=f"{demucs_time:.1f}s")

            # Step 2: Prepare drum recording
            update_job(job_id, step=2, step_name='prepare_drums',
                       message='Preparing drum recording...',
                       message_kr='드럼 녹음 준비 중...')
            if drum_path.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
                drum_audio = os.path.join(job_work, 'drum_recording.wav')
                extract_audio(drum_path, drum_audio, sr=sr)
            else:
                drum_audio = drum_path

            # Step 3: Beat detection
            update_job(job_id, step=3, step_name='beat_detection',
                       message='Detecting beats and tempo...',
                       message_kr='비트 및 템포 감지 중...')
            backing_info = detect_beats(backing_path, sr=sr)
            drums_info = detect_beats(drum_audio, sr=sr)
            update_job(job_id,
                       drums_tempo=f"{drums_info['tempo']:.1f}",
                       backing_tempo=f"{backing_info['tempo']:.1f}",
                       drums_beats=drums_info['beat_count'],
                       backing_beats=backing_info['beat_count'])

            # Step 4: Tempo + sync
            update_job(job_id, step=4, step_name='sync_offset',
                       message='Aligning tempo and finding sync point...',
                       message_kr='템포 정렬 및 동기화 지점 찾는 중...')
            tempo_ratio = drums_info['tempo'] / backing_info['tempo']
            if abs(tempo_ratio - 1.0) > 0.02:
                y_stretched = librosa.effects.time_stretch(drums_info['audio'], rate=tempo_ratio)
                drum_audio = os.path.join(job_work, 'drums_stretched.wav')
                sf.write(drum_audio, y_stretched, sr)
                drums_info = detect_beats(drum_audio, sr=sr)

            offset, confidence = find_sync_offset(
                backing_info['onset_env'], drums_info['onset_env'])
            update_job(job_id, sync_offset=f"{offset:.4f}s", sync_confidence=f"{confidence:.3f}")

            # Step 5: Mix
            update_job(job_id, step=5, step_name='mixing',
                       message='Mixing audio tracks...',
                       message_kr='오디오 트랙 믹싱 중...')
            mixed_audio = os.path.join(job_work, 'mixed_audio.wav')
            mix_audio(backing_path, drum_audio, mixed_audio, drum_offset=offset, sr=sr)

            # Step 6: Sync video
            update_job(job_id, step=6, step_name='video_sync',
                       message='Creating final video...',
                       message_kr='최종 비디오 생성 중...')
            output_video = os.path.join(OUTPUT_DIR, f'{job_id}_output.mp4')
            sync_video_audio(video_path, mixed_audio, output_video)

            total_time = time.time() - total_start
            update_job(job_id, step=7, step_name='complete', status='complete',
                       message='Complete! Your video is ready.',
                       message_kr='완료! 비디오가 준비되었습니다.',
                       output_video=f'{job_id}_output.mp4',
                       output_size=f"{os.path.getsize(output_video)/1024/1024:.1f} MB",
                       total_time=f"{total_time:.1f}s")

    except Exception as e:
        import traceback
        traceback.print_exc()
        update_job(job_id, status='error',
                   message=f'Error: {str(e)}',
                   message_kr=f'오류: {str(e)}')


# ── API Routes ─────────────────────────────────────────────
@app.route('/')
def index():
    return HTML_PAGE


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'No filename'}), 400

    file_id = str(uuid.uuid4())[:8]
    ext = Path(f.filename).suffix
    save_path = os.path.join(UPLOAD_DIR, f'{file_id}{ext}')
    f.save(save_path)

    return jsonify({
        'file_id': file_id,
        'filename': f.filename,
        'path': save_path,
        'size': os.path.getsize(save_path)
    })


@app.route('/api/fetch-url', methods=['POST'])
def fetch_url():
    """Download video from YouTube URL."""
    data = request.json
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    if not is_youtube_url(url):
        return jsonify({'error': 'Not a valid YouTube URL'}), 400

    try:
        filepath, filename = download_youtube(url, UPLOAD_DIR)
        return jsonify({
            'file_id': str(uuid.uuid4())[:8],
            'filename': filename,
            'path': filepath,
            'size': os.path.getsize(filepath),
            'source': 'youtube'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/start', methods=['POST'])
def start_job():
    data = request.json
    mode = data.get('mode', 'test')

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        'id': job_id,
        'mode': mode,
        'status': 'running',
        'step': 0,
        'step_name': 'starting',
        'message': 'Starting...',
        'message_kr': '시작 중...',
        'started': time.time()
    }

    files = {}
    if mode == 'test':
        files['video'] = data['video_path']
    else:
        files['song'] = data['song_path']
        files['drums'] = data['drums_path']
        files['video'] = data['video_path']

    thread = threading.Thread(target=run_pipeline, args=(job_id, mode, files))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id})


@app.route('/api/status/<job_id>')
def job_status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(jobs[job_id])


@app.route('/api/download/<filename>')
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


@app.route('/api/stream/<filename>')
def stream_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)


@app.route('/api/system-info')
def system_info():
    """Check system capabilities."""
    info = {
        'python': sys.version.split()[0],
        'ffmpeg': False,
        'ytdlp': False,
        'gpu': False,
        'platform': sys.platform,
    }
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        info['ffmpeg'] = True
    except:
        pass
    ytdlp_result = find_ytdlp()
    info['ytdlp'] = ytdlp_result is not None
    if ytdlp_result:
        info['ytdlp_mode'] = ytdlp_result[0]  # 'binary' or 'module'
    try:
        import torch
        info['gpu'] = torch.cuda.is_available()
        info['torch'] = torch.__version__
    except:
        pass
    return jsonify(info)


# ── HTML Page ──────────────────────────────────────────────
HTML_PAGE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DrumSyncer v2.0 — Kauzak Foundation</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🥁</text></svg>">
<style>
:root {
  --bg: #0a0a0b; --surface: #141416; --surface2: #1c1c20;
  --border: #2a2a30; --text: #e8e8ec; --text2: #9898a0;
  --accent: #dc1438; --accent2: #ff2950;
  --green: #22c55e; --blue: #3b82f6; --orange: #f59e0b;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',-apple-system,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; }
.container { max-width:960px; margin:0 auto; padding:24px; }
.header { display:flex; align-items:center; justify-content:space-between; padding:20px 0; border-bottom:1px solid var(--border); margin-bottom:32px; }
.header h1 { font-size:28px; font-weight:700; letter-spacing:-0.5px; }
.header h1 span { color:var(--accent); }
.header .subtitle { color:var(--text2); font-size:13px; margin-top:2px; }
.header .right { display:flex; gap:8px; align-items:center; }
.lang-toggle, .sys-btn { background:var(--surface2); border:1px solid var(--border); color:var(--text); padding:6px 14px; border-radius:6px; cursor:pointer; font-size:13px; transition:all .2s; }
.lang-toggle:hover, .sys-btn:hover { border-color:var(--accent); }
.mode-selector { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:32px; }
.mode-card { background:var(--surface); border:2px solid var(--border); border-radius:12px; padding:24px; cursor:pointer; transition:all .2s; }
.mode-card:hover { border-color:var(--text2); }
.mode-card.active { border-color:var(--accent); background:var(--surface2); }
.mode-card h3 { font-size:18px; margin-bottom:8px; }
.mode-card p { color:var(--text2); font-size:14px; line-height:1.5; }
.upload-section { margin-bottom:24px; }
.upload-section h3 { font-size:15px; margin-bottom:10px; display:flex; align-items:center; gap:8px; }
.upload-section h3 .num { background:var(--accent); color:white; width:24px; height:24px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; }
.input-method { display:flex; gap:8px; margin-bottom:10px; }
.input-method button { background:var(--surface2); border:1px solid var(--border); color:var(--text2); padding:6px 16px; border-radius:6px; cursor:pointer; font-size:13px; transition:all .2s; }
.input-method button.active { border-color:var(--accent); color:var(--text); background:var(--surface); }
.input-method button:hover { border-color:var(--accent); }
.url-input-group { display:flex; gap:8px; margin-bottom:8px; }
.url-input { flex:1; background:var(--surface); border:1px solid var(--border); color:var(--text); padding:10px 14px; border-radius:8px; font-size:14px; outline:none; }
.url-input:focus { border-color:var(--accent); }
.url-input::placeholder { color:#555; }
.url-fetch-btn { background:var(--accent); color:white; border:none; padding:10px 20px; border-radius:8px; cursor:pointer; font-size:14px; font-weight:600; transition:all .2s; white-space:nowrap; }
.url-fetch-btn:hover { background:var(--accent2); }
.url-fetch-btn:disabled { background:var(--surface2); color:var(--text2); cursor:not-allowed; }
.drop-zone { border:2px dashed var(--border); border-radius:10px; padding:36px; text-align:center; cursor:pointer; transition:all .2s; background:var(--surface); }
.drop-zone:hover, .drop-zone.dragover { border-color:var(--accent); background:var(--surface2); }
.drop-zone.has-file { border-color:var(--green); border-style:solid; }
.drop-zone .icon { font-size:36px; margin-bottom:8px; }
.drop-zone .label { color:var(--text2); font-size:14px; }
.drop-zone .filename { color:var(--green); font-size:14px; font-weight:600; word-break:break-all; }
.drop-zone .filesize { color:var(--text2); font-size:12px; margin-top:4px; }
.drop-zone input[type="file"] { display:none; }
.go-btn { width:100%; padding:16px; background:var(--accent); color:white; border:none; border-radius:10px; font-size:18px; font-weight:700; cursor:pointer; transition:all .2s; margin-top:16px; letter-spacing:.5px; }
.go-btn:hover { background:var(--accent2); transform:translateY(-1px); }
.go-btn:disabled { background:var(--surface2); color:var(--text2); cursor:not-allowed; transform:none; }
.progress-panel { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; margin-top:24px; display:none; }
.progress-panel.visible { display:block; }
.progress-bar-container { height:6px; background:var(--surface2); border-radius:3px; margin-bottom:20px; overflow:hidden; }
.progress-bar { height:100%; background:var(--accent); border-radius:3px; transition:width .5s ease; width:0%; }
.progress-bar.complete { background:var(--green); }
.step-list { list-style:none; }
.step-item { display:flex; align-items:center; gap:12px; padding:10px 0; font-size:14px; color:var(--text2); border-bottom:1px solid var(--border); }
.step-item:last-child { border-bottom:none; }
.step-item.active { color:var(--text); font-weight:600; }
.step-item.done { color:var(--green); }
.step-item .dot { width:10px; height:10px; border-radius:50%; background:var(--border); flex-shrink:0; }
.step-item.active .dot { background:var(--accent); box-shadow:0 0 8px var(--accent); animation:pulse 1.5s infinite; }
.step-item.done .dot { background:var(--green); }
.step-item .detail { color:var(--text2); font-size:12px; font-weight:400; margin-left:auto; }
@keyframes pulse { 0%,100% { box-shadow:0 0 4px var(--accent); } 50% { box-shadow:0 0 12px var(--accent); } }
.results-panel { background:var(--surface); border:1px solid var(--green); border-radius:12px; padding:24px; margin-top:24px; display:none; }
.results-panel.visible { display:block; }
.results-panel h3 { color:var(--green); margin-bottom:16px; font-size:18px; }
.result-file { display:flex; align-items:center; justify-content:space-between; padding:12px 16px; background:var(--surface2); border-radius:8px; margin-bottom:8px; }
.result-file .name { font-size:14px; font-weight:600; }
.result-file .desc { font-size:12px; color:var(--text2); }
.result-file a { background:var(--accent); color:white; padding:6px 16px; border-radius:6px; text-decoration:none; font-size:13px; font-weight:600; transition:background .2s; }
.result-file a:hover { background:var(--accent2); }
.stats-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:16px; }
.stat-box { background:var(--surface2); border-radius:8px; padding:14px; text-align:center; }
.stat-box .val { font-size:22px; font-weight:700; color:var(--accent); }
.stat-box .lbl { font-size:11px; color:var(--text2); margin-top:4px; text-transform:uppercase; letter-spacing:.5px; }
.instructions { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; margin-top:32px; }
.instructions h3 { margin-bottom:16px; font-size:16px; }
.instructions ol { padding-left:20px; color:var(--text2); font-size:14px; line-height:2; }
.instructions ol li { padding-left:8px; }
.instructions ol li strong { color:var(--text); }
.footer { text-align:center; padding:32px 0; color:var(--text2); font-size:12px; border-top:1px solid var(--border); margin-top:48px; }
.sys-status { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px 24px; margin-bottom:24px; display:none; }
.sys-status.visible { display:block; }
.sys-status .item { display:inline-flex; align-items:center; gap:6px; margin-right:16px; font-size:13px; }
.sys-status .ok { color:var(--green); }
.sys-status .warn { color:var(--orange); }
.sys-status .err { color:#ef4444; }
.hidden { display:none !important; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1>Drum<span>Syncer</span> <small style="font-size:14px;color:var(--text2);font-weight:400;">v2.0</small></h1>
      <div class="subtitle" data-en="Kauzak Foundation — Artist Production Tool" data-kr="카우작 재단 — 아티스트 프로덕션 도구"></div>
    </div>
    <div class="right">
      <button class="sys-btn" onclick="checkSystem()" data-en="System Check" data-kr="시스템 확인"></button>
      <button class="lang-toggle" onclick="toggleLang()">한국어</button>
    </div>
  </div>

  <div class="sys-status" id="sys-status"></div>

  <div class="mode-selector">
    <div class="mode-card active" onclick="setMode('test')" id="mode-test">
      <h3 data-en="Test Mode" data-kr="테스트 모드"></h3>
      <p data-en="Upload or paste a YouTube link to a drum cover. DrumSyncer separates and reassembles to verify sync." data-kr="드럼 커버 영상을 업로드하거나 YouTube 링크를 붙여넣으세요. DrumSyncer가 분리하고 재조립하여 동기화를 확인합니다."></p>
    </div>
    <div class="mode-card" onclick="setMode('produce')" id="mode-produce">
      <h3 data-en="Production Mode" data-kr="프로덕션 모드"></h3>
      <p data-en="Upload original song + drum recording + video. DrumSyncer handles everything automatically." data-kr="원곡 + 드럼 녹음 + 영상을 업로드하세요. DrumSyncer가 자동으로 처리합니다."></p>
    </div>
  </div>

  <!-- TEST MODE UPLOADS -->
  <div id="uploads-test">
    <div class="upload-section">
      <h3><span class="num">1</span> <span data-en="Drum Cover Video" data-kr="드럼 커버 영상"></span></h3>
      <div class="input-method">
        <button class="active" onclick="switchInput(this,'test-file','test')" data-en="Upload File" data-kr="파일 업로드"></button>
        <button onclick="switchInput(this,'test-url','test')" data-en="YouTube URL" data-kr="YouTube 링크"></button>
      </div>
      <div id="test-file">
        <div class="drop-zone" id="drop-video-test" onclick="document.getElementById('file-video-test').click()">
          <div class="icon">🎬</div>
          <div class="label" data-en="Drop video here or click to browse" data-kr="여기에 영상을 놓거나 클릭하여 찾기"></div>
          <div class="label" style="font-size:12px;margin-top:4px;color:#666">MP4, MOV, AVI, MKV, WebM</div>
          <input type="file" id="file-video-test" accept=".mp4,.mov,.avi,.mkv,.webm" onchange="handleFile(this,'video-test')">
        </div>
      </div>
      <div id="test-url" class="hidden">
        <div class="url-input-group">
          <input type="text" class="url-input" id="url-video-test" placeholder="https://www.youtube.com/watch?v=..." data-en-placeholder="Paste YouTube URL here..." data-kr-placeholder="YouTube 링크를 붙여넣으세요...">
          <button class="url-fetch-btn" onclick="fetchUrl('url-video-test','video-test')" data-en="Fetch" data-kr="가져오기"></button>
        </div>
        <div id="url-status-test" style="font-size:13px;color:var(--text2);margin-top:4px;"></div>
      </div>
    </div>
  </div>

  <!-- PRODUCTION MODE UPLOADS -->
  <div id="uploads-produce" style="display:none">
    <div class="upload-section">
      <h3><span class="num">1</span> <span data-en="Original Song" data-kr="원곡"></span></h3>
      <div class="input-method">
        <button class="active" onclick="switchInput(this,'song-file','song')" data-en="Upload File" data-kr="파일 업로드"></button>
        <button onclick="switchInput(this,'song-url','song')" data-en="YouTube URL" data-kr="YouTube 링크"></button>
      </div>
      <div id="song-file">
        <div class="drop-zone" onclick="document.getElementById('file-song').click()">
          <div class="icon">🎵</div>
          <div class="label" data-en="Drop original song here" data-kr="여기에 원곡을 놓으세요"></div>
          <input type="file" id="file-song" accept=".mp3,.wav,.flac,.m4a,.mp4,.ogg" onchange="handleFile(this,'song')">
        </div>
      </div>
      <div id="song-url" class="hidden">
        <div class="url-input-group">
          <input type="text" class="url-input" id="url-song" placeholder="https://www.youtube.com/watch?v=...">
          <button class="url-fetch-btn" onclick="fetchUrl('url-song','song')" data-en="Fetch" data-kr="가져오기"></button>
        </div>
        <div id="url-status-song" style="font-size:13px;color:var(--text2);margin-top:4px;"></div>
      </div>
    </div>
    <div class="upload-section">
      <h3><span class="num">2</span> <span data-en="Drum Recording" data-kr="드럼 녹음"></span></h3>
      <div class="drop-zone" onclick="document.getElementById('file-drums').click()">
        <div class="icon">🥁</div>
        <div class="label" data-en="Drop your drum recording here" data-kr="여기에 드럼 녹음을 놓으세요"></div>
        <input type="file" id="file-drums" accept=".wav,.mp3,.flac,.m4a,.mp4,.mov" onchange="handleFile(this,'drums')">
      </div>
    </div>
    <div class="upload-section">
      <h3><span class="num">3</span> <span data-en="Performance Video" data-kr="연주 영상"></span></h3>
      <div class="drop-zone" onclick="document.getElementById('file-video-prod').click()">
        <div class="icon">📹</div>
        <div class="label" data-en="Drop your performance video here" data-kr="여기에 연주 영상을 놓으세요"></div>
        <input type="file" id="file-video-prod" accept=".mp4,.mov,.avi,.mkv,.webm" onchange="handleFile(this,'video-prod')">
      </div>
    </div>
  </div>

  <button class="go-btn" id="go-btn" disabled onclick="startJob()">
    <span data-en="START PROCESSING" data-kr="처리 시작"></span>
  </button>

  <div class="progress-panel" id="progress-panel">
    <div class="progress-bar-container"><div class="progress-bar" id="progress-bar"></div></div>
    <ul class="step-list" id="step-list"></ul>
  </div>

  <div class="results-panel" id="results-panel">
    <h3 data-en="Processing Complete" data-kr="처리 완료"></h3>
    <div id="results-files"></div>
    <div class="stats-grid" id="stats-grid"></div>
  </div>

  <div class="instructions">
    <h3 data-en="How It Works" data-kr="사용 방법"></h3>
    <ol>
      <li data-en="<strong>Upload or paste URL</strong> — drag a file or paste a YouTube link" data-kr="<strong>업로드 또는 URL 붙여넣기</strong> — 파일을 드래그하거나 YouTube 링크를 붙여넣으세요"></li>
      <li data-en="<strong>AI Separation</strong> — Demucs neural network isolates drums from music" data-kr="<strong>AI 분리</strong> — Demucs 신경망이 음악에서 드럼을 분리합니다"></li>
      <li data-en="<strong>Beat Detection</strong> — analyzes tempo and beat positions in both tracks" data-kr="<strong>비트 감지</strong> — 두 트랙의 템포와 비트 위치를 분석합니다"></li>
      <li data-en="<strong>Auto Sync</strong> — cross-correlation aligns tracks to the exact beat" data-kr="<strong>자동 동기화</strong> — 상호 상관 분석으로 정확한 비트에 맞춥니다"></li>
      <li data-en="<strong>Mix & Export</strong> — combines everything and exports your finished video" data-kr="<strong>믹스 & 내보내기</strong> — 모든 것을 결합하여 완성된 비디오를 내보냅니다"></li>
    </ol>
  </div>

  <div class="footer">DrumSyncer v2.0 — Kauzak Foundation<br>
    <span data-en="Open source. Built with Demucs, librosa, FFmpeg." data-kr="오픈 소스. Demucs, librosa, FFmpeg으로 제작."></span>
  </div>
</div>

<script>
let lang='en', mode='test', uploadedFiles={}, currentJobId=null, pollTimer=null;

const STEPS_TEST=[
  {en:'Extract audio from video',kr:'비디오에서 오디오 추출'},
  {en:'AI stem separation (Demucs)',kr:'AI 스템 분리 (Demucs)'},
  {en:'Beat detection & tempo analysis',kr:'비트 감지 및 템포 분석'},
  {en:'Compute sync alignment',kr:'동기화 정렬 계산'},
  {en:'Mix audio tracks',kr:'오디오 트랙 믹싱'},
  {en:'Sync audio to video',kr:'오디오를 비디오에 동기화'},
  {en:'Complete',kr:'완료'}
];
const STEPS_PROD=[
  {en:'Strip drums from original song',kr:'원곡에서 드럼 제거'},
  {en:'Prepare drum recording',kr:'드럼 녹음 준비'},
  {en:'Beat detection & tempo analysis',kr:'비트 감지 및 템포 분석'},
  {en:'Tempo alignment & sync',kr:'템포 정렬 및 동기화'},
  {en:'Mix audio tracks',kr:'오디오 트랙 믹싱'},
  {en:'Create final video',kr:'최종 비디오 생성'},
  {en:'Complete',kr:'완료'}
];

function toggleLang(){
  lang=lang==='en'?'kr':'en';
  document.querySelector('.lang-toggle').textContent=lang==='en'?'한국어':'English';
  document.querySelectorAll('[data-en]').forEach(el=>{
    const t=el.getAttribute('data-'+lang);
    if(t) el.innerHTML=t;
  });
  document.querySelectorAll('[data-'+lang+'-placeholder]').forEach(el=>{
    el.placeholder=el.getAttribute('data-'+lang+'-placeholder');
  });
}

function setMode(m){
  mode=m;
  document.getElementById('mode-test').classList.toggle('active',m==='test');
  document.getElementById('mode-produce').classList.toggle('active',m==='produce');
  document.getElementById('uploads-test').style.display=m==='test'?'block':'none';
  document.getElementById('uploads-produce').style.display=m==='produce'?'block':'none';
  uploadedFiles={};
  checkReady();
}

function switchInput(btn, showId, group){
  btn.parentElement.querySelectorAll('button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const parent=btn.closest('.upload-section');
  parent.querySelectorAll('.url-input-group, .drop-zone').forEach(el=>{
    el.closest('[id]').classList.add('hidden');
  });
  // Show the right one
  const ids=parent.querySelectorAll('[id]');
  ids.forEach(el=>{
    if(el.id===showId) el.classList.remove('hidden');
    else if(el.id.includes('file')||el.id.includes('url')) el.classList.add('hidden');
  });
  document.getElementById(showId).classList.remove('hidden');
}

function handleFile(input,key){
  const file=input.files[0];
  if(!file) return;
  const dropZone=input.closest('.drop-zone');
  const formData=new FormData();
  formData.append('file',file);
  dropZone.classList.add('has-file');
  const origHTML=dropZone.innerHTML;
  dropZone.innerHTML='<div class="icon" style="animation:pulse 1s infinite">&#9203;</div><div class="label">'+(lang==='kr'?'업로드 중...':'Uploading...')+'</div><input type="file" id="'+input.id+'" accept="'+input.accept+'" onchange="handleFile(this,\''+key+'\')" style="display:none">';

  fetch('/api/upload',{method:'POST',body:formData})
    .then(r=>r.json())
    .then(data=>{
      uploadedFiles[key]=data;
      const sizeMB=(data.size/1024/1024).toFixed(1);
      dropZone.innerHTML='<div style="font-size:28px">&#9989;</div><div class="filename">'+data.filename+'</div><div class="filesize">'+sizeMB+' MB</div><input type="file" id="'+input.id+'" accept="'+input.accept+'" onchange="handleFile(this,\''+key+'\')" style="display:none">';
      checkReady();
    })
    .catch(err=>{
      dropZone.innerHTML='<div style="font-size:28px">&#10060;</div><div class="label" style="color:#ef4444">'+err.message+'</div><input type="file" id="'+input.id+'" accept="'+input.accept+'" onchange="handleFile(this,\''+key+'\')" style="display:none">';
    });
}

function fetchUrl(inputId, key){
  const input=document.getElementById(inputId);
  const url=input.value.trim();
  if(!url) return;

  const statusId='url-status-'+inputId.split('-').pop();
  const statusEl=document.getElementById(statusId)||input.parentElement.nextElementSibling;
  const fetchBtn=input.nextElementSibling;

  fetchBtn.disabled=true;
  fetchBtn.textContent=lang==='kr'?'다운로드 중...':'Downloading...';
  if(statusEl) statusEl.innerHTML='<span style="color:var(--orange)">'+(lang==='kr'?'YouTube에서 다운로드 중... 잠시 기다려주세요':'Downloading from YouTube... please wait')+'</span>';

  fetch('/api/fetch-url',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({url})
  })
  .then(r=>r.json())
  .then(data=>{
    fetchBtn.disabled=false;
    fetchBtn.textContent=lang==='kr'?'가져오기':'Fetch';
    if(data.error){
      if(statusEl) statusEl.innerHTML='<span style="color:#ef4444">'+data.error+'</span>';
      return;
    }
    uploadedFiles[key]=data;
    const sizeMB=(data.size/1024/1024).toFixed(1);
    if(statusEl) statusEl.innerHTML='<span style="color:var(--green)">&#9989; '+data.filename+' ('+sizeMB+' MB)</span>';
    checkReady();
  })
  .catch(err=>{
    fetchBtn.disabled=false;
    fetchBtn.textContent=lang==='kr'?'가져오기':'Fetch';
    if(statusEl) statusEl.innerHTML='<span style="color:#ef4444">'+err.message+'</span>';
  });
}

function checkReady(){
  const btn=document.getElementById('go-btn');
  if(mode==='test') btn.disabled=!uploadedFiles['video-test'];
  else btn.disabled=!(uploadedFiles['song']&&uploadedFiles['drums']&&uploadedFiles['video-prod']);
}

function checkSystem(){
  const el=document.getElementById('sys-status');
  el.classList.add('visible');
  el.innerHTML='<span style="color:var(--text2)">'+(lang==='kr'?'확인 중...':'Checking...')+'</span>';
  fetch('/api/system-info').then(r=>r.json()).then(d=>{
    let html='';
    html+='<span class="item '+(d.python?'ok':'err')+'">Python '+d.python+'</span>';
    html+='<span class="item '+(d.ffmpeg?'ok':'err')+'">'+(d.ffmpeg?'&#9989;':'&#10060;')+' FFmpeg</span>';
    html+='<span class="item '+(d.ytdlp?'ok':'warn')+'">'+(d.ytdlp?'&#9989;':'&#9888;')+' yt-dlp</span>';
    html+='<span class="item '+(d.gpu?'ok':'warn')+'">'+(d.gpu?'&#9989; GPU':'&#9888; CPU only')+'</span>';
    el.innerHTML=html;
  });
}

function startJob(){
  const btn=document.getElementById('go-btn');
  btn.disabled=true;
  const body={mode};
  if(mode==='test') body.video_path=uploadedFiles['video-test'].path;
  else{
    body.song_path=uploadedFiles['song'].path;
    body.drums_path=uploadedFiles['drums'].path;
    body.video_path=uploadedFiles['video-prod'].path;
  }
  const panel=document.getElementById('progress-panel');
  panel.classList.add('visible');
  document.getElementById('results-panel').classList.remove('visible');
  const steps=mode==='test'?STEPS_TEST:STEPS_PROD;
  document.getElementById('step-list').innerHTML=steps.map((s,i)=>
    '<li class="step-item" id="step-'+(i+1)+'"><span class="dot"></span><span>'+s[lang]+'</span><span class="detail" id="step-detail-'+(i+1)+'"></span></li>'
  ).join('');

  fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  .then(r=>r.json()).then(data=>{currentJobId=data.job_id;pollTimer=setInterval(pollStatus,1000);});
}

function pollStatus(){
  if(!currentJobId) return;
  fetch('/api/status/'+currentJobId).then(r=>r.json()).then(data=>{
    const steps=mode==='test'?STEPS_TEST:STEPS_PROD;
    const pct=Math.min(100,(data.step/steps.length)*100);
    const bar=document.getElementById('progress-bar');
    bar.style.width=pct+'%';
    for(let i=1;i<=steps.length;i++){
      const el=document.getElementById('step-'+i);
      if(!el) continue;
      el.classList.remove('active','done');
      if(i<data.step) el.classList.add('done');
      else if(i===data.step) el.classList.add('active');
    }
    if(data.demucs_time){const d=document.getElementById('step-detail-2')||document.getElementById('step-detail-1');if(d)d.textContent=data.demucs_time;}
    if(data.drums_tempo){const d=document.getElementById('step-detail-3');if(d)d.textContent=data.drums_tempo+' BPM';}
    if(data.sync_confidence){const d=document.getElementById('step-detail-4');if(d)d.textContent=data.sync_offset+' ('+(parseFloat(data.sync_confidence)*100).toFixed(0)+'%)';}
    if(data.status==='complete'){
      clearInterval(pollTimer);bar.classList.add('complete');bar.style.width='100%';
      for(let i=1;i<=steps.length;i++){const el=document.getElementById('step-'+i);if(el){el.classList.remove('active');el.classList.add('done');}}
      showResults(data);
    }else if(data.status==='error'){
      clearInterval(pollTimer);bar.style.background='#ef4444';
      alert((lang==='kr'?'오류: ':'Error: ')+data.message);
      document.getElementById('go-btn').disabled=false;
    }
  });
}

function showResults(data){
  const panel=document.getElementById('results-panel');
  panel.classList.add('visible');
  let html='';
  if(data.output_video) html+='<div class="result-file"><div><div class="name">'+(lang==='kr'?'Final Video / 최종 비디오':'Final Video')+'</div><div class="desc">'+data.output_size+'</div></div><a href="/api/download/'+data.output_video+'">'+(lang==='kr'?'다운로드':'Download')+'</a></div>';
  if(data.output_drums) html+='<div class="result-file"><div><div class="name">'+(lang==='kr'?'Drums Only / 드럼만':'Drums Only')+'</div><div class="desc">'+(lang==='kr'?'AI로 분리된 드럼 트랙':'AI-isolated drum track')+'</div></div><a href="/api/download/'+data.output_drums+'">'+(lang==='kr'?'다운로드':'Download')+'</a></div>';
  if(data.output_backing) html+='<div class="result-file"><div><div class="name">'+(lang==='kr'?'Backing Only / 반주만':'Backing Only')+'</div><div class="desc">'+(lang==='kr'?'드럼이 제거된 음악':'Music with drums removed')+'</div></div><a href="/api/download/'+data.output_backing+'">'+(lang==='kr'?'다운로드':'Download')+'</a></div>';
  document.getElementById('results-files').innerHTML=html;

  let stats='';
  if(data.drums_tempo) stats+='<div class="stat-box"><div class="val">'+data.drums_tempo+'</div><div class="lbl">BPM</div></div>';
  if(data.drums_beats) stats+='<div class="stat-box"><div class="val">'+data.drums_beats+'</div><div class="lbl">'+(lang==='kr'?'비트':'Beats')+'</div></div>';
  if(data.demucs_time) stats+='<div class="stat-box"><div class="val">'+data.demucs_time+'</div><div class="lbl">'+(lang==='kr'?'분리 시간':'Separation')+'</div></div>';
  if(data.total_time) stats+='<div class="stat-box"><div class="val">'+data.total_time+'</div><div class="lbl">'+(lang==='kr'?'총 시간':'Total')+'</div></div>';
  document.getElementById('stats-grid').innerHTML=stats;
  document.getElementById('go-btn').disabled=false;
}

// Drag & drop
document.querySelectorAll('.drop-zone').forEach(z=>{
  z.addEventListener('dragover',e=>{e.preventDefault();z.classList.add('dragover');});
  z.addEventListener('dragleave',()=>z.classList.remove('dragover'));
  z.addEventListener('drop',e=>{
    e.preventDefault();z.classList.remove('dragover');
    const input=z.querySelector('input[type="file"]');
    if(input&&e.dataTransfer.files.length){input.files=e.dataTransfer.files;input.dispatchEvent(new Event('change'));}
  });
});

// URL paste detection
document.addEventListener('paste',e=>{
  const text=(e.clipboardData||window.clipboardData).getData('text');
  if(text&&(text.includes('youtube.com/watch')||text.includes('youtu.be/'))){
    const urlInputs=document.querySelectorAll('.url-input:not(.hidden)');
    // Find visible URL input
    const visible=Array.from(document.querySelectorAll('.url-input')).find(el=>!el.closest('.hidden'));
    if(visible&&!visible.value){
      visible.value=text;
      visible.focus();
      e.preventDefault();
    }
  }
});

toggleLang();toggleLang();
</script>
</body>
</html>
'''


# ── Main ───────────────────────────────────────────────────
if __name__ == '__main__':
    port = 5151
    print(f"""
    ╔══════════════════════════════════════════════════╗
    ║  DrumSyncer v2.0 — Kauzak Foundation             ║
    ║  드럼싱커 v2.0 — 카우작 재단                       ║
    ║                                                    ║
    ║  Open in browser / 브라우저에서 열기:                ║
    ║  http://localhost:{port}                             ║
    ║                                                    ║
    ║  Press Ctrl+C to stop / 중지하려면 Ctrl+C           ║
    ╚══════════════════════════════════════════════════╝
""")

    threading.Timer(1.5, lambda: webbrowser.open(f'http://localhost:{port}')).start()
    app.run(host='0.0.0.0', port=port, debug=False)
