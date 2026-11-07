"""Compare proposed analysis with saved review; activation is explicit."""
from copy import deepcopy
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QComboBox,QTableWidget,QTableWidgetItem,QPushButton
from bsae.core.rounds import comparison,apply_round,identity_key
from bsae.core.models import GameSession


class RoundsUI:
    def round_done(self,result):
        self.analysis_done(result.session);self.fill_identity(self.session.player);self.load_output_preferences()
        if result.status in ('FAILED','INTERRUPTED'):
            self.stage.setText('재탐색 실패/중단 · 기존 검수와 회차·캐시 보존');self.error(result.error or '탐색을 중단했습니다. 기존 결과와 캐시가 보존됐습니다.');return
        if result.status=='PROPOSED':
            try:
                from bsae.core.library import Library
                row=next(r for r in self.session.analysis_runs if r['id']==result.round_id)
                Library().save(GameSession.from_dict(row['payload']).player,latest_project=self.project_path)
            except Exception as exc:self.error('탐색 결과는 보존됐으나 선수 목록 저장 실패: '+str(exc))
            self.stage.setText('새 탐색 회차 보관 · 기존 검수 유지 · 결과 비교 후 반영하세요')
            self.pending_round_id=result.round_id

    def show_analysis_rounds(self,round_id=None):
        if not self.session or not self.session.analysis_runs:self.error('저장된 탐색 회차가 없습니다.');return
        if self.job and self.job.isRunning():return
        dialog=QDialog(self);dialog.setWindowTitle('탐색 회차 비교·되돌리기');dialog.resize(850,500);layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel('현재 검수는 자동으로 덮어쓰지 않습니다. 전환·복원 전 상태도 별도로 보관합니다.'))
        records=list(self.session.analysis_runs);chooser=QComboBox()
        for r in records:
            player=r['payload']['player'];kind='검수 보관' if r['kind']=='checkpoint' else '탐색'
            state={'SAVED':'검수 보관','PROPOSED':'비교 대기','APPLIED':'결과 반영','FAILED':'실패','INTERRUPTED':'중단'}.get(r['status'],r['status'])
            chooser.addItem(f"{r['created_at']} / {player['name']} / {'투수' if player['role']=='pitcher' else '타자'} / {kind} / {state}")
        layout.addWidget(chooser);table=QTableWidget(0,4);table.setHorizontalHeaderLabels(['플레이','시작','종료','기존 결과와 비교']);table.setSelectionBehavior(QTableWidget.SelectRows);table.setEditTriggers(QTableWidget.NoEditTriggers);layout.addWidget(table)
        message=QLabel();message.setWordWrap(True);layout.addWidget(message)
        add=QPushButton('새로운 플레이만 추가');replace=QPushButton('이 회차로 전환 · 기존 검수 보관');layout.addWidget(add);layout.addWidget(replace)
        current=[]
        def refresh():
            record=records[chooser.currentIndex()];table.setRowCount(0);current.clear()
            failed=record['status'] in ('FAILED','INTERRUPTED');replace.setEnabled(not failed)
            add.setEnabled(not failed and record['kind']=='analysis' and identity_key(self.session.player)==identity_key(GameSession.from_dict(record['payload']).player))
            note=record.get('error','겹치는 후보는 추가하지 않습니다. 경계 변경은 비교 후 회차 전환 또는 수동 검수하세요.')
            analysis=record['payload'].get('analysis',{})
            if not record['payload'].get('events'):note='이 회차에 플레이 후보가 없습니다. 미인식·누락 가능성이 있으니 기존 검수 결과 전환에 주의하세요. '+note
            if analysis.get('support_status')=='UNVERIFIED_CAMERA_TYPE':note='미검증 촬영 유형 · 선수 추적 미지원. '+note
            message.setText(note)
            if failed:return
            current.extend(comparison(self.session,record['id']))
            for i,row in enumerate(current):
                table.insertRow(i)
                for j,value in enumerate([i+1,f"{row['start']:.3f}",f"{row['end']:.3f}",{'new':'새 플레이','existing':'기존 구간과 일치','overlap_changed':'겹침·경계 변경 검수'}[row['state']]]):table.setItem(i,j,QTableWidgetItem(str(value)))
        def apply(mode):
            try:
                record=records[chooser.currentIndex()]
                apply_round(self.session,record['id'],'restore' if record['kind']=='checkpoint' else mode)
                self.fill_identity(self.session.player);self.load_output_preferences();self.refresh();self.dirty=True
                if self.project_path:self.session.save(self.project_path);self.dirty=False
                self.remember_project(self.session,self.project_path);self.stage.setText('회차 반영 완료 · 선수/타석/구간 검수 필요');dialog.accept()
            except Exception as exc:self.error(exc)
        def preview(row,column):
            try:
                record=records[chooser.currentIndex()];candidate=GameSession.from_dict(record['payload']);event=candidate.events[row]
                self.preview_segments=deepcopy(event.segments);self.preview_index=0;self.play_segment()
            except Exception as exc:self.error(exc)
        table.cellDoubleClicked.connect(preview);chooser.currentIndexChanged.connect(refresh);add.clicked.connect(lambda:apply('add_new'));replace.clicked.connect(lambda:apply('replace'))
        chooser.setCurrentIndex(next((i for i,r in enumerate(records) if r['id']==round_id),len(records)-1));refresh();dialog.exec()
