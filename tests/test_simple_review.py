from copy import deepcopy
from pathlib import Path
import pytest
from bsae.core.models import GameSession,PlayerIdentity,VideoSource,PitchEvent
from bsae.core.bulk import approve_clips,approval_warnings
from bsae.core.review import assign_plate,classify_event


def game():
    s=GameSession('Simple review',PlayerIdentity('선수','pitcher','팀','12'),[VideoSource('/synthetic',20,'x')])
    s.events=[PitchEvent(s.id,s.split(t,t+2),t,t+2,number=i+1) for i,t in enumerate((0,4,8))]
    return s


@pytest.mark.parametrize('count',[1,3])
def test_one_approval_records_identity_without_changing_automatic_state(count):
    s=game();old=deepcopy(s);ids=[e.id for e in s.events[:count]]
    with pytest.raises(ValueError,match='사용자'):approve_clips(s,ids)
    assert s==old
    approve_clips(s,ids,user_approved=True)
    assert all(e.status=='APPROVED' and e.manual_identity_confirmed and e.identity_status=='IDENTITY_UNKNOWN' and e.pitcher_id==s.player.id for e in s.events[:count])
    assert s.events[count:]==old.events[count:]
    assert all(any(h.action=='MANUAL_IDENTITY_CONFIRMED' and h.timestamp for h in e.history) for e in s.events[:count])


def test_bad_batch_rolls_back_and_classification_requires_explicit_correction():
    s=game();ids=[e.id for e in s.events];before=deepcopy(s)
    with pytest.raises(ValueError,match='2번'):approve_clips(s,ids,user_approved=True,ranges={ids[1]:(4,99)})
    assert s==before
    s.events[0].identity_status='OTHER_PLAYER';before=deepcopy(s)
    assert approval_warnings(s,ids)
    with pytest.raises(ValueError,match='재분류'):approve_clips(s,ids,user_approved=True)
    assert s==before
    classify_event(s,ids[0],'pitch_candidate');approve_clips(s,ids[:1],user_approved=True)
    assert s.events[0].identity_status=='OTHER_PLAYER' and s.events[0].manual_identity_confirmed
    classify_event(s,ids[1],'replay');before=deepcopy(s)
    with pytest.raises(ValueError):approve_clips(s,ids,user_approved=True)
    assert s==before


def test_plate_confirmation_is_part_of_approval_not_guessed():
    s=game();ids=[e.id for e in s.events];assign_plate(s,ids[:2])
    approve_clips(s,ids[:1],user_approved=True,confirm_groups=True);assert not s.appearances[0].confirmed
    untouched=deepcopy(s.events[0]);approve_clips(s,ids[1:2],user_approved=True,confirm_groups=True)
    assert s.appearances[0].confirmed and s.events[0]==untouched
    assert s.events[2].plate_id is None


@pytest.mark.parametrize('mode,files',[('all',1),('pitch',2),('plate',1)])
def test_approved_unknowns_export_without_second_identity_check(make_video,tmp_path,mode,files):
    from bsae.ingest.media import add_sources
    from bsae.export.render import export
    s=GameSession('Output',PlayerIdentity('선수'),add_sources([make_video(['setup']*8)]))
    s.events=[PitchEvent(s.id,s.split(t,t+1),t,t+1) for t in (0,2,4)]
    ids=[e.id for e in s.events[:2]];assign_plate(s,ids)
    s.events[2].event_type='replay';s.events[2].broadcast_status='REPLAY_SUSPECTED';s.events[2].status='EXCLUDED'
    approve_clips(s,ids,user_approved=True,confirm_groups=True)
    out=export(s,tmp_path/mode,mode);assert len(list(out.glob('*.mp4')))==files
    path=tmp_path/'project.json';s.save(path);restored=GameSession.load(path)
    assert restored.events==s.events and restored.appearances==s.appearances


def test_unexported_pickoff_does_not_block_selected_output(make_video,tmp_path):
    from bsae.ingest.media import add_sources
    from bsae.export.render import export
    s=GameSession('Output subset',PlayerIdentity('선수'),add_sources([make_video(['setup']*5)]))
    s.events=[PitchEvent(s.id,s.split(0,1),0,1),PitchEvent(s.id,s.split(2,3),2,3,event_type='pickoff',status='APPROVED',broadcast_status='REPLAY_SUSPECTED')]
    approve_clips(s,[s.events[0].id],user_approved=True)
    assert list(export(s,tmp_path/'output').glob('*.mp4'))


def test_gui_single_button_and_project_identity_are_stable(monkeypatch):
    from PySide6.QtWidgets import QApplication,QPushButton
    from PySide6.QtCore import QItemSelectionModel
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication([]);w=Window();s=game();w.registered(s);original=s.player.id
    assert w.name.isReadOnly()
    w.name.setText('다른 입력');w.table.setCurrentCell(0,0)
    w.table.selectionModel().select(w.table.model().index(1,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
    monkeypatch.setattr(w,'ask_approval',lambda *a:True);w.apply('APPROVED')
    assert [e.status for e in s.events]==['APPROVED','APPROVED','REVIEW_REQUIRED']
    assert all(e.pitcher_id==original for e in s.events[:2]) and s.player.name=='선수'
    assert not hasattr(w,'confirm')
    labels=[b.text() for b in w.findChildren(QPushButton) if b.isVisibleTo(w)]
    assert '선택 후보 선수 확인' not in labels and '수정 저장·검수 완료' not in labels
    w.begin_target_change();assert not w.name.isReadOnly()
    w.dirty=False;w.close();app.processEvents()


def test_export_window_combines_choices_without_mandatory_file_dialog(make_video,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QLineEdit,QPushButton,QFileDialog
    from PySide6.QtCore import QTimer
    from bsae.gui.window import Window
    from bsae.ingest.media import add_sources
    app=QApplication.instance() or QApplication([]);w=Window()
    s=GameSession('Output dialog',PlayerIdentity('선수'),add_sources([make_video(['setup']*4)]));s.events=[PitchEvent(s.id,s.split(0,1),0,1)]
    approve_clips(s,[s.events[0].id],user_approved=True);w.registered(s)
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a:pytest.fail('Should only open on explicit browse'))
    def choose():
        d=app.activeModalWidget();d.findChild(QLineEdit,'export-folder').setText(str(tmp_path));d.findChild(QLineEdit,'export-name').setText('approved-video');d.findChild(QPushButton,'export-save').click()
    QTimer.singleShot(50,choose);result=w.choose_export()
    assert result['destination']==tmp_path/'approved-video' and result['mode']=='all'
    w.dirty=False;w.close();app.processEvents()


def test_revoke_and_reapprove_preserve_history_and_replay_correction():
    from bsae.core.review import review_many
    s=game();event_id=s.events[0].id
    approve_clips(s,[event_id],user_approved=True)
    original=deepcopy(s.events[0].history)
    review_many(s,[event_id],'REVIEW_REQUIRED')
    assert s.events[0].status=='REVIEW_REQUIRED' and s.events[0].history[:len(original)]==original
    approve_clips(s,[event_id],user_approved=True,ranges={event_id:(0.1,2.1)})
    assert s.events[0].status=='APPROVED' and s.events[0].timeline_start==0.1
    classify_event(s,event_id,'replay')
    assert approval_warnings(s,[event_id])
    classify_event(s,event_id,'pitch_candidate')
    approve_clips(s,[event_id],user_approved=True)
    assert s.events[0].status=='APPROVED' and s.events[0].identity_status=='IDENTITY_UNKNOWN'
    assert sum(h.action=='APPROVED' for h in s.events[0].history)==3
