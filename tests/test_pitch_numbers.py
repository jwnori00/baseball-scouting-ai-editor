from copy import deepcopy
import pytest
from bsae.core.models import GameSession,PlayerIdentity,VideoSource,PitchEvent
from bsae.core.review import set_pitch_numbers,review_many
from bsae.core.rounds import run_round,apply_round


def project():
    s=GameSession('Number labels',PlayerIdentity('투수'),[VideoSource('/synthetic',30,'synthetic')])
    s.events=[PitchEvent(s.id,s.split(a,a+2),a,a+2,number=i+1) for i,a in enumerate((0,5))]
    review_many(s,[e.id for e in s.events],confirm_identity=True)
    return s


def test_edit_one_number_preserves_other_review_and_reload(tmp_path):
    s=project();other=deepcopy(s.events[1]);before=deepcopy(s.events[0])
    assert set_pitch_numbers(s,{s.events[0].id:35})==1
    assert s.events[1]==other and s.events[0].status==before.status and s.events[0].segments==before.segments
    p=tmp_path/'game.json';s.save(p);s=GameSession.load(p);assert s.events[0].number==35
    for value in (0,-1,1.5,True,100000):
        original=deepcopy(s)
        with pytest.raises(ValueError):set_pitch_numbers(s,{s.events[0].id:value})
        assert s==original


def test_new_analysis_candidates_never_reset_manual_numbers(tmp_path):
    s=project();set_pitch_numbers(s,{s.events[0].id:35,s.events[1].id:36})
    def analyze(work,*args):work.events=[PitchEvent(work.id,work.split(10,12),10,12,number=1)]
    result=run_round(s,deepcopy(s.player),{},tmp_path/'cache',analyzer=analyze)
    apply_round(result.session,result.round_id,'add_new')
    assert [e.number for e in result.session.events]==[35,36,37]


def test_gui_number_edit_changes_current_row_only(monkeypatch):
    from PySide6.QtWidgets import QApplication,QInputDialog
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication([]);w=Window();w.session=project();w.fill_identity(w.session.player);w.refresh();w.table.selectRow(0)
    errors=[];monkeypatch.setattr(w,'error',errors.append);monkeypatch.setattr(QInputDialog,'getInt',lambda *a,**k:(35,True))
    w.edit_pitch_number();assert not errors and [e.number for e in w.session.events]==[35,2]
    assert all(e.status=='APPROVED' for e in w.session.events)
    w.dirty=False;w.close()
