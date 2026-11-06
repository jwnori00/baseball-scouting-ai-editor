import json
import threading
from pathlib import Path
from dataclasses import asdict
import numpy as np
import pytest
from bsae.core.models import GameSession,PlayerIdentity,PitchEvent,DetectionEvidence,PlaySegment
from bsae.core.review import review
from bsae.ingest.media import add_sources,frames,fingerprint,probe
from bsae.vision.model import TemporalModel,features
from bsae.vision.scoreboard import identify
from bsae.vision.pipeline import analyze,Assembler,Cancelled,group_appearances
from bsae.vision.cache import Cache
from bsae.export.render import export
from bsae.evaluation import evaluate


def session(paths,role='pitcher'):
    return GameSession('Synthetic',PlayerIdentity('Daniel Martínez',role,'LMB','42'),add_sources(paths))


def test_stream_pts_and_multifile(make_video):
    paths=[make_video(['other','setup'],'a.mkv'),make_video(['delivery','receive','dead'],'b.mkv')]
    s=session(paths)
    assert s.sources[1].offset==pytest.approx(2)
    assert len(s.split(1,3))==2
    samples=list(frames(paths[0]))
    assert [t for t,_ in samples]==pytest.approx([i/4 for i in range(8)])
    assert samples[0][1].shape==(90,160,3)


def test_real_inference_to_review_and_render(make_video,trained,tmp_path):
    manifest,_=trained
    source=make_video(['other','setup','delivery','receive','live','dead','other','setup','delivery','receive','dead'],audio=True)
    before=fingerprint(source)
    s=session([source])
    analyze(s,manifest,{},tmp_path/'cache.sqlite')
    assert len(s.events)==2
    assert s.events[0].timeline_start==pytest.approx(1)
    assert s.events[0].timeline_end==pytest.approx(5)
    assert all(e.status=='REVIEW_REQUIRED' and e.confidence is None for e in s.events)
    with pytest.raises(ValueError,match='승인'):export(s,tmp_path/'not-approved')
    with pytest.raises(ValueError,match='선수'):review(s,s.events[0].id,'APPROVED')
    for e in s.events:review(s,e.id,'APPROVED',confirm_identity=True)
    for pa in s.appearances:pa.confirmed=True
    path=tmp_path/'project.json';s.save(path);s=GameSession.load(path)
    assert s.events[0].history[0].action=='APPROVED'
    for mode,count in [('all',1),('pitch',2),('plate',2)]:
        destination=export(s,tmp_path/mode,mode)
        outputs=list(destination.glob('*.mp4'))
        assert len(outputs)==count
        assert json.loads((destination/'manifest.json').read_text())['completeness']=='NOT_EVALUATED'
        assert all(float(probe(p)['format']['duration'])>0 for p in outputs)
        with pytest.raises(FileExistsError):export(s,destination,mode)
    assert before==fingerprint(source)


def test_missing_or_tampered_model_fails(trained,make_video,tmp_path):
    s=session([make_video(['setup','delivery','receive','dead'])])
    with pytest.raises(FileNotFoundError):analyze(s,tmp_path/'missing.json',{},tmp_path/'cache.sqlite')
    assert not s.events
    manifest,_=trained
    data=json.loads(manifest.read_text());data['sha256']='0'*64
    altered=manifest.parent/'tampered.json';altered.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='체크섬'):TemporalModel(altered)


def test_cache_cancel_resume(make_video,trained,tmp_path):
    s=session([make_video(['setup','delivery','receive','live','dead'])])
    stop=threading.Event()
    def cancel(stage,value):
        if value>.3:stop.set()
    with pytest.raises(Cancelled):analyze(s,trained[0],{},tmp_path/'c.sqlite',stop,cancel)
    cache=Cache(tmp_path/'c.sqlite')
    assert cache.db.execute('SELECT COUNT(*) FROM frames').fetchone()[0]>0
    cache.close()
    analyze(s,trained[0],{},tmp_path/'c.sqlite')
    assert len(s.events)==1
    initial=[(e.timeline_start,e.timeline_end) for e in s.events]
    analyze(s,trained[0],{},tmp_path/'c.sqlite')
    assert [(e.timeline_start,e.timeline_end) for e in s.events]==initial


def test_identity_accent_and_multiple_evidence():
    p=PlayerIdentity('Daniel Martínez',team='Club',jersey='42',aliases=['D. Martinez'])
    assert not identify(p,{'pitcher_name':'D. Martinez'})[0]
    assert identify(p,{'pitcher_name':'Daniel Martinez','pitcher_jersey':'42'})[0]
    assert not identify(p,{'batter_name':'Daniel Martinez','pitcher_jersey':'42'})[0]


