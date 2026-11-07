"""One explicit human approval, with atomic identity/review/group history."""
from copy import deepcopy
from datetime import datetime,timezone
from .models import ReviewRecord
from .review import _selection,confirm_manual_identities,review_many


def approval_warnings(session,event_ids):
    result=[]
    field='pitcher_id' if session.player.role=='pitcher' else 'batter_id'
    for e in _selection(session,event_ids):
        reclassified=any(h.action=='CLASSIFY' and h.after.get('event_type')=='pitch_candidate' for h in e.history)
        unsafe=e.event_type in ('replay','other_player_or_ocr_error') or e.broadcast_status in ('REPLAY_SUSPECTED','ARCHIVE_SUSPECTED') or ((e.identity_status=='OTHER_PLAYER' or getattr(e,field) not in (None,session.player.id)) and not reclassified)
        if unsafe:result.append(dict(id=e.id,number=e.number,reason='리플레이·자료화면·다른 선수: 실제 영상 확인 후 고급 편집에서 투구로 재분류하세요'))
    return result


def approve_clips(session,event_ids,*,user_approved=False,ranges=None,confirm_groups=False):
    selected=_selection(session,event_ids)
    if not user_approved:raise ValueError('사용자의 검수 승인 없이 자동 승인할 수 없습니다')
    warnings=approval_warnings(session,event_ids)
    if warnings:raise ValueError('재분류가 필요한 후보: '+', '.join(str(r['number']) for r in warnings))
    import math
    for event in selected:
        a,b=(ranges or {}).get(event.id,(event.timeline_start,event.timeline_end))
        try:
            if not all(math.isfinite(v) for v in (a,b)) or not 0<=a<b:raise ValueError('시작·종료 범위')
            session.split(a,b)
        except (ValueError,TypeError) as exc:raise ValueError(f'{event.number}번 클립의 시간 구간을 확인하세요: {a}–{b}') from exc
    working=deepcopy(session);ids=[e.id for e in selected]
    # A human approval is the identity confirmation. Automatic status is retained.
    confirm_manual_identities(working,ids)
    review_many(working,ids,confirm_identity=False,ranges=ranges,note='사용자가 선택 클립의 선수·구간을 함께 검수 승인')
    confirmed=0
    if confirm_groups:
        chosen=set(ids);by_id={e.id:e for e in working.events}
        for pa in working.appearances:
            if chosen.intersection(pa.event_ids) and all(by_id[i].status=='APPROVED' for i in pa.event_ids):
                if not pa.confirmed:
                    by_id[next(i for i in pa.event_ids if i in chosen)].history.append(ReviewRecord('PLATE_CONFIRMED',dict(plate_id=pa.id,confirmed=False),dict(plate_id=pa.id,confirmed=True),'타석 전체 선택 후 구성을 함께 검수 승인',datetime.now(timezone.utc).isoformat()))
                pa.confirmed=True;confirmed+=1
    working.validate();session.events,session.appearances=working.events,working.appearances
    return dict(approved=len(ids),confirmed_groups=confirmed)
