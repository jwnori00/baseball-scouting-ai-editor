"""Require a reviewed, checksum-verified asset supply; never fetch opaque models."""
from pathlib import Path
import hashlib
import json
import sys
from bsae.vision.model import TemporalModel


def validate(root):
    root=Path(root).resolve(strict=True)
    manifest=json.loads((root/'assets.json').read_text(encoding='utf-8'))
    entries=manifest['files']
    if not entries:raise ValueError('자산 체크섬 목록이 없습니다')
    verified=set()
    for e in entries:
        p=(root/e['path']).resolve(strict=True)
        if root not in p.parents:raise ValueError('외부 자산 경로')
        with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=e['sha256']:raise ValueError('자산 체크섬 불일치: '+e['path'])
        verified.add(p.relative_to(root).as_posix())
    for folder in ('tools','models','licenses','corresponding-source'):
        files=[p for p in (root/folder).rglob('*') if p.is_file()]
        if not files:raise ValueError('필수 자산 폴더 없음: '+folder)
        if any(p.relative_to(root).as_posix() not in verified for p in files):raise ValueError('체크섬 미등록 자산: '+folder)
    for name in ('ffmpeg.exe','ffprobe.exe','tesseract.exe','tessdata/eng.traineddata'):
        if not (root/'tools'/name).is_file():raise ValueError('필수 도구 없음: '+name)
    TemporalModel(root/'models'/'model.json')
    return manifest


if __name__=='__main__':
    validate(sys.argv[1]);print('Asset checksums and model format verified. Accuracy NOT_EVALUATED.')
