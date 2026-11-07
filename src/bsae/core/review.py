from dataclasses import asdict
from datetime import datetime, timezone
from .models import ReviewRecord


def review(session, event_id, action, *, start=None, end=None, note='', confirm_identity=False):
    if action not in ('APPROVED', 'EXCLUDED', 'REVIEW_REQUIRED'):
        raise ValueError('잘못된 검수 동작')
    event = next(e for e in session.events if e.id == event_id)
    if action=='APPROVED' and (event.event_type in ('replay','other_player_or_ocr_error') or event.broadcast_status in ('REPLAY_SUSPECTED','ARCHIVE_SUSPECTED')):raise ValueError('리플레이·자료화면·다른 선수 분류를 먼저 확인하세요')
    before = dict(start=event.timeline_start, end=event.timeline_end, status=event.status,
                  pitcher_id=event.pitcher_id, batter_id=event.batter_id,manual_identity_confirmed=event.manual_identity_confirmed,identity_status=event.identity_status)
    a = event.timeline_start if start is None else start
    b = event.timeline_end if end is None else end
    if a < 0 or b <= a:
        raise ValueError('잘못된 검수 범위')
    segments = session.split(a, b)
    role_field = 'pitcher_id' if session.player.role == 'pitcher' else 'batter_id'
    if action == 'APPROVED' and not confirm_identity and (getattr(event,role_field)!=session.player.id or not (event.identity_status=='TARGET_CONFIRMED' or event.manual_identity_confirmed)):
        raise ValueError('대상 선수임을 명시적으로 확인해야 합니다')
    event.segments, event.timeline_start, event.timeline_end = segments, a, b
    if confirm_identity:
        setattr(event, role_field, session.player.id)
        event.manual_identity_confirmed=True
    if (a,b)!=(before['start'],before['end']) or event.batter_id!=before['batter_id']:
        for pa in session.appearances:
            if event.id in pa.event_ids:pa.confirmed = False
    event.status = action
    after = dict(start=a, end=b, status=action, pitcher_id=event.pitcher_id, batter_id=event.batter_id,manual_identity_confirmed=event.manual_identity_confirmed,identity_status=event.identity_status)
    event.history.append(ReviewRecord(action, before, after, note, datetime.now(timezone.utc).isoformat()))
    session.validate()


def classify_event(session,event_id,kind,note='검수자가 이벤트 유형 분류'):
    if kind not in ('pitch_candidate','pickoff','replay'):raise ValueError('잘못된 이벤트 유형')
    event=next(e for e in session.events if e.id==event_id)
    before=dict(event_type=event.event_type,status=event.status)
    event.broadcast_status='REPLAY_SUSPECTED' if kind=='replay' else 'UNVERIFIED'
    event.event_type=kind;event.status='EXCLUDED' if kind=='replay' else 'REVIEW_REQUIRED'
    for pa in session.appearances:
        if event.id in pa.event_ids:pa.confirmed=False
    event.history.append(ReviewRecord('CLASSIFY',before,dict(event_type=kind,status=event.status),note,datetime.now(timezone.utc).isoformat()))
    session.validate()


def split_plate(session,event_id):
    from bsae.core.models import PlateAppearance
    event=next(e for e in session.events if e.id==event_id)
    if event.plate_id is None:raise ValueError('타석 미배정 후보입니다. 선택 투구를 한 타석으로 기능으로 먼저 구성하세요')
    pa=next(p for p in session.appearances if p.id==event.plate_id)
    index=pa.event_ids.index(event_id)
    if index:
        new=PlateAppearance(pa.event_ids[index:],event.batter_id,event.inning,batter_name=pa.batter_name)
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
    if not previous.batter_name:previous.batter_name=current.batter_name
    for e in session.events:
        if e.id in current.event_ids:e.plate_id=previous.id
    session.appearances.remove(current)
    event.history.append(ReviewRecord('PLATE_MERGE',before,dict(plate_id=previous.id),'검수자가 동일 타석 확인 후 병합',datetime.now(timezone.utc).isoformat()))
    session.validate()


