"""Local comparison against separately reviewed reference projects. No uploads."""
from pathlib import Path
from itertools import combinations
import statistics
from bsae.core.models import GameSession,atomic_json
from bsae.evaluation import evaluate,write_csv
from bsae.vision.scoreboard import normalize


def compare_projects(predicted_path,reference_path,destination,*,reference_complete=False,manual_seconds=None,assisted_seconds=None):
    predicted=GameSession.load(predicted_path);reference=GameSession.load(reference_path)
    if predicted.player.role!=reference.player.role or normalize(predicted.player.name)!=normalize(reference.player.name):raise ValueError('선수/역할이 다른 정답 프로젝트')
    if [(s.fingerprint,s.offset) for s in predicted.sources]!=[(s.fingerprint,s.offset) for s in reference.sources]:raise ValueError('원본·파일 순서가 다른 정답 프로젝트')
    field='pitcher_id' if predicted.player.role=='pitcher' else 'batter_id'
    truth=[e for e in reference.events if e.status=='APPROVED' and e.event_type not in ('replay','pickoff')]
    if not truth or any(not e.history for e in truth):raise ValueError('독립적으로 검수·승인한 정답 기록이 필요합니다')
    candidates=[e for e in predicted.events if e.status!='EXCLUDED' and e.event_type not in ('replay','pickoff','other_player_or_ocr_error')]
    def item(e,target):return dict(start=e.timeline_start,end=e.timeline_end,player_id='target' if getattr(e,field)==target else None,plate_id=e.plate_id,followup_end=e.timeline_end)
    p=[item(e,predicted.player.id) for e in candidates];t=[item(e,reference.player.id) for e in truth]
    metrics=evaluate(p,t,manual_seconds=manual_seconds,assisted_seconds=assisted_seconds)
    edges=[]
    for i,a in enumerate(p):
        for j,b in enumerate(t):
            intersection=max(0,min(a['end'],b['end'])-max(a['start'],b['start']))
            union=max(a['end'],b['end'])-min(a['start'],b['start'])
            if intersection/union>=.5:edges.append((intersection/union,i,j))
    used_p=set();used_t=set();matched=[]
    for _,i,j in sorted(edges,reverse=True):
        if i not in used_p and j not in used_t:used_p.add(i);used_t.add(j);matched.append((i,j))
    metrics.update(reference_pitch_count=len(t),detected_pitch_count=len(p),
        unmatched_reference_count=len(t)-len(matched),unmatched_candidate_count=len(p)-len(matched),
        start_error_max=max((abs(p[i]['start']-t[j]['start']) for i,j in matched),default='NOT_EVALUATED'),
        end_error_max=max((abs(p[i]['end']-t[j]['end']) for i,j in matched),default='NOT_EVALUATED'),
        reference_plate_count=len({x['plate_id'] for x in t if x['plate_id']}),
        detected_plate_count=len({x['plate_id'] for x in p if x['plate_id']}),
        reference_complete=reference_complete,
        scope='COMPLETE_REFERENCE_COMPARISON' if reference_complete else 'PROVISIONAL_OR_PARTIAL_REFERENCE')
    pairs=[(p[a]['plate_id']==p[c]['plate_id'],t[b]['plate_id']==t[d]['plate_id']) for (a,b),(c,d) in combinations(matched,2)
           if all(v is not None for v in (p[a]['plate_id'],p[c]['plate_id'],t[b]['plate_id'],t[d]['plate_id']))]
    metrics['plate_pair_agreement']=sum(a==b for a,b in pairs)/len(pairs) if pairs else 'NOT_EVALUATED'
    if not reference_complete:
        for key in ('pitch_recall','precision','plate_recall','missing_play_rate','followup_preservation','identity_accuracy'):
            metrics[key]='NOT_EVALUATED'
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    atomic_json(destination/'validation.json',metrics);write_csv(destination/'validation.csv',[metrics])
    write_csv(destination/'matched-events.csv',[dict(candidate_id=candidates[i].id,reference_id=truth[j].id,
        start_error=p[i]['start']-t[j]['start'],end_error=p[i]['end']-t[j]['end']) for i,j in matched])
    return metrics
