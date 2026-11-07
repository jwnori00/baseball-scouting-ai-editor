from copy import deepcopy
from pathlib import Path
import threading
import numpy as np
import pytest
from bsae.core.models import GameSession,PlayerIdentity,PitchEvent,VideoSource,DetectionEvidence
from bsae.vision.batter_text import configure,interpret
from bsae.vision.rules import group_plates,Identity,load_profile,scan,Assembly
from bsae.vision.cache import Cache


def block(text,box=(.1,.7,.4,.8)):
    return dict(text=text,region=list(box),ocr_confidence=90,semantic_role='UNCONFIRMED')


def player():return PlayerIdentity('정수빈','batter','두산','31',league='KBO')


def test_caption_evidence_is_not_uniform_or_name_only_identity():
    p=player();profile=configure(load_profile(Path(__file__).parents[1]/'profiles/multi-broadcast-scene-v1.json'),p)
    assert profile['language']=='kor+eng' and profile['auto_batter_text']
    readings=interpret([block('정 수 빈')],p)
    assert 'batter_name_hint' in readings and 'batter_name' not in readings
    assert Identity(p,profile).update(0,readings)['state']=='unconfirmed'
    readings=interpret([block('타자 정수빈 두산 등번호 31')],p)
    assert Identity(p,profile).update(0,readings)['state']=='target'
    assert readings['batter_number_source']=='caption_label; NOT uniform_number'
    assert Identity(p,profile).update(0,interpret([block('타자 정수빈 두산 등번호 32')],p))['state']=='conflict'
    assert not interpret([block('이호준')],PlayerIdentity('이호','batter'))


def test_team_on_other_side_of_screen_is_not_identity_proof():
    p=player();readings=interpret([block('타자 정수빈'),block('두산',(.8,.02,.9,.08))],p)
    assert 'batter_team' not in readings
    assert Identity(p,configure(load_profile(),p)).update(0,readings)['state']=='unconfirmed'


def test_unidentified_pitch_is_not_a_plate_or_a_bridge():
    s=GameSession('Unknown',player(),[VideoSource('/synthetic',60,'synthetic')])
    s.events=[PitchEvent(s.id,s.split(t,t+2),t,t+2) for t in (0,5,10)]
    assert group_plates(s.events)==[] and all(e.plate_id is None for e in s.events)
    for e in (s.events[0],s.events[2]):e.evidence=[DetectionEvidence('ocr:batter_name','정수빈',e.timeline_start)]
    groups=group_plates(s.events)
    assert [len(g.event_ids) for g in groups]==[1,1] and s.events[1].plate_id is None


def test_generic_batter_scans_text_even_without_fixed_regions(make_video,tmp_path,monkeypatch):
    import bsae.vision.scoreboard as scoreboard
    from bsae.ingest.media import add_sources
    p=player();source=add_sources([make_video(['setup']*3)])[0]
    profile=configure(load_profile(Path(__file__).parents[1]/'profiles/multi-broadcast-scene-v1.json'),p)
    calls=[]
    monkeypatch.setattr(scoreboard,'text_regions',lambda *a,**kw:calls.append(kw['language']) or [block('타자 정수빈 두산')])
    c=Cache(tmp_path/'cache.sqlite')
    try:
        rows=list(scan(source,profile,c,threading.Event(),lambda *a:None))
        assert calls and any(row.get('text_blocks') for _,row in rows)
        before=len(calls);list(scan(source,profile,c,threading.Event(),lambda *a:None));assert len(calls)==before
    finally:c.close()


def test_pitcher_profile_is_unchanged():
    profile=load_profile();assert configure(profile,PlayerIdentity('투수'))==profile


def test_explicit_legacy_cleanup_preserves_edits_and_can_restore():
    from bsae.core.models import PlateAppearance
    from bsae.core.rounds import clear_unsubstantiated_plates,apply_round
    from bsae.core.review import review
    s=GameSession('Old',player(),[VideoSource('/synthetic',30,'synthetic')])
    for t in (0,5):
        e=PitchEvent(s.id,s.split(t,t+2),t,t+2);pa=PlateAppearance([e.id],None,None);e.plate_id=pa.id;s.events.append(e);s.appearances.append(pa)
    review(s,s.events[1].id,'APPROVED',confirm_identity=True)
    old=deepcopy(s);assert clear_unsubstantiated_plates(s)==1
    assert s.events[0].plate_id is None and s.events[1]==old.events[1] and len(s.appearances)==1
    apply_round(s,s.analysis_runs[0]['id'],'restore');assert s.events==old.events and s.appearances==old.appearances


def test_literal_quote_in_tesseract_tsv_does_not_swallow_following_rows(monkeypatch):
    import bsae.vision.scoreboard as scoreboard
    raw='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    raw+='5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90\t"\n'
    raw+='5\t1\t2\t1\t1\t1\t20\t20\t10\t10\t90\t정수빈\n'
    monkeypatch.setattr(scoreboard,'run',lambda *a,**k:raw.encode())
    blocks=scoreboard.text_regions(np.zeros((100,100,3),np.uint8))
    assert [b['text'] for b in blocks]==['"','정수빈']


