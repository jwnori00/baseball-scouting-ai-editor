"""Add pinned Apache-2.0 language data without rebuilding native FFmpeg."""
from pathlib import Path
import hashlib
import json
import urllib.request
import sys

COMMIT='87416418657359cb625c412a48b6e1d6d41c29bd'
BASE=f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{COMMIT}/'
FILES={'kor.traineddata':'6b85e11d9bbf07863b97b3523b1b112844c43e713df8b66418a081fd1060b3b2','jpn.traineddata':'1f5de9236d2e85f5fdf4b3c500f2d4926f8d9449f28f5394472d9e8d83b91b4d','LICENSE':'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'}


def prepare(root):
    root=Path(root)
    manifest=json.loads((root/'assets.json').read_text(encoding='utf-8'))
    registered={e['path']:e for e in manifest['files']}
    for name,digest in FILES.items():
        relative='licenses/TESSDATA_FAST_MULTILINGUAL.txt' if name=='LICENSE' else 'tools/tessdata/'+name
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        data=path.read_bytes() if path.exists() else urllib.request.urlopen(BASE+name,timeout=60).read()
        if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('OCR language checksum failure: '+name)
        path.write_bytes(data);registered[relative]=dict(path=relative,sha256=digest)
    receipt=json.dumps(dict(source=BASE,commit=COMMIT,license='Apache-2.0',sha256=FILES),indent=2).encode()
    relative='licenses/TESSDATA_FAST_MULTILINGUAL_SOURCE.json';(root/relative).write_bytes(receipt)
    registered[relative]=dict(path=relative,sha256=hashlib.sha256(receipt).hexdigest())
    (root/'assets.json').write_text(json.dumps(dict(files=list(registered.values())),indent=2),encoding='utf-8')


if __name__=='__main__':prepare(sys.argv[1])
