from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent,QMouseEvent
from PySide6.QtCore import QEvent,QPointF
from PySide6.QtWidgets import QApplication,QPushButton
from bsae.gui.window import Window


def test_review_preview_resizes_and_returns_from_fullscreen():
    app=QApplication.instance() or QApplication([])
    window=Window();window.show();app.processEvents()
    assert window.review_splitter.widget(0) is window.table
    assert window.review_splitter.widget(1) is window.video
    assert window.video.height()>window.table.height()
    window.review_splitter.setSizes([200,250]);app.processEvents()
    assert window.table.height()>=100 and window.video.height()>=180
    next(b for b in window.findChildren(QPushButton) if b.text()=='미리보기 크게 보기').click()
    app.processEvents();assert window.video.isFullScreen()
    window.video.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier))
    app.processEvents();assert not window.video.isFullScreen()
    event=QMouseEvent(QEvent.MouseButtonDblClick,QPointF(10,10),QPointF(10,10),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
    window.video.mouseDoubleClickEvent(event);app.processEvents();assert window.video.isFullScreen()
    window.video.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier))
    assert window.player.videoOutput() is window.video
    window.dirty=False;window.close();app.processEvents()
