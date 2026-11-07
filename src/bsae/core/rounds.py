"""Append-only analysis snapshots and explicit review-safe result application."""
from copy import deepcopy
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from .models import GameSession,PlayerIdentity,PlateAppearance,uid


def snapshot(session):
    return dict(title=session.title,player=asdict(session.player),sources=[asdict(s) for s in session.sources],events=[asdict(e) for e in session.events],appearances=[asdict(p) for p in session.appearances],game_date=session.game_date,id=session.id,schema=session.schema,analysis=deepcopy(session.analysis),output_settings=deepcopy(session.output_settings),active_round_id=session.active_round_id)


def identity_key(player):
    return (player.name,player.role,player.team,player.jersey,tuple(player.aliases),player.league)


def checkpoint(session,label='재탐색 전 검수 보관'):
    record=dict(id=uid(),kind='checkpoint',status='SAVED',created_at=datetime.now(timezone.utc).isoformat(),label=label,payload=snapshot(session))
    session.analysis_runs.append(record);return record


@dataclass
class RoundResult:
    session:GameSession
    round_id:str
    status:str
    error:str=''


def run_round(session,identity,profile,cache_path,stop=None,progress=lambda *a:None,analyzer=None):
    from bsae.vision.rules import analyze_plays
    from bsae.vision.pipeline import Cancelled
    base=deepcopy(session)
    if base.events or base.analysis_runs:checkpoint(base)
    work=GameSession(base.title,deepcopy(identity),deepcopy(base.sources),game_date=base.game_date,id=base.id,output_settings=deepcopy(base.output_settings))
    record=dict(id=uid(),kind='analysis',created_at=datetime.now(timezone.utc).isoformat(),profile={k:deepcopy(v) for k,v in profile.items() if k!='scene_weights'},status='PROPOSED')
    try:
        (analyzer or analyze_plays)(work,profile,cache_path,stop,progress)
        work.validate()
        if any(e.status=='APPROVED' for e in work.events):raise ValueError('자동 탐색은 플레이를 검수 완료로 승인할 수 없습니다')
    except Exception as exc:
        record.update(status='INTERRUPTED' if isinstance(exc,Cancelled) else 'FAILED',error=str(exc),payload=snapshot(work));base.analysis_runs.append(record)
        return RoundResult(base,record['id'],record['status'],str(exc))
    if 'profile_snapshot' in work.analysis:record['profile']=deepcopy(work.analysis['profile_snapshot'])
    record['payload']=snapshot(work);base.analysis_runs.append(record)
    if not base.events and identity_key(base.player)==identity_key(work.player):
        _activate(base,record);record['status']='APPLIED'
        return RoundResult(base,record['id'],'APPLIED')
    return RoundResult(base,record['id'],'PROPOSED')


def _record(session,round_id):
    record=next((r for r in session.analysis_runs if r['id']==round_id),None)
    if not record or record['status'] in ('FAILED','INTERRUPTED'):raise ValueError('적용할 수 없는 탐색 회차입니다')
    candidate=GameSession.from_dict(record['payload'])
    if candidate.id!=session.id or [(s.id,s.fingerprint) for s in candidate.sources]!=[(s.id,s.fingerprint) for s in session.sources]:raise ValueError('다른 원본/경기의 결과를 적용할 수 없습니다')
    return record,candidate


def comparison(session,round_id):
    _,candidate=_record(session,round_id);rows=[]
    for e in candidate.events:
        overlaps=[old for old in session.events if e.timeline_start<old.timeline_end and old.timeline_start<e.timeline_end]
        exact=any(abs(e.timeline_start-old.timeline_start)<=.15 and abs(e.timeline_end-old.timeline_end)<=.15 for old in overlaps)
        rows.append(dict(event_id=e.id,start=e.timeline_start,end=e.timeline_end,state='existing' if exact else 'overlap_changed' if overlaps else 'new',overlaps=[old.id for old in overlaps]))
    return rows


