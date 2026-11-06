"""Collect actual installed distribution license texts without guessing versions."""
from importlib.metadata import distribution
from pathlib import Path
import hashlib
import json
import shutil
import sys

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
    if count==0:raise RuntimeError('License texts missing: '+name)
    manifest.append(dict(name=name,version=d.version,license_files=count))
# Python's actual runtime license is required too.
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if not python_license.is_file():raise FileNotFoundError(python_license)
shutil.copy2(python_license,notices/'Python-LICENSE.txt')
(notices/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
