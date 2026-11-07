"""No-media GUI probe for native Windows DPI and unpacked ZIP checks."""
from pathlib import Path
import os
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication,QPushButton
from bsae.core.models import atomic_json


def layout_probe(report):
    from .window import Window
    report=Path(report)
    if report.exists():raise FileExistsError(report)
    app=QApplication.instance() or QApplication([]);window=Window();window.resize(1024,720);window.show();app.processEvents()
    body=window.centralWidget();buttons=[b for b in window.findChildren(QPushButton) if b.isVisibleTo(body)]
    overlaps=[]
    for i,a in enumerate(buttons):
        for b in buttons[i+1:]:
            if a.parentWidget() is b.parentWidget() and a.geometry().intersects(b.geometry()):overlaps.append([a.text(),b.text()])
    small=[b.text() for b in buttons if b.width()<b.minimumSizeHint().width()]
    window.video.setFullScreen(True);app.processEvents();window.video.setFullScreen(False);app.processEvents()
    returned=not window.video.isFullScreen() and window.player.videoOutput() is window.video
    info=window.build_information
    outcome=dict(status='PASS' if not overlaps and not small and returned and window.table.columnCount()==8 else 'FAIL',
        fullscreen_return='PASS' if returned else 'FAIL',scale=os.environ.get('QT_SCALE_FACTOR','1'),device_pixel_ratio=window.devicePixelRatioF(),window=[window.width(),window.height()],
        viewport=[window.work_scroll.viewport().width(),window.work_scroll.viewport().height()],body=[body.width(),body.height()],
        vertical_scroll=window.work_scroll.verticalScrollBar().maximum()>0 or window.review_tools_scroll.verticalScrollBar().maximum()>0,horizontal_scroll=window.work_scroll.horizontalScrollBar().maximum()>0,
        overlapping_buttons=overlaps,truncated_buttons=small,columns=window.table.columnCount(),build=info,
        scope='Blank GUI/geometry only; real video playback and user-PC validation are separate')
    report.parent.mkdir(parents=True,exist_ok=True)
    window.grab().save(str(report.with_suffix('.png')))
    atomic_json(report,outcome);window.dirty=False;window.close();app.processEvents()
    return outcome


def preview_probe(window,timeout_ms=10000):
    """Wait for a decoded frame through the actual review player, then pause."""
    from PySide6.QtCore import QEventLoop,QTimer,QUrl
    from PySide6.QtMultimedia import QMediaPlayer
    loop=QEventLoop();received=[];sink=window.video.videoSink()
    def playback_ready(*args):
        if received and window.player.playbackState()==QMediaPlayer.PlayingState:loop.quit()
    def frame_ready(frame):
        if frame.isValid():received.append([frame.width(),frame.height()]);playback_ready()
    sink.videoFrameChanged.connect(frame_ready);window.player.playbackStateChanged.connect(playback_ready)
    timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit)
    try:
        window.preview();timer.start(timeout_ms)
        if not received or window.player.playbackState()!=QMediaPlayer.PlayingState:loop.exec()
        window.player.pause()
        if not received or window.player.error()!=QMediaPlayer.NoError:
            raise RuntimeError('미리보기 프레임 수신 실패: '+window.player.errorString())
        if window.player.playbackState()!=QMediaPlayer.PausedState:raise RuntimeError('미리보기 일시정지 실패')
        return dict(decoded_frame=received[0],paused=True)
    finally:
        timer.stop();sink.videoFrameChanged.disconnect(frame_ready);window.player.playbackStateChanged.disconnect(playback_ready);window.preview_segments=[];window.player.stop();window.player.setSource(QUrl());QApplication.processEvents()
