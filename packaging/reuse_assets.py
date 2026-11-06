"""Reuse our exact successful Windows artifact; never accept an opaque binary."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASELINE_RUN=42183581537
BASELINE_COMMIT='78ed471b37bc37c531cd006c46e02326600cb026'
INPUTS={
 'packaging/build_media.sh':'1b623fa5ee2ef5c71bf45501fbf85e0b5545f67286f49cc816ba0d3cae3b198d',
 'packaging/prepare_assets.py':'0d295c52e8d377fa588af9bf5df49d72c1dacc79b6e5a8eb631786cb7d8265d6',
 'requirements-dev.txt':'b671c6a45997e7427bd5647dc94668bbdbd77dbffd4755283501e601d030417e'}


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def eligible():return all(hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==expected for p,expected in INPUTS.items())


def reuse(application,sources):
    if os.environ.get('GITHUB_ACTIONS')!='true':raise RuntimeError('CI artifact reuse only')
    if not eligible():raise ValueError('Media sources or pinned dependency versions changed; rebuild required')
    application=Path(application);sources=Path(sources)
    name='BaseballScoutingAIEditor-Windows-x64-development.zip'
    archive=application/name
    expected=(application/(name+'.sha256')).read_text(encoding='utf-8-sig').split()[0].lower()
    if len(expected)!=64 or digest(archive)!=expected:raise ValueError('Baseline ZIP checksum mismatch')
    destination=ROOT/'vendor'/'portable';destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        temp=Path(temp);unpacked=temp/'unpacked'
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if (unpacked/member.filename).resolve().is_relative_to(unpacked.resolve()) is False:raise ValueError('Unsafe archive path')
            z.extractall(unpacked)
        internal=unpacked/'BaseballScoutingAIEditor'/'_internal'
        stage=temp/'assets';stage.mkdir()
        shutil.copytree(internal/'tools',stage/'tools')
        shutil.copytree(internal/'licenses',stage/'licenses')
        shutil.copytree(sources,stage/'corresponding-source')
        receipts=json.loads((stage/'corresponding-source'/'upstream-receipts.json').read_text(encoding='utf-8'))
        for receipt in receipts:
            p=(stage/receipt['path']).resolve(strict=True)
            if not p.is_relative_to(stage.resolve()) or digest(p)!=receipt['sha256']:raise ValueError('Corresponding-source checksum mismatch')
        (stage/'corresponding-source'/'baseline-reuse.json').write_text(json.dumps(dict(run=BASELINE_RUN,commit=BASELINE_COMMIT,application_sha256=expected,source_inputs=INPUTS),indent=2),encoding='utf-8')
        entries=[dict(path=p.relative_to(stage).as_posix(),sha256=digest(p)) for p in stage.rglob('*') if p.is_file()]
        (stage/'assets.json').write_text(json.dumps(dict(files=entries),indent=2),encoding='utf-8')
        if destination.exists():shutil.rmtree(destination) # CI-generated cache only; no checkout/source changes.
        stage.rename(destination)
    print('Verified native tools, OCR, licenses and exact corresponding sources reused from successful run',BASELINE_RUN)


if __name__=='__main__':
    if sys.argv[1]=='--eligible':
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:output.write('eligible='+str(eligible()).lower()+'\n')
    else:reuse(sys.argv[1],sys.argv[2])
