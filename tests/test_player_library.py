import json
import os
import subprocess
import sys
from pathlib import Path
from bsae.core.library import Library,data_directory
from bsae.core.models import PlayerIdentity


def test_library_survives_new_process_zip_directory_and_aliases(tmp_path,monkeypatch):
    script="from bsae.core.library import Library;from bsae.core.models import PlayerIdentity;Library().save(PlayerIdentity('이현승','pitcher','두산','48',['Lee Hyun-seung','李賢承'],league='KBO'),favorite=True,latest_project='game.json')"
    subprocess.run([sys.executable,'-c',script],check=True,env=os.environ.copy())
    replacement=tmp_path/'new-portable-zip';replacement.mkdir();monkeypatch.chdir(replacement)
    script="from bsae.core.library import Library;import json;print(json.dumps(Library().records('Lee KBO'),ensure_ascii=True))"
    output=subprocess.check_output([sys.executable,'-c',script],env=os.environ.copy())
    rows=json.loads(output);assert len(rows)==1 and rows[0]['player']['name']=='이현승' and rows[0]['favorite']
    assert rows[0]['latest_project']=='game.json'
    assert data_directory()!=replacement


def test_homonyms_update_backup_restore_preserves_local_edits(tmp_path):
    lib=Library();p=PlayerIdentity('동명이인','batter','팀','9',league='KBO')
    a=lib.save(p);assert lib.save(p)['id']==a['id']
    b=lib.save(p,force_new=True);assert a['id']!=b['id']
    import pytest
    with pytest.raises(ValueError,match='동명이인'):lib.save(p)
    backup=tmp_path/'players.json';lib.backup(backup)
    p.team='이적팀';p.jersey='10';lib.save(p,record_id=a['id'])
    assert lib.restore(backup)==1
    assert lib.get(a['id'])['player']['team']=='이적팀'
    assert len(lib.records())==3
    bad=tmp_path/'bad.json';bad.write_text(json.dumps(dict(schema=1,players=[dict(id='broken',player={})])))
    before=lib.records()
    with pytest.raises(ValueError):lib.restore(bad)
    assert lib.records()==before


def test_gui_library_selection_fills_identity_and_preserves_video():
    from PySide6.QtWidgets import QApplication,QLineEdit,QTableWidget,QPushButton
    from PySide6.QtCore import QTimer
    from bsae.gui.window import Window
    p=PlayerIdentity('이현승','pitcher','두산','48',['Lee Hyun-seung'],league='KBO')
    record=Library().save(p,favorite=True)
    app=QApplication.instance() or QApplication([]);window=Window();window.files.addItem('/keep-source.mp4')
    def choose():
        dialog=app.activeModalWidget();dialog.findChild(QLineEdit).setText('Lee')
        dialog.findChild(QTableWidget).selectRow(0)
        next(b for b in dialog.findChildren(QPushButton) if b.text()=='선택한 선수 불러오기').click()
    QTimer.singleShot(30,choose);window.choose_player()
    identity=window.current_identity()
    assert (identity.name,identity.role,identity.team,identity.jersey,identity.league,identity.aliases)==(p.name,p.role,p.team,p.jersey,p.league,p.aliases)
    assert window.library_id==record['id'] and window.favorite.isChecked()
    assert window.files.item(0).text()=='/keep-source.mp4'
    window.dirty=False;window.close()
