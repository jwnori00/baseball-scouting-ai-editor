"""Collect actual installed distribution license texts without guessing versions."""
from importlib.metadata import distribution
from pathlib import Path
import hashlib
import json
import shutil
import sys
import os

root=Path(sys.argv[1])
notices=root/'licenses'/'python-packages'
notices.mkdir(parents=True,exist_ok=True)
manifest=[]
for name in ('numpy','opencv-python-headless','PySide6','PySide6-Essentials','PySide6-Addons','shiboken6','pyinstaller'):
    d=distribution(name);count=0
    for file in d.files or []:
        if any(part.lower().startswith(('license','copying','notice')) for part in file.parts) and d.locate_file(file).is_file():
            source=Path(d.locate_file(file));dest=notices/name/str(file)
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest);count+=1
    source_kind='installed distribution'
    if count==0 and name in ('PySide6','PySide6-Essentials','PySide6-Addons','shiboken6'):
        if d.version!='6.8.3':raise RuntimeError('Qt source version does not match wheel')
        source=Path(os.environ['BSAE_BUILD_ASSETS'])/'licenses'/'qt-pyside'
        files=list(source.glob('*'))
        if not files:raise RuntimeError('Qt/PySide corresponding-source licenses missing')
        shared=notices/'Qt-PySide-6.8.3-source'
        if not shared.exists():shutil.copytree(source,shared)
        count=len(files);source_kind='Qt/PySide 6.8.3 corresponding source (shared notices directory)'
    if count==0:raise RuntimeError('License texts missing: '+name)
    manifest.append(dict(name=name,version=d.version,license_files=count,license_source=source_kind))
# Python's actual runtime license is required too.
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if not python_license.is_file():raise FileNotFoundError(python_license)
shutil.copy2(python_license,notices/'Python-LICENSE.txt')
(notices/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
