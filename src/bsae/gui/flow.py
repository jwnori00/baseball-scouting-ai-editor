"""Composition around a native grid; no Python QLayout virtual ownership."""
from PySide6.QtWidgets import QGridLayout


class ToolGrid:
    def __init__(self):
        self.layout=QGridLayout();self.widgets=[];self.columns=3
        self.layout.setContentsMargins(0,0,0,0);self.layout.setSpacing(6)
    def addWidget(self,widget):
        self.widgets.append(widget);i=len(self.widgets)-1
        self.layout.addWidget(widget,i//self.columns,i%self.columns)
    def reflow(self,width):
        widest=max((w.sizeHint().width() for w in self.widgets),default=1)
        columns=max(1,min(len(self.widgets) or 1,width//max(1,widest+self.layout.spacing())))
        if columns==self.columns:return
        self.columns=columns
        for i,widget in enumerate(self.widgets):self.layout.addWidget(widget,i//columns,i%columns)
