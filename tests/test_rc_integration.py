from pathlib import Path
import ast,importlib.util,json,os,subprocess,sys
from importlib.metadata import version
import pytest
from bsae.core.models import GameSession,PlayerIdentity,PitchEvent,VideoSource
from bsae.core.review import review
from bsae.core.summary import review_counts
from bsae.version import APP_VERSION
from bsae.vision.rules import VERSION,load_profile

ROOT=Path(__file__).resolve().parents[1]


def test_counts_describe_active_round_and_overlap():
    s=GameSession('Counts',PlayerIdentity('Player'),[VideoSource('/synthetic',10,'x')])
    s.events=[PitchEvent(s.id,s.split(t,t+1),t,t+1) for t in (0,2,4)]
    s.events[0].identity_status='TARGET_CONFIRMED';s.events[0].manual_identity_confirmed=True;s.events[0].status='APPROVED'
    s.events[2].identity_status='OTHER_PLAYER';s.events[2].status='EXCLUDED'
    assert review_counts(s)==dict(total=3,automatic=1,manual=1,overlap=1,unknown=1,other=1,approved=1,excluded=1)


def test_single_version_and_generated_build_provenance(tmp_path):
    assert version('baseball-scouting-ai-editor')==APP_VERSION
    spec=importlib.util.spec_from_file_location('build_policy',ROOT/'packaging/write_build_policy.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assets=tmp_path/'assets';assets.mkdir();evidence=tmp_path/'evidence'
    value=module.create(assets,'rules-preview',evidence)
    assert value['version']==APP_VERSION and value['engine']==VERSION and len(value['commit'])==40
    assert json.loads((evidence/'build-info.json').read_text(encoding='utf-8'))==value
    assert APP_VERSION in (evidence/'CLIENT_MANUAL.txt').read_text(encoding='utf-8-sig')
    ast.parse((evidence/'windows-version.txt').read_text(encoding='utf-8'))


@pytest.mark.parametrize('scale',['1','1.5','2'])
def test_rc_window_dpi_fullscreen_and_process_shutdown(scale,tmp_path):
    report=tmp_path/f'layout-{scale}.json'
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_SCALE_FACTOR=scale)
    result=subprocess.run([sys.executable,str(ROOT/'packaging/entry.py'),'--layout-probe',str(report)],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    data=json.loads(report.read_text(encoding='utf-8'));assert data['status']=='PASS' and data['fullscreen_return']=='PASS'
    assert data['columns']==8 and data['window']==[1024,720]
    assert not data['overlapping_buttons'] and not data['truncated_buttons']
    assert report.with_suffix('.png').is_file()


def test_acceptance_uses_same_rules_workflow_without_approving(make_video,tmp_path):
    from bsae.ingest.media import add_sources
    from bsae.acceptance import run_acceptance
    s=GameSession('Rules acceptance',PlayerIdentity('Unknown'),add_sources([make_video(['setup']*4)]))
    s.events=[PitchEvent(s.id,s.split(0,1),0,1)];review(s,s.events[0].id,'APPROVED',confirm_identity=True)
    reference=tmp_path/'reference.json';s.save(reference);before=reference.read_bytes()
    profile=load_profile();profile['regions']={}
    plan=dict(reference_project=str(reference),engine=VERSION,profile=profile,automatic_profile=False,
              ground_truth_complete=True,followup_reviewed=True,cache=str(tmp_path/'cache.sqlite'),candidate_project=str(tmp_path/'candidate.json'),output=str(tmp_path/'output'))
    path=tmp_path/'plan.json';path.write_text(json.dumps(plan))
    report=run_acceptance(path,tmp_path/'report.json');candidate=GameSession.load(plan['candidate_project'])
    assert report['matches_gui_engine'] and report['execution_path']=='bsae.vision.workflow.analyze_for_review'
    assert all(e.status!='APPROVED' for e in candidate.events)
    assert report['release_qualification']=='NOT_GRANTED_BY_THIS_TEST' and reference.read_bytes()==before
    plan['cache']=plan['candidate_project'];path.write_text(json.dumps(plan))
    with pytest.raises(ValueError,match='경로'):run_acceptance(path,tmp_path/'other-report.json')


@pytest.mark.parametrize('role',['pitcher','batter'])
@pytest.mark.parametrize('marker',['replay','archive'])
def test_historical_caption_cannot_confirm_current_player(role,marker):
    from bsae.vision.rules import Identity
    p=PlayerIdentity('Player',role,'TEAM','12');i=Identity(p,load_profile())
    observed={role+'_name':'Player',role+'_team':'TEAM',role+'_jersey':'12'}
    assert i.update(0,observed)['state']=='target'
    assert i.update(2,dict(observed,**{marker:'REPLAY' if marker=='replay' else '자료화면'}))['state']!='target'
    assert i.update(3,{})['state']!='target'


def test_archived_caption_is_not_a_live_plate_group():
    from bsae.core.models import DetectionEvidence
    from bsae.vision.rules import group_plates
    s=GameSession('Archive',PlayerIdentity('Player','batter'),[VideoSource('/synthetic',10,'x')])
    e=PitchEvent(s.id,s.split(0,2),0,2,broadcast_status='ARCHIVE_SUSPECTED',evidence=[DetectionEvidence('ocr:batter_name','Player',0)])
    assert group_plates([e])==[] and e.plate_id is None


def test_unrelated_logo_in_replay_roi_does_not_invalidate_pitcher():
    from bsae.vision.rules import Identity
    p=PlayerIdentity('Player','pitcher','TEAM');i=Identity(p,load_profile())
    assert i.update(0,dict(pitcher_name='Player',pitcher_team='TEAM',replay='SPORTS LIVE'))['state']=='target'
    assert i.update(1,{})['state']=='target'


def test_actual_review_preview_decodes_and_pauses(make_video,tmp_path):
    from PySide6.QtWidgets import QApplication
    from bsae.gui.window import Window
    from bsae.gui.diagnostics import preview_probe
    from bsae.ingest.media import add_sources,run
    raw=make_video(['setup','delivery','receive']);video=tmp_path/'한글 영상 Martínez.mp4'
    run('ffmpeg',['-v','error','-i',raw,'-c:v','libx264',video])
    app=QApplication.instance() or QApplication([]);w=Window();w.show()
    w.registered(GameSession('Preview',PlayerIdentity('Player'),add_sources([video])))
    w.start.setValue(0);w.end.setValue(2.5)
    result=preview_probe(w)
    assert result['decoded_frame']==[160,90] and result['paused']
    assert w.player.source().isEmpty()
    renamed=video.with_name('released.mp4');video.rename(renamed);renamed.rename(video)
    w.dirty=False;w.close();app.processEvents()
