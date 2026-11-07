from copy import deepcopy
import pytest
from bsae.core.models import GameSession,PlayerIdentity,VideoSource,PitchEvent,PlateAppearance
from bsae.core.review import review_many,set_innings


def project():
    s=GameSession('Bulk review',PlayerIdentity('이현승','pitcher','두산','48'),[VideoSource('/synthetic',20,'synthetic')])
    s.events=[PitchEvent(s.id,s.split(a,a+3),a,a+3,number=i+1) for i,a in enumerate((0,5,10))]
    pa=PlateAppearance([e.id for e in s.events],None,None,confirmed=True)
    for e in s.events:e.plate_id=pa.id
    s.appearances=[pa]
    return s


def test_bulk_atomic_identity_and_boundaries():
    s=project();ids=[e.id for e in s.events[:2]];before=deepcopy(s)
    with pytest.raises(ValueError,match='선수'):review_many(s,ids)
    assert s==before
    assert review_many(s,ids,confirm_identity=True)==2
    assert [e.status for e in s.events]==['APPROVED','APPROVED','REVIEW_REQUIRED']
    assert [(e.timeline_start,e.timeline_end) for e in s.events]==[(0,3),(5,8),(10,13)]
    assert all(e.history[-1].action=='APPROVED' for e in s.events[:2])
    s.events[2].event_type='replay';before=deepcopy(s)
    with pytest.raises(ValueError,match='리플레이'):review_many(s,[e.id for e in s.events],confirm_identity=True)
    assert s==before


def test_inning_save_reload_partial_group_and_clear(tmp_path):
    s=project();ids=[e.id for e in s.events]
    assert set_innings(s,ids,'9회 초')==3
    assert s.appearances[0].inning=='9초' and not s.appearances[0].confirmed
    set_innings(s,ids[:1],'10말')
    assert s.appearances[0].inning is None
    p=tmp_path/'project.json';s.save(p);loaded=GameSession.load(p)
    assert [e.inning for e in loaded.events]==['10말','9초','9초']
    assert loaded.events[0].history[-1].after==dict(inning='10말')
    before=deepcopy(s)
    with pytest.raises(ValueError):set_innings(s,ids,'0회')
    assert s==before
    set_innings(s,ids,'?');assert all(e.inning is None for e in s.events)


def test_gui_multiple_rows_approve_and_edit_inning(monkeypatch):
    from PySide6.QtWidgets import QApplication,QMessageBox,QInputDialog
    from PySide6.QtCore import QItemSelectionModel
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication([]);window=Window()
    window.session=project();window.fill_identity(window.session.player);window.refresh()
    def select():
        model=window.table.selectionModel()
        for row in (0,1):model.select(window.table.model().index(row,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
    select();assert len(window.selected_event_ids())==2
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.Yes)
    errors=[];monkeypatch.setattr(window,'error',errors.append)
    window.approve_selected();select()
    monkeypatch.setattr(QInputDialog,'getText',lambda *a,**k:('9초',True))
    window.edit_inning()
    assert not errors
    assert [e.status for e in window.session.events]==['APPROVED','APPROVED','REVIEW_REQUIRED']
    assert [e.inning for e in window.session.events]==['9초','9초',None]
    window.dirty=False;window.close()
