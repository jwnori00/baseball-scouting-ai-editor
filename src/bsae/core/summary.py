"""Counts are from the active round, not the current table filter."""


def review_counts(session):
    events=session.events if session else []
    return dict(total=len(events),automatic=sum(e.identity_status=='TARGET_CONFIRMED' for e in events),manual=sum(e.manual_identity_confirmed for e in events),overlap=sum(e.identity_status=='TARGET_CONFIRMED' and e.manual_identity_confirmed for e in events),unknown=sum(e.identity_status=='IDENTITY_UNKNOWN' and not e.manual_identity_confirmed for e in events),other=sum(e.identity_status=='OTHER_PLAYER' for e in events),approved=sum(e.status=='APPROVED' for e in events),excluded=sum(e.status=='EXCLUDED' for e in events))
