from copy import deepcopy
import pytest
from bsae.core.models import GameSession,PlayerIdentity,VideoSource,PitchEvent
from bsae.core.review import assign_plate,name_plate,split_plate,merge_previous_plate,review_many


def game():
    s=GameSession('Pitcher opponents',PlayerIdentity('투수','pitcher'),[VideoSource('/synthetic',30,'synthetic')])
    s.events=[PitchEvent(s.id,s.split(i*5,i*5+3),i*5,i*5+3,number=i+1) for i in range(4)]
    return s


def test_selected_pitcher_plates_preserve_review_and_roundtrip(tmp_path):
    s=game();ids=[e.id for e in s.events]
    review_many(s,ids,confirm_identity=True);before=deepcopy(s.events)
    assign_plate(s,ids[:2],'타자A');assign_plate(s,ids[2:],'타자B')
    assert len(s.appearances)==2 and all(e.pitcher_id==s.player.id and e.batter_id is None for e in s.events)
    assert [e.status for e in s.events]==[e.status for e in before]
    split_plate(s,ids[1]);assert len(s.appearances)==3 and s.appearances[1].batter_name=='타자A'
    merge_previous_plate(s,ids[1]);assert len(s.appearances)==2
    name_plate(s,ids[0],'수정 타자');assert s.player.name=='투수'
    p=tmp_path/'project.json';s.save(p);loaded=GameSession.load(p)
    assert [pa.batter_name for pa in loaded.appearances]==['수정 타자','타자B']


def test_nonconsecutive_selection_and_failed_review_are_atomic():
    s=game();ids=[e.id for e in s.events];before=deepcopy(s)
    with pytest.raises(ValueError,match='연속'):assign_plate(s,[ids[0],ids[2]],'타자')
    assert s==before
    with pytest.raises(ValueError):review_many(s,ids[:2],confirm_identity=True,ranges={ids[1]:(5,99)})
    assert s==before
    assign_plate(s,ids,'타자');assign_plate(s,ids[1:3],'새 타자')
    assert [len(p.event_ids) for p in s.appearances]==[1,2,1]
    assert len({i for p in s.appearances for i in p.event_ids})==4


def test_gui_partial_selection_apply_preserves_unselected(monkeypatch):
    from PySide6.QtWidgets import QApplication,QMessageBox
    from PySide6.QtCore import QItemSelectionModel
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication([]);w=Window();w.session=game();w.fill_identity(w.session.player);w.refresh()
    w.table.setCurrentCell(0,0)
    w.table.selectionModel().select(w.table.model().index(1,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
    assert len(w.selected_event_ids())==2
    w.start.setValue(.2);w.end.setValue(2.8);w.confirm.setChecked(True)
    errors=[];monkeypatch.setattr(w,'error',errors.append);monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.Yes)
    original=deepcopy(w.session.events[2:]);w.apply('APPROVED')
    assert not errors
    assert [e.status for e in w.session.events]==['APPROVED','APPROVED','REVIEW_REQUIRED','REVIEW_REQUIRED']
    assert [(e.timeline_start,e.timeline_end) for e in w.session.events[:2]]==[(.2,2.8),(5,8)]
    assert w.session.events[2:]==original
    w.dirty=False;w.close()


def test_pitcher_grouped_plate_mp4_output(make_video,tmp_path):
    from bsae.ingest.media import add_sources
    from bsae.export.render import export
    s=GameSession('Pitcher output',PlayerIdentity('투수','pitcher'),add_sources([make_video(['setup']*8)]))
    s.events=[PitchEvent(s.id,s.split(a,a+1),a,a+1) for a in (0,2,4)]
    ids=[e.id for e in s.events];review_many(s,ids,confirm_identity=True)
    assign_plate(s,ids[:2],'상대 타자 A');assign_plate(s,ids[2:],'상대 타자 B')
    for pa in s.appearances:pa.confirmed=True
    export(s,tmp_path/'output',mode='plate')
    assert len(list((tmp_path/'output').glob('plate_*.mp4')))==2