def test_camera_changes_do_not_finish_active_play(make_video):
    s=session([make_video(['other']*12)])
    a=Assembler(s)
    sequence=[('setup',0),('delivery',1),('receive',2),('other',3),('live',4),('other',5),('dead',8),('replay',9)]
    for label,t in sequence:a.feed(t,dict(label=label,scores={label:1},ocr={}))
    assert len(a.events)==1
    assert a.events[0].timeline_end==8
    assert len(a.events[0].evidence)>=4


def test_batter_groups_and_substitution(make_video):
    s=session([make_video(['other']*10)],'batter');a=Assembler(s)
    for start,inning,name in [(0,'1 top','Daniel Martinez'),(3,'1 top','Daniel Martinez'),(6,'2 top','Other')]:
        ocr={'batter_name':name,'batter_jersey':'42','inning':inning}
        for delta,label in [(0,'setup'),(.5,'delivery'),(1,'receive'),(2,'dead')]:
            a.feed(start+delta,dict(label=label,scores={label:1},ocr=ocr))
    groups=group_appearances(a.events)
    assert len(groups)==2 and len(groups[0].event_ids)==2
    assert a.events[0].batter_id==s.player.id
    assert a.events[-1].batter_id is None


def test_cross_file_event_render(make_video,tmp_path):
    p1=make_video(['other']*2,'one.mkv');p2=make_video(['other']*2,'two.mkv')
    s=session([p1,p2]);e=PitchEvent(s.id,s.split(1,3),1,3,number=1)
    s.events=[e];review(s,e.id,'APPROVED',confirm_identity=True)
    export(s,tmp_path/'out')
    assert float(probe(tmp_path/'out'/'all_0001.mp4')['format']['duration'])==pytest.approx(2,abs=.3)
    e.segments[0].end=100
    with pytest.raises(ValueError):s.validate()


def test_metrics_no_claim_without_truth():
    assert evaluate([],[])['pitch_recall']=='NOT_EVALUATED'
    p=[dict(start=1,end=4,player_id='a',plate_id='p')]*2
    truth=[dict(start=1,end=4,player_id='a',plate_id='q',followup_end=4)]
    r=evaluate(p,truth)
    assert r['precision']==.5 and r['pitch_recall']==1 and r['identity_accuracy']==1
    assert r['matched']==1 and r['review_time_savings']=='NOT_EVALUATED'


def test_source_protection_and_changed_media(make_video,tmp_path,trained):
    source=make_video(['setup','delivery','receive','dead']);s=session([source])
    with pytest.raises(ValueError):s.save(source)
    with source.open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='변경'):analyze(s,trained[0],{},tmp_path/'cache.sqlite')


def test_gui_model_gate():
    from PySide6.QtWidgets import QApplication
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication([])
    w=Window()
    assert not w.analyze_button.isEnabled()
    assert 'BLOCKED' in w.availability.text()
    w.close();app.processEvents()


def test_replay_model_state_does_not_create_pitch(make_video,trained,tmp_path):
    s=session([make_video(['setup','delivery','receive','dead','replay','replay','other'])])
    analyze(s,trained[0],{},tmp_path/'cache.sqlite')
    assert len(s.events)==1


def test_exact_overlap_requires_motion():
    from bsae.vision.replay import exact_overlap
    sequence=[str(i) for i in range(10)]
    assert exact_overlap(['earlier']+sequence,sequence+['later'])==10
    assert exact_overlap(['static']*20,['static']*20)==0
    assert exact_overlap(sequence,list(reversed(sequence)))==0


def test_local_ocr_reads_rendered_text():
    import shutil
    if not shutil.which('tesseract'):pytest.skip('Tesseract optional for CI without OCR tool; local OCR is tested separately')
    import cv2
    from bsae.vision.scoreboard import ScoreboardOCR
    rgb=np.full((100,600,3),255,np.uint8)
    cv2.putText(rgb,'MARTINEZ',(10,65),cv2.FONT_HERSHEY_SIMPLEX,2,(0,0,0),3)
    values=ScoreboardOCR(dict(regions={'pitcher_name':[0,0,1,1]},language='eng')).read(rgb)
    assert 'MARTINEZ' in values['pitcher_name']


