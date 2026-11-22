from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class ReviewTimeline(QSlider):
    """A millisecond playhead with a separate, read-only clip range."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.clip_range = None
        self.setAccessibleName('통합 영상 재생 위치')
        self.setSingleStep(1)
        self.setPageStep(1000)
        self.setMinimumHeight(28)

    def set_clip_range(self, clip_range):
        self.clip_range = clip_range
        self.update()

    def slider_geometry(self):
        options = QStyleOptionSlider()
        self.initStyleOption(options)
        groove = self.style().subControlRect(QStyle.CC_Slider, options, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.CC_Slider, options, QStyle.SC_SliderHandle, self)
        return groove.left() + handle.width() // 2, max(1, groove.width() - handle.width()), options.upsideDown

    def move_playhead(self, event):
        left, span, inverted = self.slider_geometry()
        value = QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), round(event.position().x()) - left, span, inverted
        )
        self.setValue(value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setSliderDown(True)
            self.move_playhead(event)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.move_playhead(event)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self.move_playhead(event)
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.clip_range is None or self.maximum() <= self.minimum():
            return
        left, span, inverted = self.slider_geometry()
        start, end = (
            left + QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), value, span, inverted)
            for value in self.clip_range
        )
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().color(QPalette.Highlight), 3))
        painter.drawLine(start, 3, end, 3)
        for x in (start, end):
            painter.drawLine(x, 2, x, 7)
