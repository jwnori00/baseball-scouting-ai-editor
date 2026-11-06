from dataclasses import asdict
from datetime import datetime, timezone
from .models import ReviewRecord


def review(session, event_id, action, *, start=None, end=None, note='', confirm_identity=False):
    if action not in ('APPROVED', 'EXCLUDED', 'REVIEW_REQUIRED'):
        raise ValueError('잘못된 검수 동작')
    event = next(e for e in session.events if e.id == event_id)
    before = dict(start=event.timeline_start, end=event.timeline_end, status=event.status,
                  pitcher_id=event.pitcher_id, batter_id=event.batter_id)
    a = event.timeline_start if start is None else start
    b = event.timeline_end if end is None else end
    if a < 0 or b <= a:
        raise ValueError('잘못된 검수 범위')
    segments = session.split(a, b)
    role_field = 'pitcher_id' if session.player.role == 'pitcher' else 'batter_id'
    if action == 'APPROVED' and getattr(event, role_field) != session.player.id and not confirm_identity:
        raise ValueError('대상 선수임을 명시적으로 확인해야 합니다')
    event.segments, event.timeline_start, event.timeline_end = segments, a, b
    if confirm_identity:
        setattr(event, role_field, session.player.id)
    if (a, b) != (before['start'], before['end']):
        for pa in session.appearances:
            if event.id in pa.event_ids:pa.confirmed = False
    event.status = action
    after = dict(start=a, end=b, status=action, pitcher_id=event.pitcher_id, batter_id=event.batter_id)
    event.history.append(ReviewRecord(action, before, after, note, datetime.now(timezone.utc).isoformat()))
    session.validate()


def classify_event(session,event_id,kind,note='검수자가 이벤트 유형 분류'):
    if kind not in ('pitch_candidate','pickoff','replay'):raise ValueError('잘못된 이벤트 유형')
    event=next(e for e in session.events if e.id==event_id)
    before=dict(event_type=event.event_type,status=event.status)
    event.event_type=kind;event.status='EXCLUDED' if kind=='replay' else 'REVIEW_REQUIRED'
    for pa in session.appearances:
        if event.id in pa.event_ids:pa.confirmed=False
    event.history.append(ReviewRecord('CLASSIFY',before,dict(event_type=kind,status=event.status),note,datetime.now(timezone.utc).isoformat()))
    session.validate()


def split_plate(session,event_id):
    from bsae.core.models import PlateAppearance
    event=next(e for e in session.events if e.id==event_id)
    if event.plate_id is None:
        ungrouped=sorted([e for e in session.events if e.plate_id is None and e.event_type not in ('replay','pickoff')],key=lambda e:e.timeline_start)
        if not ungrouped:raise ValueError('그룹화할 투구가 없습니다')
        pa=PlateAppearance([e.id for e in ungrouped],event.batter_id,event.inning)
        session.appearances.append(pa)
        for e in ungrouped:e.plate_id=pa.id
    pa=next(p for p in session.appearances if p.id==event.plate_id)
    index=pa.event_ids.index(event_id)
    if index:
        new=PlateAppearance(pa.event_ids[index:],event.batter_id,event.inning)
        pa.event_ids=pa.event_ids[:index];session.appearances.insert(session.appearances.index(pa)+1,new)
        for e in session.events:
            if e.id in new.event_ids:e.plate_id=new.id
    pa.confirmed=False
    by_id={e.id:e for e in session.events}
    session.appearances.sort(key=lambda p:min(by_id[i].timeline_start for i in p.event_ids))
    event.history.append(ReviewRecord('PLATE_SPLIT',{},dict(plate_id=event.plate_id),'검수자가 타석 경계 지정',datetime.now(timezone.utc).isoformat()))
    session.validate()


def merge_previous_plate(session,event_id):
    event=next(e for e in session.events if e.id==event_id)
    current=next(p for p in session.appearances if p.id==event.plate_id)
    index=session.appearances.index(current)
    if index==0:raise ValueError('이전 타석이 없습니다')
    previous=session.appearances[index-1];before=dict(plate_id=current.id)
    previous.event_ids.extend(current.event_ids);previous.confirmed=False
    for e in session.events:
        if e.id in current.event_ids:e.plate_id=previous.id
    session.appearances.remove(current)
    event.history.append(ReviewRecord('PLATE_MERGE',before,dict(plate_id=previous.id),'검수자가 동일 타석 확인 후 병합',datetime.now(timezone.utc).isoformat()))
    session.validate()
