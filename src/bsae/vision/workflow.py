"""Shared GUI and acceptance discovery path; no Qt or automatic approval."""
from copy import deepcopy
from .rules import load_profile


def analyze_for_review(session,profile,cache,stop=None,progress=lambda *a:None,*,automatic_profile=False,preflight=None):
    selected=deepcopy(profile) if isinstance(profile,dict) else load_profile(profile)
    assessment=None
    if automatic_profile:
        from .profile_detection import select_profile
        progress('중계 구도·문자 영역 자동 탐색 시도',0)
        selected,assessment=select_profile(session.sources[0],stop,session.player)
        session.analysis['preflight']=assessment.get('preflight',{})
        if session.player.role=='batter' and not assessment.get('preflight',{}).get('identity_evidence_frames') and preflight:
            preflight(assessment)
    # Import through the module so tests/diagnostics observe the same engine.
    from . import rules
    rules.analyze_plays(session,selected,cache,stop,progress)
    session.analysis.setdefault('profile_snapshot',{k:v for k,v in selected.items() if k!='scene_weights'})
    session.analysis['execution_path']='bsae.vision.workflow.analyze_for_review'
    session.analysis['automatic_profile']=bool(automatic_profile)
    if assessment:
        session.analysis['preflight']=assessment.get('preflight',{})
        session.analysis['layout_detection']=assessment
        if assessment['status']=='UNRECOGNIZED_LAYOUT':session.analysis['status']='UNRECOGNIZED_LAYOUT_REVIEW_REQUIRED'
    return session
