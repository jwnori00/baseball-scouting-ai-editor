"""Player-library UI; no video or player data is sent to a server."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLineEdit,QTableWidget,QTableWidgetItem,QPushButton,QFileDialog,QInputDialog
from bsae.core.models import PlayerIdentity
from bsae.core.library import Library


class LibraryUI:
    def current_identity(self):
        return PlayerIdentity(self.name.text().strip(),'pitcher' if self.role.currentIndex()==0 else 'batter',self.team.text().strip(),self.jersey.text().strip(),[s.strip() for s in self.alias.text().split(',') if s.strip()],league=self.league.currentText())

    def fill_identity(self,p):
        self.name.setText(p.name);self.team.setText(p.team);self.jersey.setText(p.jersey)
        self.alias.setText(', '.join(p.aliases));self.league.setCurrentText(p.league)
        self.role.setCurrentIndex(0 if p.role=='pitcher' else 1)

    def save_library(self,force_new=False):
        try:
            row=Library().save(self.current_identity(),record_id=None if force_new else self.library_id,favorite=self.favorite.isChecked(),force_new=force_new)
            self.library_id=row['id'];self.stage.setText('선수 정보 저장 완료: '+row['player']['name'])
        except Exception as exc:self.error(exc)

    def remember_project(self,session,path):
        try:
            record_id=self.library_id
            if record_id:
                old=Library().get(record_id)['player']
                if any(old.get(k,'')!=getattr(session.player,k) for k in ('name','role','team','jersey','league')):record_id=None
            row=Library().save(session.player,record_id=record_id,favorite=self.favorite.isChecked() if record_id or self.favorite.isChecked() else None,latest_project=path or '')
            self.library_id=row['id']
        except Exception as exc:self.error('프로젝트는 보존됐지만 선수 목록 저장 실패: '+str(exc))

    def choose_player(self):
        if self.job and self.job.isRunning():return
        if self.session:self.begin_target_change()
        dialog=QDialog(self);dialog.setWindowTitle('선수 목록 · 이름/별칭/팀/리그 검색');dialog.resize(800,450)
        layout=QVBoxLayout(dialog);query=QLineEdit();query.setPlaceholderText('이름, 다른 언어 표기, 팀, 리그, 등번호');layout.addWidget(query)
        table=QTableWidget(0,6);table.setHorizontalHeaderLabels(['선수','리그','팀','등번호','구분','즐겨찾기'])
        table.setSelectionBehavior(QTableWidget.SelectRows);table.setSelectionMode(QTableWidget.SingleSelection);table.setEditTriggers(QTableWidget.NoEditTriggers);layout.addWidget(table)
        records=[]
        def refresh():
            try:
                records[:]=Library().records(query.text());table.setRowCount(len(records))
                for i,r in enumerate(records):
                    p=r['player']
                    for j,v in enumerate([p['name'],p.get('league',''),p['team'],p['jersey'],'투수' if p['role']=='pitcher' else '타자','★' if r['favorite'] else '']):table.setItem(i,j,QTableWidgetItem(v))
            except Exception as exc:self.error(exc)
        def choose():
            i=table.currentRow()
            if 0<=i<len(records):
                r=records[i];self.library_id=r['id'];self.fill_identity(PlayerIdentity(**r['player']));self.favorite.setChecked(r['favorite']);self.update_active_context();dialog.accept()
        query.textChanged.connect(refresh);button=QPushButton('선택한 선수 불러오기');button.clicked.connect(choose);layout.addWidget(button);table.cellDoubleClicked.connect(lambda *args:choose());refresh();dialog.exec()

    def backup_players(self):
        path,_=QFileDialog.getSaveFileName(self,'선수 목록 백업','','JSON (*.json)')
        if path:
            try:Library().backup(path);self.stage.setText('선수 백업 저장: '+path)
            except Exception as exc:self.error(exc)

    def restore_players(self):
        path,_=QFileDialog.getOpenFileName(self,'선수 목록 복원','','JSON (*.json)')
        if path:
            try:self.stage.setText(f'선수 {Library().restore(path)}개 복원 · 기존 수정 기록 보존')
            except Exception as exc:self.error(exc)

    def open_recent_player_project(self):
        if not self.library_id:self.error('먼저 라이브러리에서 선수를 선택하세요.');return
        try:
            from pathlib import Path
            from bsae.core.models import GameSession
            path=Library().get(self.library_id)['latest_project']
            if not path or not Path(path).is_file():raise ValueError('최근 프로젝트가 없거나 파일이 이동됐습니다.')
            if self.job and self.job.isRunning():return
            if not self.discard():return
            self.session=GameSession.load(path);self.changing_target=False;self.project_path=path;self.files.clear()
            for source in self.session.sources:self.files.addItem(source.path)
            self.fill_identity(self.session.player);self.date.setText(self.session.game_date);self.dirty=False;self.refresh();self.load_output_preferences()
        except Exception as exc:self.error(exc)
