import argparse
from dataclasses import asdict
import json
from pathlib import Path
import threading
from bsae.core.models import GameSession, PlayerIdentity, atomic_json
from bsae.ingest.media import add_sources, frames, tool


def parser():
    p=argparse.ArgumentParser(description='로컬 야구 후보 분석 도구 — 실제 경기 성능 미평가')
    sub=p.add_subparsers(dest='command', required=True)
    doctor=sub.add_parser('doctor', help='도구 및 모델 준비 확인')
    doctor.add_argument('--model')
    new=sub.add_parser('new', help='원본을 업로드하지 않고 로컬 프로젝트 생성')
    new.add_argument('project'); new.add_argument('videos', nargs='+')
    new.add_argument('--name', required=True); new.add_argument('--role', choices=['pitcher','batter'], default='pitcher')
    new.add_argument('--team', default=''); new.add_argument('--jersey', default='')
    new.add_argument('--alias', action='append', default=[]); new.add_argument('--date', default='')
    scan=sub.add_parser('analyze'); scan.add_argument('project'); scan.add_argument('--model', required=True)
    scan.add_argument('--profile', required=True); scan.add_argument('--cache', required=True)
    rev=sub.add_parser('review'); rev.add_argument('project'); rev.add_argument('event_id')
    rev.add_argument('--status', choices=['APPROVED','EXCLUDED','REVIEW_REQUIRED'], required=True)
    rev.add_argument('--start', type=float); rev.add_argument('--end', type=float)
    rev.add_argument('--confirm-identity', action='store_true'); rev.add_argument('--note', default='')
    group=sub.add_parser('confirm-plate'); group.add_argument('project'); group.add_argument('plate_id')
    exp=sub.add_parser('export'); exp.add_argument('project'); exp.add_argument('destination')
    exp.add_argument('--mode', choices=['all','pitch','plate'], default='all'); exp.add_argument('--include-pickoffs', action='store_true')
    train=sub.add_parser('train', help='사용권이 있는 로컬 라벨 영상으로 실험용 모델 학습')
    train.add_argument('labels'); train.add_argument('destination'); train.add_argument('--license', required=True)
    train.add_argument('--provenance', required=True)
    ev=sub.add_parser('evaluate'); ev.add_argument('project'); ev.add_argument('truth'); ev.add_argument('destination')
    ev.add_argument('--manual-seconds', type=float); ev.add_argument('--assisted-seconds', type=float)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    if args.command=='doctor':
        report={}
        for name in ('ffmpeg','ffprobe','tesseract'):
            try: report[name]=tool(name)
            except FileNotFoundError as e: report[name]=str(e)
        if args.model:
            from bsae.vision.model import TemporalModel
            m=TemporalModel(args.model); report['model']=m.info
        else:
            report['automatic_analysis']='BLOCKED: 학습 모델 미지정'
        print(json.dumps(report,ensure_ascii=False,indent=2)); return
    if args.command=='new':
        if Path(args.project).exists(): raise FileExistsError(args.project)
        session=GameSession(args.name,PlayerIdentity(args.name,args.role,args.team,args.jersey,args.alias),add_sources(args.videos),game_date=args.date)
        session.save(args.project); return
    if args.command=='train':
        from bsae.vision.model import features,train,LABELS
        spec=json.loads(Path(args.labels).read_text(encoding='utf-8'))
        samples, labels=[],[]
        # Labels are training supervision, never inserted into inference output.
        for item in spec:
            ranges=item['intervals']
            if any(r['label'] not in LABELS or r['start']<0 or r['end']<=r['start'] for r in ranges):
                raise ValueError('잘못된 학습 라벨')
            path=Path(item['video'])
            if not path.is_absolute(): path=Path(args.labels).resolve().parent/path
            previous=None
            for t,rgb in frames(path):
                x=features(rgb,previous); previous=rgb
                targets=[r['label'] for r in ranges if r['start']<=t<r['end']]
                if len(targets)>1: raise ValueError('학습 라벨 구간 중복')
                if targets: samples.append(x);labels.append(targets[0])
                if len(samples)>100_000: raise ValueError('학습 예제 100000개 한도: 데이터셋을 분할하세요')
        print(train(samples,labels,args.destination,license_name=args.license,provenance=args.provenance));return
    session=GameSession.load(args.project)
    if args.command=='analyze':
        from bsae.vision.pipeline import analyze
        profile=json.loads(Path(args.profile).read_text(encoding='utf-8'))
        try:
            analyze(session,args.model,profile,args.cache,progress=lambda stage,v: print(f'{v:.0%} {stage}',flush=True))
        except KeyboardInterrupt:
            print('중단됨: 캐시 체크포인트가 보존되었습니다. 같은 명령으로 재개하세요.');return 130
        session.save(args.project)
    elif args.command=='review':
        from bsae.core.review import review
        review(session,args.event_id,args.status,start=args.start,end=args.end,note=args.note,confirm_identity=args.confirm_identity)
        session.save(args.project)
    elif args.command=='confirm-plate':
        next(pa for pa in session.appearances if pa.id==args.plate_id).confirmed=True
        session.save(args.project)
    elif args.command=='export':
        from bsae.export.render import export
        print(export(session,args.destination,args.mode,include_pickoffs=args.include_pickoffs))
    elif args.command=='evaluate':
        from bsae.evaluation import evaluate, write_csv
        truth=json.loads(Path(args.truth).read_text(encoding='utf-8'))
        predicted=[dict(start=e.timeline_start,end=e.timeline_end,
            player_id=e.pitcher_id if session.player.role=='pitcher' else e.batter_id,plate_id=e.plate_id)
            for e in session.events if e.status!='EXCLUDED' and e.event_type!='pickoff']
        report=evaluate(predicted,truth,manual_seconds=args.manual_seconds,assisted_seconds=args.assisted_seconds)
        out=Path(args.destination)
        out.mkdir(exist_ok=False,parents=True)
        atomic_json(out/'metrics.json',report);write_csv(out/'metrics.csv',[report])
        print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    raise SystemExit(main())
