"""Single source for application version and persisted build provenance."""
from pathlib import Path
import json
import sys

APP_VERSION='1.0.0rc2'
BUILD_LABEL='배포 후보판(RC) · 검수 필수'


def build_info():
    from bsae.vision.rules import VERSION
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
    path=root/'build-policy.json'
    info=json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
    value=dict(version=APP_VERSION,kind='source',engine=VERSION,commit='NOT_RECORDED',built_at='NOT_RECORDED')
    value.update(info);value['runtime_engine']=VERSION;value['source_version']=APP_VERSION
    return value
