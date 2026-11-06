"""Fetch official OCR data and Qt/PySide source; checksum every retained asset."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'vendor'/'portable'


def fetch(url,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        temporary=path.with_suffix(path.suffix+'.part')
        try:
            with urllib.request.urlopen(url,timeout=180) as source,temporary.open('wb') as out:
                while chunk:=source.read(1024*1024):out.write(chunk)
            temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    return dict(url=url,path=str(path.relative_to(ASSETS)),sha256=digest)


def prepare():
    sources=ASSETS/'corresponding-source';sources.mkdir(parents=True,exist_ok=True)
    receipts=[]
    # Pin to the full official Git revision resolved by Git, not an opaque binary mirror.
    revision=subprocess.check_output(['git','ls-remote','https://github.com/tesseract-ocr/tessdata_fast.git','HEAD'],text=True).split()[0]
    for filename,target in [('eng.traineddata',ASSETS/'tools'/'tessdata'/'eng.traineddata'),('LICENSE',ASSETS/'licenses'/'tessdata-LICENSE')]:
        receipts.append(fetch(f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{revision}/{filename}',target))
    qt='https://download.qt.io/archive/qt/6.8/6.8.3/single/qt-everywhere-src-6.8.3.tar.xz'
    record=fetch(qt,sources/'qt-everywhere-src-6.8.3.tar.xz')
    with urllib.request.urlopen(qt+'.sha256',timeout=60) as r:expected=r.read().decode().split()[0].lower()
    if record['sha256']!=expected:raise ValueError('Official Qt source checksum mismatch')
    receipts.append(record)
    receipts.append(fetch('https://github.com/pyside/pyside-setup/archive/3ae6c97953d563c33ff630f259716b01b81aa531.tar.gz',sources/'pyside-setup-6.8.3.tar.gz'))
    # Qt Multimedia can include its own FFmpeg DLL; preserve that exact upstream source.
    import ctypes,os,re,PySide6
    handles=[]
    for dll in Path(PySide6.__file__).parent.rglob('avutil-*.dll'):
        handles.append(os.add_dll_directory(str(dll.parent)))
        library=ctypes.CDLL(str(dll));library.av_version_info.restype=ctypes.c_char_p
        version=library.av_version_info().decode()
        if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?',version):raise ValueError('Unknown Qt FFmpeg version: '+version)
        receipts.append(fetch(f'https://github.com/FFmpeg/FFmpeg/archive/refs/tags/n{version}.tar.gz',sources/f'qt-ffmpeg-{version}.tar.gz'))
    (sources/'upstream-receipts.json').write_text(json.dumps(receipts,indent=2),encoding='utf-8')
    entries=[]
    for folder in ('tools','licenses','corresponding-source','models'):
        for path in sorted((ASSETS/folder).rglob('*')):
            if path.is_file():
                with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
                entries.append(dict(path=path.relative_to(ASSETS).as_posix(),sha256=digest))
    (ASSETS/'assets.json').write_text(json.dumps(dict(files=entries),indent=2),encoding='utf-8')


if __name__=='__main__':prepare()
