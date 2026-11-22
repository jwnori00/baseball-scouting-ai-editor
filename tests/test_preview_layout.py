from PySide6.QtCore import QPoint, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from bsae.core.models import GameSession, PitchEvent, PlayerIdentity
from bsae.gui.window import Window
from bsae.ingest.media import add_sources


def wait_until(predicate, timeout=4000):
    for _ in range(timeout // 20):
        if predicate():
            return
        QTest.qWait(20)
    assert predicate()


def test_review_timeline_playback_and_in_place_edit(make_video, monkeypatch):
    app = QApplication.instance() or QApplication([])
    paths = [make_video(['setup'] * 4, name=f'review-{i}.mkv') for i in range(2)]
    session = GameSession('Review', PlayerIdentity('투수', 'pitcher'), add_sources(paths))
    session.events = [
        PitchEvent(session.id, session.split(1.125, 3.5), 1.125, 3.5, number=i+1)
        for i in range(40)
    ]
    window = Window()
    window.resize(1280, 900)
    window.session = session
    window.fill_identity(session.player)
    window.refresh()
    window.show()
    app.processEvents()
    try:
        assert window.review_splitter.orientation() == Qt.Horizontal
        assert window.review_splitter.widget(0) is window.table
        assert window.review_splitter.widget(1) is window.preview_panel
        assert window.player.videoOutput() is window.video
        window.table.setCurrentCell(22, 0)
        window.table.verticalScrollBar().setValue(19)
        scroll = window.table.verticalScrollBar().value()
        ids = [e.id for e in window.visible_events]
        unchanged_item = window.table.item(21, 3)
        wait_until(lambda: window.pending_seek is None)
        wait_until(lambda: window.video.videoSink().videoFrame().isValid())
        assert window.player.position() == 1125
        assert window.timeline.clip_range == (1125, 3500)
        assert '1.125초 / 전체 길이: 8.000초' in window.timeline_time.text()

        window.preview()
        wait_until(lambda: window.player.position() > 1125)
        assert window.table.isVisible() and window.table.rowCount() == 40
        assert window.table.geometry().right() < window.preview_panel.geometry().left()
        window.pause_preview()
        assert window.player.playbackState() == QMediaPlayer.PausedState
        paused = window.player.position()
        QTest.qWait(100)
        assert window.timeline.value() == paused
        assert f'{paused/1000:.3f}초' in window.timeline_time.text()

        timeline = window.timeline
        left, span, _ = timeline.slider_geometry()
        point = lambda fraction: QPoint(left + round(span * fraction), timeline.height() // 2)
        QTest.mouseClick(timeline, Qt.LeftButton, pos=point(.25))
        wait_until(lambda: window.pending_seek is None)
        assert abs(window.player.position() - 2000) < 30
        QTest.mousePress(timeline, Qt.LeftButton, pos=point(.25))
        QTest.mouseMove(timeline, point(.75))
        assert abs(timeline.value() - 6000) < 30
        QTest.mouseRelease(timeline, Qt.LeftButton, pos=point(.75))
        wait_until(lambda: window.pending_seek is None)
        assert window.preview_source.id == session.sources[1].id
        assert abs(window.player.position() - 2000) < 30
        assert window.player.playbackState() == QMediaPlayer.PausedState
        wait_until(lambda: 1_750_000 <= window.video.videoSink().videoFrame().startTime() <= 2_250_000)

        window.resume_preview()
        wait_until(lambda: window.player.playbackState() == QMediaPlayer.PlayingState)
        QTest.mouseClick(timeline, Qt.LeftButton, pos=point(.25))
        wait_until(lambda: window.pending_seek is None and window.player.playbackState() == QMediaPlayer.PlayingState)
        assert window.preview_source.id == session.sources[0].id
        window.pause_preview()

        QTest.keyClick(window.start, Qt.Key_Up)
        QTest.keyClick(window.end, Qt.Key_Down)
        assert (window.start.value(), window.end.value()) == (1.625, 3.0)
        assert timeline.clip_range == (1625, 3000)
        window.end.setValue(8.5)
        assert '전체 길이' in window.range_feedback.text()
        window.apply('APPROVED')
        assert session.events[22].status == 'REVIEW_REQUIRED'
        window.start.setValue(3.1)
        window.end.setValue(3.0)
        assert '종료는 시작보다 뒤' in window.range_feedback.text()
        window.start.setValue(-0.5)
        assert '0초 이상' in window.range_feedback.text()
        window.start.setValue(3.625)
        window.end.setValue(4.5)
        window.preview()
        wait_until(lambda: not window.preview_segments)
        assert window.preview_source.id == session.sources[1].id
        assert window.timeline.value() == 4500
        assert window.player.position() == 500

        def unexpected_dialog(*args, **kwargs):
            raise AssertionError('Single approval opened a dialog')

        monkeypatch.setattr(QMessageBox, 'question', unexpected_dialog)
        monkeypatch.setattr(window, 'error', unexpected_dialog)
        window.confirm.setChecked(True)
        window.apply('APPROVED')
        event = session.events[22]
        assert (event.timeline_start, event.timeline_end) == (3.625, 4.5)
        assert event.status == event.history[-1].action == 'APPROVED'
        assert event.identity_status == 'IDENTITY_UNKNOWN'
        assert event.manual_identity_confirmed and event.pitcher_id == session.player.id
        assert '승인 완료' in window.stage.text()
        assert window.table.currentRow() == 22
        assert window.table.verticalScrollBar().value() == scroll
        assert [e.id for e in window.visible_events] == ids
        assert window.table.item(21, 3) is unchanged_item
        assert window.table.item(22, 3).text() == '3.625'
        window.approve_selected()
        assert len(session.events[22].history) == 2
    finally:
        window.dirty = False
        window.close()
        app.processEvents()