def test_vfr_nonzero_pts_are_normalized(tmp_path):
    from bsae.ingest.media import run
    path=tmp_path/'vfr.mkv'
    run('ffmpeg',['-v','error','-nostdin','-n','-f','lavfi','-i','testsrc2=size=160x90:rate=10:duration=2',
        '-vf',"select='not(mod(n,3))',setpts=PTS+5/TB",'-fps_mode','vfr','-c:v','ffv1',path])
    timestamps=[t for t,_ in frames(path)]
    assert timestamps[0]==pytest.approx(0)
    assert timestamps==sorted(timestamps)
    assert probe(path)['streams'][0]['start_time']=='5.000000'
    source=add_sources([path])[0]
    assert source.pts_origin==5
    # FFmpeg versions encode the last selected frame with 0.1s or 0.3s duration.
    # The playable span must exclude the 5s PTS origin in either case.
    assert 1.8 <= source.duration <= 2.2
    assert timestamps[-1] <= source.duration + .25


def test_portable_bundled_model_is_selected(trained,tmp_path,monkeypatch):
    import shutil,sys
    from PySide6.QtWidgets import QApplication
    from bsae.gui.window import Window
    bundled=tmp_path/'models';bundled.mkdir()
    shutil.copy2(trained[0],bundled/'model.json')
    shutil.copy2(trained[0].parent/'temporal.npz',bundled/'temporal.npz')
    monkeypatch.setattr(sys,'_MEIPASS',str(tmp_path),raising=False)
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    app=QApplication.instance() or QApplication([]);w=Window()
    assert w.model.text()==str(bundled/'model.json')
    assert w.model.isReadOnly() and w.analyze_button.isEnabled()
    w.close();app.processEvents()


def test_acceptance_does_not_autoapprove_predictions(make_video,trained,tmp_path):
    from bsae.acceptance import run_acceptance
    s=session([make_video(['setup','delivery','receive','dead'])])
    analyze(s,trained[0],{},tmp_path/'before.sqlite')
    for e in s.events:review(s,e.id,'APPROVED',confirm_identity=True)
    reference=tmp_path/'reference.json';s.save(reference);before=reference.read_bytes()
    plan=dict(reference_project=str(reference),ground_truth_complete=True,followup_reviewed=True,
        model=str(trained[0]),profile={},cache=str(tmp_path/'fresh.sqlite'),
        candidate_project=str(tmp_path/'candidate.json'),output=str(tmp_path/'acceptance-output'))
    path=tmp_path/'plan.json';path.write_text(json.dumps(plan))
    report=run_acceptance(path,tmp_path/'report.json')
    assert report['status']=='NOT_READY'
    assert report['checks']['review_time_savings']=='NOT_EVALUATED'
    assert report['metrics']['identity_accuracy']==0
    assert all(e.status=='REVIEW_REQUIRED' for e in GameSession.load(plan['candidate_project']).events)
    assert reference.read_bytes()==before


def test_development_package_disables_even_supplied_model(trained,tmp_path,monkeypatch):
    import sys,shutil
    from PySide6.QtWidgets import QApplication
    from bsae.gui.window import Window
    (tmp_path/'build-policy.json').write_text(json.dumps({'kind':'development'}))
    bundled=tmp_path/'models';bundled.mkdir()
    shutil.copy2(trained[0],bundled/'model.json');shutil.copy2(trained[0].parent/'temporal.npz',bundled/'temporal.npz')
    monkeypatch.setattr(sys,'_MEIPASS',str(tmp_path),raising=False)
    app=QApplication.instance() or QApplication([]);w=Window()
    assert not w.analyze_button.isEnabled() and '개발판' in w.availability.text()
    w.close();app.processEvents()


def test_development_media_registration_without_ai(make_video):
    from PySide6.QtWidgets import QApplication
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication([]);w=Window()
    game=session([make_video(['other']*3)])
    w.registered(game)
    w.start.setValue(.2);w.end.setValue(1.5);w.manual()
    w.table.selectRow(0);w.confirm.setChecked(True);w.apply('APPROVED')
    assert w.session.events[0].status=='APPROVED'
    assert w.session.events[0].event_type=='manual_candidate'
    w.dirty=False;w.close();app.processEvents()


def test_asset_gate_separates_development_and_release(tmp_path):
    import hashlib,importlib.util
    spec=importlib.util.spec_from_file_location('asset_gate',Path(__file__).resolve().parents[1]/'packaging'/'validate_assets.py')
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    names=['tools/ffmpeg.exe','tools/ffprobe.exe','tools/tesseract.exe','tools/tessdata/eng.traineddata','licenses/test.txt','corresponding-source/test.txt']
    entries=[]
    for name in names:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'unit-test-fixture-only')
        entries.append(dict(path=name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    (tmp_path/'assets.json').write_text(json.dumps(dict(files=entries)))
    gate.validate(tmp_path,'development')
    with pytest.raises(ValueError,match='models'):gate.validate(tmp_path,'release')
    (tmp_path/'tools'/'ffmpeg.exe').write_bytes(b'changed')
    with pytest.raises(ValueError,match='체크섬'):gate.validate(tmp_path,'development')
