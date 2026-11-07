"""Rule tests supply measured cues, never ground-truth timestamps to inference."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import numpy as np
import pytest
from bsae.core.models import GameSession,PlayerIdentity,VideoSource,PitchEvent,DetectionEvidence
from bsae.vision.rules import Assembly,Identity,peaks,load_profile,group_plates,parse_count,clean_name,VERSION,analyze_plays
from bsae.core.review import classify_event


def project(role='pitcher',duration=60):
    player=PlayerIdentity('Daniel Martínez' if role=='pitcher' else 'Michael Wielansky',role,'TIJ' if role=='pitcher' else 'JAL')
    return GameSession('Synthetic rules',player,[VideoSource('/synthetic',duration,'synthetic')])


def measured(t,energy=0,view=True,**kwargs):
    return dict(pitch_view=view,motion=energy,catcher_motion=1,field=.2,cut=False,signature=str(t),**kwargs)


def episode(assembler,start=0,count='0-2',name='Michael Wielansky'):
    for i in range(80):
        # One windup/release episode and a later return, separated by no quiet
        # interval; must remain one pitch rather than two.
        energy=.05 if i<25 else (2.5 if i<40 else .8 if i<55 else 1.3 if i<60 else .5)
        ocr={'pitcher_name':'Daniel Martinez','pitcher_team':'TIJ','batter_name':name,'batter_team':'JAL','count':count}
        assembler.feed(start+i/10,measured(start+i/10,energy,ocr=ocr if i%10==0 else {}))
    assembler.feed(start+8,measured(start+8,view=False))


def test_short_delivery_is_not_lost_to_high_episode_median():
    profile=load_profile()
    values=[.6]*5+[1.,2.,3.,2.,1.]*3+[.7]*5
    rows=[(i/10,measured(i/10,v)) for i,v in enumerate(values)]
    assert peaks(rows,profile)


def test_camera_changes_alone_are_not_pitches():
    s=project();a=Assembly(s,load_profile())
    for i in range(40):a.feed(i/10,measured(i/10,0,view=i<30))
    assert a.finish(4)==[]


def test_return_motion_does_not_become_second_pitch():
    s=project();a=Assembly(s,load_profile());episode(a)
    events=a.finish(9)
    assert len(events)==1 and events[0].confidence is None
    assert events[0].status=='REVIEW_REQUIRED'
    assert events[0].pitcher_id==s.player.id


def test_unchanged_foul_count_keeps_both_pitches_one_plate():
    s=project('batter');a=Assembly(s,load_profile())
    episode(a,0,count='0-2');episode(a,10,count='0-2')
    events=a.finish(19);plates=group_plates(events)
    assert len(events)==2 and len(plates)==1 and len(plates[0].event_ids)==2
    assert all(e.batter_id==s.player.id for e in events)


def test_other_batter_and_inning_split_plate():
    s=project('batter');a=Assembly(s,load_profile())
    episode(a,0,name='Michael Wielansky');episode(a,10,name='Other Batter')
    events=a.finish(19);assert len(group_plates(events))==2
    assert events[-1].batter_id is None
    events[-1].inning='2'
    assert len(group_plates(events))==2


def test_ocr_name_change_invalidates_old_support():
    p=project().player;i=Identity(p,load_profile())
    assert i.update(0,{'pitcher_name':'Daniel Martinez','pitcher_team':'TIJ'})['state']=='target'
    assert i.update(1,{'pitcher_name':'Other Pitcher'})['state']!='target'
    assert i.update(30,{})['state']!='target'


def test_unidentified_candidates_are_preserved():
    s=project();a=Assembly(s,load_profile())
    for i in range(50):a.feed(i/10,measured(i/10,2 if 20<=i<30 else .02))
    a.feed(5,measured(5,view=False))
    events=a.finish(6)
    assert events and events[0].pitcher_id is None
    assert any('미확정' in w for w in events[0].warnings)


def test_inplay_camera_cut_preserves_fielding_and_running():
    s=project();a=Assembly(s,load_profile())
    for i in range(80):a.feed(i/10,measured(i/10,2 if 25<=i<45 else .05))
    for i in range(80,120):
        row=measured(i/10,view=False);row['field']=.8;row['cut']=i in (80,90,100)
        a.feed(i/10,row)
    a.feed(12,measured(12,view=False))
    events=a.finish(13)
    assert len(events)==1 and events[0].timeline_end==12
    assert any('수비' in w for w in events[0].warnings)


def test_replay_markers_exclude_without_approving():
    s=project();a=Assembly(s,load_profile())
    for i in range(60):a.feed(i/10,measured(i/10,2 if 20<=i<35 else .05,ocr={'replay':'REPLAY'}))
    a.feed(6,measured(6,view=False));events=a.finish(7)
    assert events[0].event_type=='replay' and events[0].status=='EXCLUDED'


def test_large_constant_camera_buffer_is_bounded():
    profile=load_profile();profile['max_episode_seconds']=12
    a=Assembly(project(duration=1000),profile)
    for i in range(600):a.feed(i/10,measured(i/10,0))
    assert len(a.episode)<=130 and len(a.recent)<=82


def test_count_parser_and_graphic_noise():
    assert parse_count('o-2 |')==(0,2)
    assert parse_count('02')==(0,2)
    assert parse_count('9-9') is None
    assert clean_name('| MICHAEL WIELANSKY if')=='MICHAEL WIELANSKY'
    assert clean_name('Fernando Tatis Jr')=='Fernando Tatis Jr'


def test_pickoff_classification_is_audited_and_needs_review():
    s=project();e=PitchEvent(s.id,s.split(1,3),1,3);s.events=[e]
    classify_event(s,e.id,'pickoff')
    assert e.event_type=='pickoff' and e.status=='REVIEW_REQUIRED' and e.history[-1].action=='CLASSIFY'
    classify_event(s,e.id,'replay');assert e.status=='EXCLUDED'


@pytest.fixture
def motion_video(tmp_path):
    import cv2,subprocess
    from bsae.ingest.media import tool
    images=[]
    for i in range(100):
        rgb=np.full((90,160,3),[65,130,65],np.uint8)
        cv2.rectangle(rgb,(121,55),(139,73),(15,15,15),-1)
        shift=0 if i<25 else int(12*np.sin((i-25)/20*np.pi)) if i<45 else 0
        cv2.rectangle(rgb,(50+shift,40),(59+shift,65),(240,240,240),-1)
        if i>=80:rgb[:]=80
        images.append(rgb.tobytes())
    path=tmp_path/'temporal-motion.mkv'
    subprocess.run([tool('ffmpeg'),'-v','error','-nostdin','-n','-f','rawvideo','-pix_fmt','rgb24','-s','160x90','-r','10','-i','pipe:0','-c:v','ffv1',str(path)],input=b''.join(images),check=True,capture_output=True)
    return path


def test_streaming_motion_video_to_candidates_and_cached_resume(motion_video,tmp_path):
    from bsae.ingest.media import add_sources,fingerprint
    from bsae.vision.pipeline import Cancelled
    profile=load_profile();profile['regions']={}
    s=GameSession('Motion fixture',PlayerIdentity('Unknown'),add_sources([motion_video]))
    original=fingerprint(motion_video);stop=threading.Event()
    def cancel(stage,v):
        if v>.3:stop.set()
    with pytest.raises(Cancelled):analyze_plays(s,profile,tmp_path/'cache.sqlite',stop,cancel)
    assert s.analysis['status']=='INTERRUPTED'
    analyze_plays(s,profile,tmp_path/'cache.sqlite')
    assert s.events and all(e.status=='REVIEW_REQUIRED' for e in s.events)
    expected=[(e.timeline_start,e.timeline_end) for e in s.events]
    analyze_plays(s,profile,tmp_path/'cache.sqlite')
    assert [(e.timeline_start,e.timeline_end) for e in s.events]==expected
    assert fingerprint(motion_video)==original


def test_cross_source_candidate_maps_real_segments():
    s=project(duration=5)
    s.sources.append(VideoSource('/synthetic2',10,'synthetic2',offset=5))
    a=Assembly(s,load_profile())
    episode(a,0);events=a.finish(9)
    assert len(events)==1 and len(events[0].segments)==2
    s.events=events;s.appearances=group_plates(events);s.validate()


def test_gui_button_calls_rules_engine_and_saves_results(motion_video,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QFileDialog
    from PySide6.QtCore import QEventLoop,QTimer
    from bsae.gui.window import Window
    import bsae.vision.rules as rules
    import bsae.ingest.media as media
    import sys
    profile=load_profile();profile['regions']={}
    original_tool=media.tool
    monkeypatch.setattr(media,'tool',lambda name:sys.executable if name=='tesseract' else original_tool(name))
    monkeypatch.setattr(rules,'load_profile',lambda path=None:profile)
    app=QApplication.instance() or QApplication([])
    w=Window();w.select_broadcast(Path(__file__).resolve().parents[1]/'profiles'/'lmb-telemetry-v1.json');w.name.setText('Unknown');w.files.addItem(str(motion_video))
    output=tmp_path/'gui-scan.json'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(output),'JSON'))
    assert w.analyze_button.isEnabled()
    w.analyze_button.click();assert w.job is not None
    loop=QEventLoop();w.job.finished.connect(loop.quit);QTimer.singleShot(15000,loop.quit);loop.exec()
    assert not w.job.isRunning()
    assert w.session and w.session.analysis['engine']==VERSION
    assert w.session.events and GameSession.load(output).analysis['engine']==VERSION
    assert w.table.columnCount()==7 and w.table.horizontalHeaderItem(6).text()=='타자'
    w.dirty=False;w.close();app.processEvents()


def test_replay_cannot_be_exported_as_approved_pitch(tmp_path):
    from bsae.export.render import export
    s=project();e=PitchEvent(s.id,s.split(1,3),1,3,pitcher_id=s.player.id,event_type='replay',status='APPROVED');s.events=[e]
    with pytest.raises(ValueError,match='리플레이'):export(s,tmp_path/'unsafe')


def test_reviewed_comparison_preserves_unevaluated_status(tmp_path):
    from bsae.validation import compare_projects
    from bsae.core.review import review
    s=project();e=PitchEvent(s.id,s.split(1,3),1,3);s.events=[e]
    predicted=tmp_path/'auto.json';s.save(predicted)
    review(s,e.id,'APPROVED',confirm_identity=True);reference=tmp_path/'truth.json';s.save(reference)
    r=compare_projects(predicted,reference,tmp_path/'report')
    assert r['reference_pitch_count']==r['detected_pitch_count']==1
    assert r['pitch_recall']=='NOT_EVALUATED' and r['reference_complete'] is False
    r=compare_projects(predicted,reference,tmp_path/'complete-report',reference_complete=True)
    assert r['pitch_recall']==1 and r['identity_accuracy']==0


def test_reference_plate_split_merge_preserves_pitch_cuts():
    from bsae.core.review import split_plate,merge_previous_plate
    s=project('batter');s.events=[PitchEvent(s.id,s.split(a,a+1),a,a+1,number=i+1) for i,a in enumerate((1,3,5))]
    original=[(e.timeline_start,e.timeline_end) for e in s.events]
    split_plate(s,s.events[0].id);assert len(s.appearances)==1
    split_plate(s,s.events[1].id);assert [len(p.event_ids) for p in s.appearances]==[1,2]
    merge_previous_plate(s,s.events[1].id);assert len(s.appearances)==1
    assert original==[(e.timeline_start,e.timeline_end) for e in s.events]
    assert all(e.history for e in (s.events[0],s.events[1]))


def test_korean_identity_never_collapses_to_empty():
    from bsae.vision.scoreboard import normalize,identify
    from bsae.vision.rules import name_matches
    a=PlayerIdentity('배영섭','batter','삼성','65');b=PlayerIdentity('이현승','pitcher','두산','48')
    assert normalize(a.name) and normalize(a.name)!=normalize(b.name)
    assert name_matches('배영섭',a) and not name_matches('이현승',a)
    assert identify(a,dict(batter_name='배영섭',batter_team='삼성'))[0]
    assert not identify(a,dict(batter_name='',batter_team='삼성'))[0]


def test_panel_free_camera_rejects_large_uniform_closeup():
    from bsae.vision.rules import camera_cues
    p=load_profile(Path(__file__).resolve().parents[1]/'profiles'/'kbo-mbc-centerfield-v1.json')
    image=np.zeros((180,320,3),np.uint8);image[90:]=[60,120,45]
    image[95:140,110:120]=230
    assert camera_cues(image,p)['pitch_view']
    image[50:170,100:200]=230
    assert not camera_cues(image,p)['pitch_view']


def test_batter_group_alias_foul_and_substitution():
    s=project(role='batter');events=[]
    for i,(name,player,count) in enumerate([('Bae Young-seop','same','0-2'),('배영섭','same','0-2'),('다른 타자','other','0-0')]):
        a=i*5
        events.append(PitchEvent(s.id,s.split(a,a+3),a,a+3,batter_id=player,evidence=[DetectionEvidence('ocr:batter_name',name,a),DetectionEvidence('ocr:count',count,a)]))
    groups=group_plates(events)
    assert [len(p.event_ids) for p in groups]==[2,1]
    assert all(not p.confirmed for p in groups)


@pytest.mark.parametrize('text,result',[('9초','9초'),('9回裏','9말'),('9 TOP','9초'),('9','9'),('0',None),('19:45',None)])
def test_inning_reading_never_invents_half(text,result):
    from bsae.vision.rules import parse_inning
    assert parse_inning(text)==result


def test_gui_rerun_same_document_preserves_approved_play(motion_video,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QFileDialog
    from PySide6.QtCore import QEventLoop,QTimer
    from bsae.gui.window import Window
    import bsae.vision.rules as rules
    profile=load_profile();profile['regions']={}
    monkeypatch.setattr(rules,'load_profile',lambda path=None:profile)
    app=QApplication.instance() or QApplication([]);w=Window();w.select_broadcast(Path(__file__).resolve().parents[1]/'profiles'/'lmb-telemetry-v1.json')
    w.name.setText('Unknown');w.files.addItem(str(motion_video));path=tmp_path/'rounds.json';dialogs=[]
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(dialogs.append(1) or str(path),'JSON'))
    errors=[];monkeypatch.setattr(w,'error',errors.append);proposals=[];monkeypatch.setattr(w,'show_analysis_rounds',proposals.append)
    def scan():
        w.analyze_button.click();assert not w.name.isEnabled() and not w.table.isEnabled();loop=QEventLoop();w.job.finished.connect(loop.quit);QTimer.singleShot(15000,loop.quit);loop.exec();app.processEvents();assert not w.job.isRunning()
    scan();assert w.session.events
    w.table.selectRow(0);w.confirm.setChecked(True);w.apply('APPROVED')
    event_id=w.session.events[0].id;before=deepcopy(w.session.events[0]);scan()
    assert not errors and len(dialogs)==1 and proposals
    assert next(e for e in w.session.events if e.id==event_id)==before
    restored=GameSession.load(path);assert next(e for e in restored.events if e.id==event_id).status=='APPROVED'
    assert restored.analysis_runs[-1]['status']=='PROPOSED'
    assert restored.analysis_runs[-1]['payload']['analysis']['cache_usage'][0]['complete_before']
    w.dirty=False;w.close()
