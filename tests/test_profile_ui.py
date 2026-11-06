from pathlib import Path
from PySide6.QtWidgets import QApplication,QDialog,QLineEdit,QPushButton,QInputDialog
from PySide6.QtCore import QTimer,QPoint,Qt
from PySide6.QtTest import QTest
from bsae.core.library import data_directory
from bsae.vision.rules import load_profile


def test_region_editor_save_and_restart_preferences(make_video,monkeypatch):
    from bsae.gui.window import Window
    app=QApplication.instance() or QApplication([]);window=Window()
    source=make_video(['setup','delivery'])
    window.files.addItem(str(source))
    monkeypatch.setattr(QInputDialog,'getDouble',lambda *a,**k:(.5,True))
    errors=[];monkeypatch.setattr(window,'error',errors.append)
    def fill_dialog():
        dialog=app.activeModalWidget()
        assert isinstance(dialog,QDialog)
        dialog.findChild(QLineEdit).setText('새 중계 카메라')
        from bsae.gui.profile_ui import RegionCanvas
        canvas=dialog.findChild(RegionCanvas)
        QTest.mousePress(canvas,Qt.LeftButton,pos=QPoint(100,100));QTest.mouseMove(canvas,QPoint(300,350));QTest.mouseRelease(canvas,Qt.LeftButton,pos=QPoint(300,350))
        button=next(b for b in dialog.findChildren(QPushButton) if b.text()=='사용자 데이터 폴더에 프로필 저장')
        button.click()
        if errors:dialog.reject()
    QTimer.singleShot(50,fill_dialog);window.edit_broadcast_regions()
    assert not errors
    profile=load_profile(window.profile.text())
    assert profile['camera']['pitcher']==[.125,100/450,.375,350/450]
    assert Path(window.profile.text()).parent==data_directory()/'profiles'
    selected=window.profile.text();window.dirty=False;window.close()
    replacement=Window();assert replacement.profile.text()==selected;replacement.dirty=False;replacement.close()
