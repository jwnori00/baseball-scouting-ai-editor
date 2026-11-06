"""Read-only FFmpeg streaming with presentation timestamps (VFR supported)."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import numpy as np
from bsae.core.models import VideoSource


def tool(name):
    if name not in ('ffmpeg', 'ffprobe', 'tesseract'):
        raise ValueError(name)
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[3]))
    bundled = base / 'tools' / (name + ('.exe' if sys.platform == 'win32' else ''))
    if bundled.is_file():
        return str(bundled)
    if getattr(sys, 'frozen', False):
        raise FileNotFoundError(f'배포본에 {name}가 없습니다')
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(f'{name} 설치가 필요합니다')
    return found


def media_error(name,stderr):
    message=stderr.decode('utf-8',errors='replace') if isinstance(stderr,bytes) else str(stderr)
    missing=re.search(r'no decoder found for:\s*([a-z0-9_]+)',message,re.I)
    if missing:
        codec=missing.group(1).upper()
        return RuntimeError(f'{codec} 영상 코덱을 현재 동봉된 도구로 읽을 수 없습니다. 해당 코덱을 지원하는 프로그램 업데이트가 필요합니다. 파일 확장자만 바꿔서는 해결되지 않습니다.')
    return RuntimeError(name+': '+message[-4000:])


def run(name, args, **kwargs):
    if sys.platform == 'win32':
        kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
    executable = tool(name)
    if name=='tesseract' and sys.platform=='win32':
        from .ocr_runtime import prepare
        executable,args,environment,working_directory=prepare(executable,list(map(str,args)))
        kwargs['env']=environment;kwargs['cwd']=working_directory
    elif name == 'tesseract' and (Path(executable).parent/'tessdata').is_dir():
        import os
        kwargs['env'] = dict(os.environ, TESSDATA_PREFIX=str(Path(executable).parent/'tessdata'))
    result = subprocess.run([executable, *map(str, args)], capture_output=True, **kwargs)
    if result.returncode:
        raise media_error(name,result.stderr)
    return result.stdout


def fingerprint(path):
    # Full hash: detects middle-of-file edits; never writes source media.
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def probe(path):
    return json.loads(run('ffprobe', ['-v', 'error', '-show_format', '-show_streams', '-of', 'json', path]))


def presentation_span(path, metadata):
    video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
    origin = float(video.get('start_time', 0))
    if video.get('duration') not in (None, 'N/A'):
        return origin, float(video['duration'])
    # Matroska may report end PTS as format.duration when start PTS is nonzero.
    # Read packet timestamps in a bounded stream instead of assuming that value
    # is the playable video duration. Packet order may differ from PTS order.
    args = [tool('ffprobe'), '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'packet=pts_time,duration_time', '-of', 'csv=p=0', str(path)]
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    earliest, latest = float('inf'), float('-inf')
    from fractions import Fraction
    rate = video.get('avg_frame_rate', '0/1')
    fallback = 1/float(Fraction(rate)) if rate not in ('0/0','0/1') else 0
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, **flags)
        try:
            for line in process.stdout:
                fields = line.decode('ascii', errors='replace').strip().split(',')
                try:
                    pts = float(fields[0])
                    duration = float(fields[1]) if len(fields)>1 and fields[1] != 'N/A' else fallback
                except ValueError:
                    continue
                earliest, latest = min(earliest,pts), max(latest,pts+duration)
            if process.wait() != 0:
                raise RuntimeError('영상 패킷 시간 검사 실패')
        finally:
            process.stdout.close()
            if process.poll() is None:process.terminate()
            process.wait()
    if not latest > earliest:
        raise ValueError('영상 PTS 범위를 확인할 수 없습니다')
    return earliest, latest-earliest


def add_sources(paths):
    sources, offset, seen = [], 0.0, set()
    for path in paths:
        path = Path(path).resolve(strict=True)
        if path in seen:
            raise ValueError('동일 파일 중복 입력')
        seen.add(path)
        data = probe(path)
        video = next(s for s in data['streams'] if s['codec_type'] == 'video')
        origin, duration = presentation_span(path, data)
        sources.append(VideoSource(str(path), duration, fingerprint(path), offset, origin))
        offset += duration
    return sources


def frames(path, fps=4, width=160, height=90, start=0, end=None):
    """Bounded RGB stream; showinfo follows fps filter, yielding sampled PTS.

    stderr is spooled to disk to avoid pipe deadlock or RAM accumulation. No
    frame-number/FPS conversion is used for original variable-rate media.
    """
    args = [tool('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'info', '-ss', str(start), '-i', str(path)]
    if end is not None:
        args += ['-t', str(end-start)]
    args += ['-an', '-vf', f'fps={fps},scale={width}:{height},showinfo', '-threads', '1',
             '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    import queue
    import threading
    from collections import deque
    timestamps = queue.Queue()
    errors = deque(maxlen=30)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **flags)

    def read_log():
        for line in iter(process.stderr.readline, b''):
            match = re.search(rb'pts_time:([\d.eE+\-]+)', line)
            if match:
                timestamps.put(start + float(match.group(1)))
            else:
                errors.append(line)
        timestamps.put(None)

    reader = threading.Thread(target=read_log, daemon=True)
    reader.start()
    try:
        while True:
            required = width*height*3
            block = bytearray()
            while len(block) < required:
                chunk = process.stdout.read(required-len(block))
                if not chunk:
                    break
                block.extend(chunk)
            if not block:
                break
            if len(block) != required:
                raise RuntimeError('잘린 디코딩 프레임')
            timestamp = timestamps.get(timeout=30)
            if timestamp is None:
                raise RuntimeError('FFmpeg PTS를 읽을 수 없습니다')
            yield timestamp, np.frombuffer(block, dtype=np.uint8).reshape(height, width, 3)
        if process.wait() != 0:
            raise media_error('ffmpeg',b''.join(errors))
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
        process.wait()
        reader.join(timeout=5)
        process.stderr.close()
