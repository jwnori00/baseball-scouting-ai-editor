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
