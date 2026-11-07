from copy import deepcopy
from dataclasses import asdict
import pytest
from bsae.core.models import GameSession,PlayerIdentity,VideoSource,PitchEvent
from bsae.core.rounds import run_round,apply_round,comparison
from bsae.core.review import review


def project():
    s=GameSession('Round test',PlayerIdentity('선수A','pitcher','팀','48'),[VideoSource('/synthetic',30,'synthetic')])
    s.events=[PitchEvent(s.id,s.split(1,4),1,4,number=1)]
    review(s,s.events[0].id,'APPROVED',confirm_identity=True)
    return s


def analyze(work,*args):
    work.events=[PitchEvent(work.id,work.split(a,b),a,b,pitcher_id=work.player.id) for a,b in [(1.2,4.1),(8,11)]]
    work.analysis=dict(engine='test-only',status='COMPLETE_REVIEW_REQUIRED')


def test_repeat_preserves_review_then_merge_and_restore(tmp_path):
    s=project();old=deepcopy(s.events[0]);identity=deepcopy(s.player);identity.id='new-analysis-player-id'
    result=run_round(s,identity,dict(id='test'),tmp_path/'cache',analyzer=analyze)
    assert result.status=='PROPOSED' and asdict(result.session.events[0])==asdict(old)
    assert len(s.analysis_runs)==0  # Caller is unchanged until it accepts returned result.
    s=result.session
    assert [r['state'] for r in comparison(s,result.round_id)]==['overlap_changed','new']
    checkpoint_id=s.analysis_runs[0]['id'];apply_round(s,result.round_id,'add_new')
    assert len(s.events)==2 and asdict(s.events[0])==asdict(old)
    assert s.events[1].pitcher_id==s.player.id and s.events[1].status=='REVIEW_REQUIRED'
    path=tmp_path/'project.json';s.save(path);s=GameSession.load(path)
    apply_round(s,checkpoint_id,'restore');assert len(s.events)==1 and asdict(s.events[0])==asdict(old)


def test_failure_and_other_player_never_overwrite_active_review(tmp_path):
    s=project();before=asdict(s.events[0])
    def fail(work,*args):raise RuntimeError('decoder test failure')
    failed=run_round(s,deepcopy(s.player),{},tmp_path/'cache',analyzer=fail)
    assert failed.status=='FAILED' and asdict(failed.session.events[0])==before
    other=PlayerIdentity('선수B','batter','다른팀','9')
    result=run_round(s,other,{},tmp_path/'cache',analyzer=analyze)
    with pytest.raises(ValueError,match='다른 선수'):apply_round(result.session,result.round_id,'add_new')
    assert asdict(result.session.events[0])==before
    apply_round(result.session,result.round_id,'replace')
    assert result.session.player.name=='선수B' and all(e.status!='APPROVED' for e in result.session.events)
    assert any(r['payload']['events'][0]['status']=='APPROVED' for r in result.session.analysis_runs if r['kind']=='checkpoint')


def test_analysis_cannot_auto_approve(tmp_path):
    s=project();old=deepcopy(s.events)
    def unsafe(work,*args):
        work.events=[PitchEvent(work.id,work.split(5,8),5,8,status='APPROVED')]
    result=run_round(s,deepcopy(s.player),{},tmp_path/'cache',analyzer=unsafe)
    assert result.status=='FAILED' and result.session.events==old
