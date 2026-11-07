from copy import deepcopy
from PySide6.QtWidgets import QApplication,QPushButton,QComboBox,QFileDialog
from PySide6.QtCore import QTimer
from bsae.gui.window import Window
from bsae.core.models import GameSession,PlayerIdentity,PitchEvent
from bsae.core.review import review
from bsae.core.rounds import run_round
from bsae.ingest.media import add_sources


def test_output_dialog_and_project_restore(make_video,tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);window=Window();source=make_video(['setup','delivery'])
    window.registered(GameSession('Output dialog',PlayerIdentity('Synthetic'),add_sources([source])))
    errors=[];monkeypatch.setattr(window,'error',errors.append)
    def choose():
        dialog=app.activeModalWidget()
        try:
            combo=next(c for c in dialog.findChildren(QComboBox) if c.count()==6);combo.setCurrentIndex(3)
            next(b for b in dialog.findChildren(QPushButton) if b.text()=='출력 설정 반영').click()
        finally:
            if dialog.isVisible():dialog.reject()
    QTimer.singleShot(50,choose);window.edit_output_preferences();assert not errors
    assert window.session.output_settings['aspect']=='9:16'
    path=tmp_path/'project.json';monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(path),'JSON'));window.save_project()
    assert GameSession.load(path).output_settings==window.session.output_settings
    window.dirty=False;window.close()


def test_round_comparison_add_button_preserves_review(make_video,tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);window=Window();source=make_video(['setup']*12)
    s=GameSession('Comparison',PlayerIdentity('Synthetic','pitcher','T','1'),add_sources([source]));s.events=[PitchEvent(s.id,s.split(0,2),0,2,number=1)];review(s,s.events[0].id,'APPROVED',confirm_identity=True)
    old=deepcopy(s.events[0])
    def analyzer(work,*args):work.events=[PitchEvent(work.id,work.split(a,b),a,b) for a,b in [(0,2),(5,7)]]
    result=run_round(s,deepcopy(s.player),{},tmp_path/'cache',analyzer=analyzer)
    window.session=result.session;window.fill_identity(window.session.player);window.project_path=str(tmp_path/'rounds.json');window.refresh()
    errors=[];monkeypatch.setattr(window,'error',errors.append)
    def add():
        dialog=app.activeModalWidget()
        try:next(b for b in dialog.findChildren(QPushButton) if b.text()=='새로운 플레이만 추가').click()
        finally:
            if dialog.isVisible():dialog.reject()
    QTimer.singleShot(50,add);window.show_analysis_rounds(result.round_id)
    assert not errors and len(window.session.events)==2 and window.session.events[0]==old
    assert window.session.events[1].status=='REVIEW_REQUIRED'
    assert len(GameSession.load(window.project_path).events)==2
    window.dirty=False;window.close()
