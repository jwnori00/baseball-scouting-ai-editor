"""Verify portable assets and keep development/release gates separate."""
from pathlib import Path
import hashlib
import json
import sys
from bsae.vision.model import TemporalModel


def validate(root, kind='development'):
    if kind not in ('development','rules-preview','release'):raise ValueError('Unknown build kind')
    root=Path(root).resolve(strict=True)
    manifest=json.loads((root/'assets.json').read_text(encoding='utf-8'))
    verified=set()
    for e in manifest['files']:
        p=(root/e['path']).resolve(strict=True)
        if root not in p.parents:raise ValueError('외부 자산 경로')
        with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=e['sha256']:raise ValueError('자산 체크섬 불일치: '+e['path'])
        verified.add(p.relative_to(root).as_posix())
    folders=['tools','licenses','corresponding-source'] + (['models'] if kind=='release' else [])
    for folder in folders:
        files=[p for p in (root/folder).rglob('*') if p.is_file()]
        if not files:raise ValueError('필수 자산 폴더 없음: '+folder)
        if any(p.relative_to(root).as_posix() not in verified for p in files):raise ValueError('체크섬 미등록 자산: '+folder)
    for name in ('ffmpeg.exe','ffprobe.exe','tesseract.exe','tessdata/eng.traineddata'):
        if not (root/'tools'/name).is_file():raise ValueError('필수 도구 없음: '+name)
    if kind in ('rules-preview','release'):
        for language in ('kor','jpn'):
            if not (root/'tools'/'tessdata'/(language+'.traineddata')).is_file():raise ValueError('필수 OCR 언어 없음: '+language)
    if kind=='release':
        model=TemporalModel(root/'models'/'model.json')
        from bsae.vision.scoreboard import ScoreboardOCR
        if 'models/broadcast.json' not in verified:raise ValueError('검증된 중계 OCR 프로필 누락')
        profile=json.loads((root/'models'/'broadcast.json').read_text(encoding='utf-8'))
        ScoreboardOCR(profile)
        regions=profile.get('regions',{})
        for role in ('pitcher','batter'):
            if role+'_name' not in regions or not any(role+'_'+field in regions for field in ('jersey','team')):
                raise ValueError('선수 식별용 중계 프로필 부족: '+role)

        report_path=root/'models'/'validation.json'
        if 'models/validation.json' not in verified:raise ValueError('검증 보고서 체크섬 누락')
        report=json.loads(report_path.read_text(encoding='utf-8'))
        if report.get('model_sha256')!=model.digest or report.get('data_kind')!='real_baseball' or not report.get('independent_games') or not report.get('commercial_use_reviewed'):
            raise ValueError('실제 야구 독립 평가·상업 이용 검토 증거 필요')
        # Preserve every legacy model/commercial/metric gate and additionally
        # require evidence for the actual GUI discovery path.
        from bsae.vision.rules import VERSION,load_profile
        load_profile(root/'models'/'broadcast.json')
        if report.get('gui_engine')!=VERSION or report.get('evaluation_path')!='bsae.vision.workflow.analyze_for_review':
            raise ValueError('실제 GUI 규칙 엔진의 독립 평가 증거가 필요합니다')
        engine_source=Path(__file__).resolve().parents[1]/'src'/'bsae'/'vision'/'rules.py'
        if report.get('gui_engine_source_sha256')!=hashlib.sha256(engine_source.read_bytes().replace(b'\r\n',b'\n')).hexdigest():
            raise ValueError('GUI 엔진 평가와 현재 소스가 다릅니다')
        for name in ('rules.py','batter_text.py','scoreboard.py','workflow.py','scene.py','game_index.py'):
            source=engine_source.parent/name
            if report.get('gui_source_sha256',{}).get(name)!=hashlib.sha256(source.read_bytes().replace(b'\r\n',b'\n')).hexdigest():
                raise ValueError('GUI 분석 소스 평가 근거 누락/변경: '+name)
        for key,minimum in [('pitch_recall',.95),('plate_recall',.95),('precision',.90),('identity_accuracy',.98),('followup_preservation',.95),('review_time_savings',.70)]:
            value=report.get('metrics',{}).get(key)
            if not isinstance(value,(int,float)) or not minimum<=value<=1:raise ValueError('정식 배포 성능 미충족: '+key)
        for key in ('start_error_median','end_error_median'):
            value=report.get('metrics',{}).get(key)
            if not isinstance(value,(int,float)) or not 0<=value<=1:raise ValueError('정식 배포 경계 오차 미충족: '+key)
    elif kind=='rules-preview':
        from bsae.vision.rules import load_profile
        load_profile()
    elif (root/'models'/'model.json').exists():
        raise ValueError('개발판은 모델을 동봉하거나 자동 분석을 활성화하지 않습니다')
    return manifest


if __name__=='__main__':
    validate(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else 'development')
    print('Portable assets verified; release requires independent baseball validation.')
