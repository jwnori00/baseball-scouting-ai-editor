"""Build provenance is generated once and reused by GUI, ZIP and evidence."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,subprocess
from bsae.version import APP_VERSION,BUILD_LABEL
from bsae.vision.rules import VERSION


ROOT=Path(__file__).resolve().parents[1]


def create(assets,kind,evidence_dir='build-evidence'):
    commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip()
    sources={name:hashlib.sha256((ROOT/'src'/'bsae'/'vision'/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in ('rules.py','batter_text.py','scoreboard.py','workflow.py','scene.py','game_index.py')}
    value=dict(analysis_sources=sources,version=APP_VERSION,label=BUILD_LABEL,kind=kind,automatic_analysis=kind!='development',engine=VERSION,commit=commit,built_at=datetime.now(timezone.utc).isoformat())
    (Path(assets)/'build-policy.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    evidence=Path(evidence_dir);evidence.mkdir(exist_ok=True)
    (evidence/'build-info.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    manual=(ROOT/'docs'/'CLIENT_MANUAL.txt').read_text(encoding='utf-8-sig').replace('{{APP_VERSION}}',APP_VERSION)
    (evidence/'CLIENT_MANUAL.txt').write_text(manual,encoding='utf-8-sig')
    # PE string version preserves the RC tag; Windows numeric version is separate.
    from packaging.version import Version
    parsed=Version(APP_VERSION);numeric=tuple([*parsed.release[:3],parsed.pre[1] if parsed.pre else 0])
    resource=f"""VSVersionInfo(ffi=FixedFileInfo(filevers={numeric},prodvers={numeric},mask=0x3f,flags=1,OS=0x40004,fileType=1,subtype=0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileVersion','{APP_VERSION}'),StringStruct('ProductVersion','{APP_VERSION}'),StringStruct('ProductName','Baseball Scouting AI Editor RC'),StringStruct('FileDescription','Baseball Scouting AI Editor RC')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])"""
    (evidence/'windows-version.txt').write_text(resource,encoding='utf-8')
    return value

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('assets');p.add_argument('kind',choices=['development','rules-preview','release']);args=p.parse_args();create(args.assets,args.kind)
