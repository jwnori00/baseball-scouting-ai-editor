"""Offline executable acceptance on user-owned local media and reviewed truth."""
from copy import deepcopy
from pathlib import Path
import json
from bsae.core.models import GameSession,atomic_json
from bsae.evaluation import evaluate
from bsae.export.render import export
from bsae.vision.pipeline import analyze


def run_acceptance(plan_path, report_path):
    plan=json.loads(Path(plan_path).read_text(encoding='utf-8'))
    reference=GameSession.load(plan['reference_project'])
    protected={Path(plan['reference_project']).resolve(), *(Path(s.path).resolve() for s in reference.sources)}
    for key in ('candidate_project','cache','output'):
        if Path(plan[key]).resolve() in protected:
            raise ValueError('인수 시험 경로가 원본/정답과 충돌합니다')
    if Path(plan['candidate_project']).exists() or Path(report_path).exists():
        raise FileExistsError('기존 후보/보고서를 덮어쓰지 않습니다')
    approved=[e for e in reference.events if e.status=='APPROVED' and e.event_type!='pickoff']
    if not approved or any(not e.history for e in approved):
        raise ValueError('실제 사람이 검수하고 승인 이력을 저장한 정답 프로젝트가 필요합니다')
    if not plan.get('ground_truth_complete') or not plan.get('followup_reviewed'):
        raise ValueError('정답의 전수 확인 및 후속 플레이 보존 검수 선언이 필요합니다')
    candidate=deepcopy(reference)
    candidate.events=[];candidate.appearances=[];candidate.analysis={}
    analyze(candidate,plan['model'],plan['profile'],plan['cache'])
    candidate.save(plan['candidate_project'])
    field='pitcher_id' if reference.player.role=='pitcher' else 'batter_id'
    predictions=[dict(start=e.timeline_start,end=e.timeline_end,player_id=getattr(e,field),plate_id=e.plate_id)
        for e in candidate.events if e.event_type!='pickoff']
    truth=[dict(start=e.timeline_start,end=e.timeline_end,player_id=getattr(e,field),plate_id=e.plate_id,followup_end=e.timeline_end) for e in approved]
    metrics=evaluate(predictions,truth,manual_seconds=plan.get('manual_seconds'),assisted_seconds=plan.get('assisted_seconds'))
    # Export only pre-existing human approvals, never approve predictions for the test.
    output=export(reference,plan['output'])
    limits={'pitch_recall':(.95,True),'precision':(.90,True),'identity_accuracy':(.98,True),
        'start_error_median':(1,False),'end_error_median':(1,False),
        'followup_preservation':(.95,True),'review_time_savings':(.70,True)}
    if reference.player.role=='batter':limits['plate_recall']=(.95,True)
    outcomes={}
    for name,(threshold,minimum) in limits.items():
        value=metrics[name]
        outcomes[name]='NOT_EVALUATED' if not isinstance(value,(int,float)) else ('PASS' if (value>=threshold if minimum else value<=threshold) else 'FAIL')
    report=dict(metrics=metrics,checks=outcomes,output=str(output),
        status='PASS' if all(v=='PASS' for v in outcomes.values()) else 'NOT_READY',
        gui_interaction='REQUIRES_MANUAL_CLEAN_WINDOWS_CHECK',
        note='Analysis evaluated against local human-reviewed reference; rendered reference approvals only. No raw media uploaded.')
    atomic_json(report_path,report)
    return report