def _selection(session,event_ids):
    ids=list(dict.fromkeys(event_ids))
    by_id={e.id:e for e in session.events}
    if not ids or any(i not in by_id for i in ids):
        raise ValueError('실제 후보를 하나 이상 선택하세요')
    return [by_id[i] for i in ids]


def review_many(session,event_ids,action='APPROVED',*,confirm_identity=False,note='GUI 선택 후보 일괄 검수',ranges=None):
    """Commit the whole selection or leave the original project unchanged."""
    from copy import deepcopy
    selected=_selection(session,event_ids)
    if action=='APPROVED' and any(e.event_type in ('replay','other_player_or_ocr_error') or e.broadcast_status in ('REPLAY_SUSPECTED','ARCHIVE_SUSPECTED') for e in selected):
        raise ValueError('리플레이·다른 선수 후보는 분류를 확인한 뒤 승인하세요')
    ranges=ranges or {}
    if set(ranges)-{e.id for e in selected}:raise ValueError('선택하지 않은 후보의 시각은 변경할 수 없습니다')
    working=deepcopy(session)
    for e in selected:
        a,b=ranges.get(e.id,(e.timeline_start,e.timeline_end))
        review(working,e.id,action,start=a,end=b,confirm_identity=confirm_identity,note=note)
    session.events,session.appearances=working.events,working.appearances
    return len(selected)


def set_innings(session,event_ids,value):
    """Edit event metadata and reconcile affected plate groups, with an audit."""
    import re
    from copy import deepcopy
    selected=_selection(session,event_ids)
    text=re.sub(r'\s+','',value)
    if text in ('','?'):inning=None
    else:
        match=re.fullmatch(r'([1-9][0-9]?)(?:회)?(초|말)?',text)
        if not match:raise ValueError('이닝은 1~99, 9초, 9회말처럼 입력하세요. 비우면 미확정입니다.')
        inning=match.group(1)+(match.group(2) or '')
    working=deepcopy(session);ids={e.id for e in selected};changed=set()
    for event in working.events:
        if event.id not in ids or event.inning==inning:continue
        before=dict(inning=event.inning);event.inning=inning;changed.add(event.id)
        event.history.append(ReviewRecord('INNING_CHANGED',before,dict(inning=inning),'검수자 직접 입력',datetime.now(timezone.utc).isoformat()))
    by_id={e.id:e for e in working.events}
    for plate in working.appearances:
        if not changed.intersection(plate.event_ids):continue
        innings={by_id[i].inning for i in plate.event_ids}
        plate.inning=next(iter(innings)) if len(innings)==1 else None
        plate.confirmed=False
    working.validate();session.events,session.appearances=working.events,working.appearances
    return len(changed)


def assign_plate(session,event_ids,batter_name=''):
    """Explicitly group a consecutive set of pitches, retaining unselected fragments."""
    from copy import deepcopy
    from .models import PlateAppearance
    chosen=_selection(session,event_ids);ids={e.id for e in chosen}
    if any(e.event_type in ('replay','pickoff','other_player_or_ocr_error') for e in chosen):raise ValueError('실제 투구 후보만 타석으로 묶을 수 있습니다')
    ordered=sorted([e for e in session.events if e.event_type not in ('replay','pickoff','other_player_or_ocr_error')],key=lambda e:e.timeline_start)
    indices=[i for i,e in enumerate(ordered) if e.id in ids]
    if indices!=list(range(min(indices),max(indices)+1)):raise ValueError('한 타석은 연속된 투구를 선택하세요. 중간 투구를 빠뜨릴 수 없습니다')
    innings={e.inning for e in chosen if e.inning}
    if len(innings)>1:raise ValueError('서로 다른 이닝의 투구를 한 타석으로 묶을 수 없습니다')
    work=deepcopy(session);by_id={e.id:e for e in work.events};groups=[]
    for pa in work.appearances:
        if not ids.intersection(pa.event_ids):groups.append(pa);continue
        # Preserve each contiguous remaining fragment as its own unconfirmed group.
        fragment=[]
        for eid in sorted(pa.event_ids,key=lambda i:by_id[i].timeline_start):
            if eid in ids:
                if fragment:groups.append(PlateAppearance(fragment,pa.batter_id,pa.inning,batter_name=pa.batter_name));fragment=[]
            else:fragment.append(eid)
        if fragment:groups.append(PlateAppearance(fragment,pa.batter_id,pa.inning,batter_name=pa.batter_name))
    chosen=sorted([by_id[i] for i in ids],key=lambda e:e.timeline_start)
    batter_ids={e.batter_id for e in chosen if e.batter_id}
    if len(batter_ids)>1:raise ValueError('다른 타자로 확인된 투구가 섞여 있습니다')
    pa=PlateAppearance([e.id for e in chosen],next(iter(batter_ids),None),next(iter(innings),None),batter_name=batter_name.strip())
    groups.append(pa);groups.sort(key=lambda p:min(by_id[i].timeline_start for i in p.event_ids))
    for group in groups:
        for eid in group.event_ids:by_id[eid].plate_id=group.id
    for event in chosen:event.history.append(ReviewRecord('PLATE_ASSIGN',{},dict(plate_id=pa.id,batter_name=pa.batter_name),'검수자가 선택 투구를 한 타석으로 구성',datetime.now(timezone.utc).isoformat()))
    work.appearances=groups;work.validate();session.events,session.appearances=work.events,work.appearances
    return pa.id


