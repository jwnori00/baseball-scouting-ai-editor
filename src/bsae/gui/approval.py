"""Single review confirmation; optional details show the selected clips."""
from PySide6.QtWidgets import QMessageBox


def confirm_approval(parent,text,details):
    box=QMessageBox(QMessageBox.Question,'선택 클립 승인',text,QMessageBox.Yes|QMessageBox.No,parent)
    box.setDefaultButton(QMessageBox.No);box.setDetailedText(details)
    return box.exec()==QMessageBox.Yes
