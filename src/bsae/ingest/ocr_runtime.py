"""Keep MinGW Tesseract's narrow filesystem API away from Unicode paths.

Media paths remain Unicode and untouched. Only public OCR language data is
materialized under a verified ASCII temporary path; image input stays on stdin.
"""
from pathlib import Path
import hashlib
import shutil
import tempfile
import threading
import os

_lock=threading.Lock()
_workspace=None
_verified={}
_tools_verified={}


def _short_path(path):
    import ctypes
    from ctypes import wintypes
    function=ctypes.windll.kernel32.GetShortPathNameW
    function.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD]
    function.restype=wintypes.DWORD
    size=function(str(path),None,0)
    if not size:return None
    result=ctypes.create_unicode_buffer(size)
    if not function(str(path),result,size):return None
    return Path(result.value)


def ascii_workspace():
    global _workspace
    with _lock:
        if _workspace and _workspace.is_dir():return _workspace
        base=Path(tempfile.gettempdir()).resolve()
        if not str(base).isascii():base=_short_path(base)
        if base is None or not str(base).isascii():
            raise RuntimeError('OCR 임시 경로의 문자 변환에 실패했습니다. Windows 임시 폴더의 영문 짧은 경로를 사용할 수 없습니다.')
        _workspace=Path(tempfile.mkdtemp(prefix='bsae-ocr-',dir=base))
        return _workspace


def prepare(executable,arguments):
    """Windows-only argv/env/cwd overrides; no source images are written."""
    workspace=ascii_workspace();data=workspace/'tessdata';data.mkdir(exist_ok=True)
    original=Path(executable).parent/'tessdata'
    if not original.is_dir():
        # Source development may use a system Tesseract installation.
        configured=os.environ.get('TESSDATA_PREFIX')
        original=Path(configured) if configured else original
    if not original.is_dir():return str(executable),list(arguments),dict(os.environ),str(workspace)
    languages='+'.join(sorted(p.stem for p in original.glob('*.traineddata'))) if '--list-langs' in arguments else 'eng'
    if '-l' in arguments:languages=arguments[arguments.index('-l')+1]
    names=set(languages.split('+'))
    if any(not n or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in n) for n in names):
        raise ValueError('지원하지 않는 OCR 언어 파일 이름')
    for name in names:
        source=original/(name+'.traineddata');target=data/source.name
        stat=source.stat();key=(str(source),stat.st_size,stat.st_mtime_ns)
        with _lock:
            if _verified.get(name)!=key or not target.is_file():
                with source.open('rb') as f:expected=hashlib.file_digest(f,'sha256').hexdigest()
                temporary=data/(name+'.tmp')
                try:
                    shutil.copyfile(source,temporary)
                    with temporary.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
                    if actual!=expected:raise RuntimeError('OCR 언어 자료 복사 무결성 검사 실패')
                    temporary.replace(target);_verified[name]=key
                finally:temporary.unlink(missing_ok=True)
    args=list(arguments)
    if '--tessdata-dir' in args:
        i=args.index('--tessdata-dir');args[i+1]=str(data)
    else:args=['--tessdata-dir',str(data),*args]
    selected=str(executable)
    if not selected.isascii():
        runtime=workspace/'tools';runtime.mkdir(exist_ok=True)
        for source in [Path(executable),*Path(executable).parent.glob('*.dll')]:
            stat=source.stat();key=(str(source),stat.st_size,stat.st_mtime_ns);target=runtime/source.name
            with _lock:
                if _tools_verified.get(source.name)!=key or not target.is_file():
                    with source.open('rb') as f:expected=hashlib.file_digest(f,'sha256').hexdigest()
                    shutil.copyfile(source,target)
                    with target.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
                    if expected!=actual:raise RuntimeError('OCR 실행 파일 복사 무결성 검사 실패')
                    _tools_verified[source.name]=key
        selected=str(runtime/Path(executable).name)
    return selected,args,dict(os.environ,TESSDATA_PREFIX=str(data)),str(workspace)


def _cleanup():
    if _workspace and _workspace.is_dir():shutil.rmtree(_workspace,ignore_errors=True)


import atexit
atexit.register(_cleanup)