def _activate(session,record):
    candidate=GameSession.from_dict(record['payload'])
    for name in ('player','events','appearances','analysis','output_settings'):setattr(session,name,deepcopy(getattr(candidate,name)))
    session.active_round_id=record['id'];session.validate()


def apply_round(session,round_id,mode='replace'):
    record,candidate=_record(session,round_id)
    if mode not in ('replace','add_new','restore'):raise ValueError('회차 적용 방식 오류')
    if mode=='add_new' and identity_key(session.player)!=identity_key(candidate.player):raise ValueError('다른 선수/역할 결과는 추가할 수 없습니다. 회차 전환을 사용하세요.')
    # Work transactionally: a failed validation never alters active review data.
    work=deepcopy(session);checkpoint(work,'회차 적용 전 검수 보관')
    if mode in ('replace','restore'):
        settings=deepcopy(work.output_settings);_activate(work,record)
        if mode=='replace':work.output_settings=settings
    else:
        new_ids={r['event_id'] for r in comparison(work,round_id) if r['state']=='new'};mapping={}
        for e in candidate.events:
            if e.id not in new_ids:continue
            if any(e.timeline_start<old.timeline_end and old.timeline_start<e.timeline_end for old in work.events):continue
            old_id=e.id;e=deepcopy(e);e.id=uid();mapping[old_id]=e.id;e.plate_id=None
            e.number=max((old.number for old in work.events),default=0)+1
            for field in ('pitcher_id','batter_id'):
                if getattr(e,field)==candidate.player.id:setattr(e,field,work.player.id)
            e.status='EXCLUDED' if e.event_type=='replay' else 'REVIEW_REQUIRED';work.events.append(e)
        for pa in candidate.appearances:
            selected=[mapping[i] for i in pa.event_ids if i in mapping]
            if not selected:continue
            p=PlateAppearance(selected,work.player.id if pa.batter_id==candidate.player.id else pa.batter_id,pa.inning,batter_name=pa.batter_name)
            work.appearances.append(p)
            for e in work.events:
                if e.id in selected:e.plate_id=p.id;e.warnings.append('추가된 플레이의 타석 연결을 다시 검수하세요.')
        work.events.sort(key=lambda e:e.timeline_start)
        work.analysis['round_merge']=dict(round_id=round_id,added=len(mapping))
    applied=next(r for r in work.analysis_runs if r['id']==round_id)
    applied['last_application']=dict(mode=mode,at=datetime.now(timezone.utc).isoformat())
    if applied['kind']=='analysis':applied['status']='APPLIED'
    work.validate()
    for name in ('player','events','appearances','analysis','analysis_runs','active_round_id','output_settings'):setattr(session,name,getattr(work,name))
    return session


def clear_unsubstantiated_plates(session):
    """Explicit migration of untouched automatic guesses, with a restore point."""
    work=deepcopy(session);by_id={e.id:e for e in work.events};remove=set()
    for pa in work.appearances:
        events=[by_id[i] for i in pa.event_ids]
        if pa.confirmed or pa.batter_id or pa.batter_name:continue
        if any(e.history or e.batter_id or e.event_type=='manual_candidate' or any(x.kind=='ocr:batter_name' and x.value.strip() for x in e.evidence) for e in events):continue
        remove.add(pa.id)
    if not remove:return 0
    checkpoint(work,'근거 없는 자동 타석 정리 전 검수 보관')
    work.appearances=[p for p in work.appearances if p.id not in remove]
    for e in work.events:
        if e.plate_id in remove:e.plate_id=None
    work.analysis['automatic_plate_cleanup']=dict(removed=len(remove),reviewed_groups_preserved=True)
    work.validate()
    session.events,session.appearances,session.analysis,session.analysis_runs=work.events,work.appearances,work.analysis,work.analysis_runs
    return len(remove)