def name_plate(session,event_id,name):
    from copy import deepcopy
    work=deepcopy(session);event=next(e for e in work.events if e.id==event_id)
    pa=next((p for p in work.appearances if p.id==event.plate_id),None)
    if pa is None:raise ValueError('먼저 선택 투구를 한 타석으로 묶으세요')
    before=pa.batter_name;pa.batter_name=name.strip();pa.confirmed=False
    for eid in pa.event_ids:
        e=next(e for e in work.events if e.id==eid)
        e.history.append(ReviewRecord('PLATE_BATTER_NAME',dict(batter_name=before),dict(batter_name=pa.batter_name),'검수자 타자명 수정; 자동 신원 확인 아님',datetime.now(timezone.utc).isoformat()))
    work.validate();session.events,session.appearances=work.events,work.appearances


def set_pitch_numbers(session,numbers):
    """Edit labels only; never renumber unselected events or change review state."""
    from copy import deepcopy
    if not numbers:raise ValueError('수정할 투구 번호가 없습니다')
    _selection(session,numbers)
    if any(type(n) is not int or not 1<=n<=99999 for n in numbers.values()):raise ValueError('투구 번호는 1~99999의 정수로 입력하세요')
    work=deepcopy(session);changed=0
    for e in work.events:
        if e.id not in numbers or e.number==numbers[e.id]:continue
        old=e.number;e.number=numbers[e.id];changed+=1
        e.history.append(ReviewRecord('PITCH_NUMBER_CHANGED',dict(number=old),dict(number=e.number),'검수자 투구 번호 직접 수정',datetime.now(timezone.utc).isoformat()))
    work.validate();session.events=work.events
    return changed


def confirm_manual_identities(session,event_ids):
    """Explicit human identity confirmation without altering automatic identity or approval."""
    from copy import deepcopy
    selected=_selection(session,event_ids);work=deepcopy(session)
    for old in selected:
        e=next(e for e in work.events if e.id==old.id)
        if e.event_type in ('replay','other_player_or_ocr_error') or e.broadcast_status!='UNVERIFIED':raise ValueError('먼저 리플레이·자료화면·다른 선수 분류를 확인하세요')
        field='pitcher_id' if work.player.role=='pitcher' else 'batter_id'
        before=dict(manual_identity_confirmed=e.manual_identity_confirmed,player_id=getattr(e,field))
        setattr(e,field,work.player.id);e.manual_identity_confirmed=True
        e.history.append(ReviewRecord('MANUAL_IDENTITY_CONFIRMED',before,dict(manual_identity_confirmed=True,player_id=work.player.id),'검수자가 이 후보의 대상을 직접 확인; 자동 판정은 변경하지 않음',datetime.now(timezone.utc).isoformat()))
    for pa in work.appearances:
        if set(pa.event_ids).intersection(event_ids):pa.confirmed=False
    work.validate();session.events,session.appearances=work.events,work.appearances
    return len(selected)