def test_batter_default_list_does_not_present_unknowns_as_target(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication([]);w=Window()
    s=GameSession('Unknown',player(),[VideoSource('/synthetic',30,'synthetic')]);s.events=[PitchEvent(s.id,s.split(0,2),0,2)]
    w.session=s;w.fill_identity(s.player);w.refresh();assert w.table.rowCount()==0
    w.review_filter.setCurrentIndex(1);assert w.table.rowCount()==1
    assert '미확정' in w.active_context.text()
    w.dirty=False;w.close()


def test_future_target_caption_does_not_relabel_another_batters_pitch():
    from bsae.vision.rules import Assembly
    s=GameSession('Temporal safety',player(),[VideoSource('/synthetic',15,'synthetic')]);a=Assembly(s,load_profile())
    for i in range(80):
        t=i/10;name='다른타자' if t<4 else '정수빈'
        a.feed(t,dict(pitch_view=True,motion=3 if 20<=i<30 else .02,catcher_motion=1,field=.2,signature=str(i),ocr=dict(batter_name=name,batter_team='두산') if i%10==0 else {}))
    a.feed(8,dict(pitch_view=False,motion=0,catcher_motion=0,field=.2,signature='end'))
    events=a.finish(9);assert events and events[0].batter_id is None


def test_lower_name_requires_observed_pitcher_and_count_in_same_panel():
    from bsae.vision.batter_text import scorebug_name
    panel=[.1,.1,.4,.4]
    def row(text,y):return dict(text=text,region=[.11,y,.35,y+.02],panel_region=panel)
    lower=row('1. 정 수 빈 2 타수 0 안타',.34)
    pitcher=row('P 임찬규 34',.30);count=row('1-1',.23)
    assert scorebug_name(lower,[lower,count]) is None
    assert scorebug_name(lower,[lower,pitcher]) is None
    assert scorebug_name(lower,[lower,pitcher,count])=='정 수 빈'
    wrong=dict(pitcher,panel_region=[.5,.1,.8,.4])
    assert scorebug_name(lower,[lower,wrong,count]) is None
    s=interpret([lower,pitcher,count],player(),pitch_view=True)
    assert s['batter_role_source']=='scorebug_count_pitcher_neighbor' and s['count']=='1-1'
    identity=Identity(player(),configure(dict(load_profile(),regions={}),player()))
    assert identity.update(0,s)['state']=='unconfirmed'
    assert identity.update(2,s)['state']=='target'
    assert 'batter_jersey' not in s


def test_repeated_scorebug_name_does_not_survive_another_batter():
    p=player();i=Identity(p,configure(dict(load_profile(),regions={}),p))
    r=dict(batter_name=p.name,batter_current_role='scorebug',batter_role_source='scorebug_count_pitcher_neighbor')
    assert i.update(0,r)['state']=='unconfirmed'
    assert i.update(1,dict(batter_name='강민호'))['state']!='target'
    assert i.update(2,r)['state']=='unconfirmed'
    assert i.update(4,r)['state']=='target'


def test_explicit_position_wins_over_partial_same_caption_not_lineup():
    a=block('9 CF 정 수 빈 .254');b=block('9 수 빈 .254')
    assert interpret([a,b],player(),pitch_view=True)['batter_name']=='정 수 빈'
    c=block('8 LF 강 민 호 .301',(.1,.8,.4,.9))
    assert 'batter_name' not in interpret([a,c],player(),pitch_view=True)


def test_scorebug_accumulates_fresh_reads_not_intervening_motion_frames():
    p=player();i=Identity(p,configure(dict(load_profile(),regions={}),p))
    r=dict(batter_name=p.name,batter_current_role='live lower row',batter_role_source='scorebug_count_pitcher_neighbor')
    assert i.update(0,r)['state']=='unconfirmed'
    for t in (.1,.2,1,1.9):assert i.update(t,{})['state']=='unconfirmed'
    assert i.update(2,r)['state']=='target'


def test_user_selected_current_batter_region_works_without_fake_team_number():
    p=player();profile=configure(dict(load_profile(),regions={'batter_name':[.1,.1,.3,.2]},language='eng'),p)
    assert profile['language']=='kor+eng'
    i=Identity(p,profile)
    assert i.update(0,{'batter_name':'정수빈'})['state']=='unconfirmed'
    assert i.update(2,{'batter_name':'정 수 빈'})['state']=='target'
    assert i.update(3,{'batter_name':''})['state']=='unconfirmed'
    assert i.update(4,{'batter_name':'정수빈'})['state']=='unconfirmed'
    assert i.update(5,{'batter_name':'강민호'})['state']!='target'


def test_observed_opposing_team_overrules_matching_batter_caption():
    p=player();i=Identity(p,configure(dict(load_profile(),regions={}),p))
    result=i.update(0,dict(batter_name='정수빈',batter_team='삼성',batter_current_role='B. 정수빈'))
    assert result['state']=='conflict'
