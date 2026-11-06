"""Korean review workbench. Long-running work never runs on the GUI thread."""
from copy import deepcopy
from pathlib import Path
import sys
import json
import threading
from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QLineEdit,QComboBox,QFileDialog,QMessageBox,QListWidget,QTableWidget,QTableWidgetItem,
    QDoubleSpinBox,QProgressBar,QInputDialog,QCheckBox)
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from bsae.core.models import GameSession,PlayerIdentity,PitchEvent,DetectionEvidence
from bsae.core.review import review
from bsae.ingest.media import add_sources


class Job(QThread):
    done=Signal(object)
    error=Signal(str)
    progress=Signal(str,float)

    def __init__(self, operation):
        super().__init__();self.stop=threading.Event();self.operation=operation

    def run(self):
        try:self.done.emit(self.operation(self))
        except Exception as exc:self.error.emit(str(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Baseball Scouting AI Editor — 개발판 / 실제 경기 성능 미평가')
        self.resize(1100,800)
        self.session=None;self.project_path=None;self.job=None;self.dirty=False
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))
        policy=root/'build-policy.json'
        self.development_package=policy.is_file() and json.loads(policy.read_text(encoding='utf-8-sig')).get('kind')=='development'

        self.preview_segments=[];self.preview_index=0
        body=QWidget();self.setCentralWidget(body);layout=QVBoxLayout(body)
        layout.addWidget(QLabel('영상 선택 → 선수 지정 → AI 탐색 → 후보 검수 → MP4 저장'))
        self.files=QListWidget();self.files.setMaximumHeight(95);layout.addWidget(self.files)
        row=QHBoxLayout();layout.addLayout(row)
        project_menu=self.menuBar().addMenu('프로젝트')
        for text,callback in [('새 경기',self.new_session),('프로젝트 열기',self.open_project),('프로젝트 저장',self.save_project)]:
            project_menu.addAction(text,callback)
        for text,callback in [('영상 선택',self.add_files),('위로',lambda:self.move(-1)),('아래로',lambda:self.move(1)),('삭제',self.remove_file)]:
            self.button(row,text,callback)
        if self.development_package or not getattr(sys,'frozen',False):
            diagnostic_menu=self.menuBar().addMenu('개발판 시험')
            diagnostic_menu.addAction('영상·검수·출력 시험용 경기 등록 (AI 아님)',self.register_game)
        row=QHBoxLayout();layout.addLayout(row)
        self.role=QComboBox();self.role.addItems(['투수','타자']);row.addWidget(self.role)
        self.name=QLineEdit();self.name.setPlaceholderText('선수 이름');row.addWidget(self.name)
        self.team=QLineEdit();self.team.setPlaceholderText('팀');row.addWidget(self.team)
        self.jersey=QLineEdit();self.jersey.setPlaceholderText('등번호');row.addWidget(self.jersey)
        self.alias=QLineEdit();self.alias.setPlaceholderText('별칭 (쉼표 구분)');self.alias.hide()
        self.date=QLineEdit();self.date.setPlaceholderText('YYYY-MM-DD');row.addWidget(self.date)
        self.model=QLineEdit();self.profile=QLineEdit()
        self.model_settings=QWidget();settings_layout=QVBoxLayout(self.model_settings)
        for text,edit in [('모델 manifest',self.model),('중계 OCR 설정',self.profile)]:
            row=QHBoxLayout();settings_layout.addLayout(row);row.addWidget(QLabel(text));row.addWidget(edit)
            self.button(row,'선택',lambda checked=False,e=edit:self.choose_json(e))
        layout.addWidget(self.model_settings);self.model_settings.hide()
        if not getattr(sys,'frozen',False):
            action=diagnostic_menu.addAction('개발자 모델 설정 표시');action.setCheckable(True)
            action.toggled.connect(self.model_settings.setVisible)
        self.availability=QLabel('자동 분석 BLOCKED: 야구 동작 학습 모델을 선택하세요. 동봉 모델 없음.')
        layout.addWidget(self.availability);self.model.textChanged.connect(self.check_model)
        row=QHBoxLayout();layout.addLayout(row)
        self.analyze_button=self.button(row,'AI 자동 분석 시작',self.start_analysis);self.analyze_button.setEnabled(False)
        self.button(row,'중단',self.cancel)
        self.progress=QProgressBar();row.addWidget(self.progress)
        self.stage=QLabel('대기');layout.addWidget(self.stage)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['번호','이닝','시작','종료','검수'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.selected);layout.addWidget(self.table)
        self.evidence=QLabel();self.evidence.setWordWrap(True);self.evidence.setMaximumHeight(110);layout.addWidget(self.evidence);self.evidence.hide()
        self.video=QVideoWidget();self.video.setMinimumHeight(180);layout.addWidget(self.video)
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.player.setAudioOutput(self.audio);self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.preview_position)
        self.player.mediaStatusChanged.connect(self.preview_status)
        row=QHBoxLayout();layout.addLayout(row)
        self.start=QDoubleSpinBox();self.end=QDoubleSpinBox()
        for label,spin in [('통합 시작(초)',self.start),('종료(초)',self.end)]:
            spin.setRange(0,9999999);spin.setDecimals(3);row.addWidget(QLabel(label));row.addWidget(spin)
        self.confirm=QCheckBox('대상 선수 확인');row.addWidget(self.confirm)
        self.button(row,'후보 재생',self.preview);self.button(row,'일시정지',self.player.pause)
        row=QHBoxLayout();layout.addLayout(row)
        self.button(row,'수정·검수 승인',lambda:self.apply('APPROVED'))
        self.button(row,'제외',lambda:self.apply('EXCLUDED'))
        self.button(row,'판단 근거',lambda:self.evidence.setVisible(not self.evidence.isVisible()))
        project_menu.addAction('선택 후보 재검수',lambda:self.apply('REVIEW_REQUIRED'))
        self.button(row,'누락 후보 보조 추가',self.manual)
        self.button(row,'선택 타석 그룹 확정',self.confirm_plate)
        self.output_mode=QComboBox();self.output_mode.addItems(['전체 MP4','투구별 MP4','확정 타석별 MP4']);row.addWidget(self.output_mode)
        self.button(row,'MP4 저장',self.start_export)
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))
        if (root/'models'/'model.json').is_file():
            self.model.setText(str(root/'models'/'model.json'))
        if (root/'models'/'broadcast.json').is_file():
            self.profile.setText(str(root/'models'/'broadcast.json'))
        if getattr(sys,'frozen',False):
            self.model.setReadOnly(True)
        self.check_model()


    def button(self,row,text,callback):
        b=QPushButton(text);b.clicked.connect(callback);row.addWidget(b);return b

    def error(self,text):
        QMessageBox.warning(self,'확인 필요',str(text))

    def choose_json(self,edit):
        path,_=QFileDialog.getOpenFileName(self,'JSON 선택','','JSON (*.json)')
        if path:edit.setText(path)

    def check_model(self):
        if self.development_package:
            self.availability.setText('개발판 — 검증된 AI 모델 없음. 자동 분석 비활성화. 영상 등록·검수·출력 시험 가능.')
            self.analyze_button.setEnabled(False)
            return
        if not self.model.text().strip():
            self.availability.setText('AI 자동 탐색 준비 안 됨 — 검증된 야구 모델이 아직 없습니다.')
            self.analyze_button.setEnabled(False)
            return
        try:
            from bsae.vision.model import TemporalModel
            model=TemporalModel(self.model.text())
            self.availability.setText('실험용 모델 로드 가능 — 성능 '+model.info.get('validation','NOT_EVALUATED'))
            self.analyze_button.setEnabled(not (self.job and self.job.isRunning()))
        except Exception as exc:
            self.availability.setText('AI 모델을 불러오지 못했습니다. 자동 탐색이 중지되었습니다.');self.availability.setToolTip(str(exc));self.analyze_button.setEnabled(False)

    def discard(self):
        return not self.dirty or QMessageBox.question(self,'저장하지 않은 변경','저장하지 않은 변경을 버릴까요?')==QMessageBox.Yes

    def new_session(self):
        if self.job and self.job.isRunning():return
        if not self.discard():return
        self.player.stop();self.preview_segments=[]
        self.session=None;self.project_path=None;self.dirty=False
        self.files.clear();self.refresh()

    def add_files(self):
        if self.job and self.job.isRunning():return
        if self.session:
            self.error('기존 프로젝트의 원본 변경은 새 프로젝트에서 진행하세요.');return
        paths,_=QFileDialog.getOpenFileNames(self,'로컬 원본 선택','','Video (*.mp4 *.mkv *.mov *.avi *.ts);;All (*)')
        for path in paths:
            if path not in [self.files.item(i).text() for i in range(self.files.count())]:self.files.addItem(path)

    def move(self,delta):
        if self.session:return
        i=self.files.currentRow();j=i+delta
        if i>=0 and 0<=j<self.files.count():self.files.insertItem(j,self.files.takeItem(i));self.files.setCurrentRow(j)

    def remove_file(self):
        if not self.session:self.files.takeItem(self.files.currentRow())

    def launch(self,operation,done):
        if self.job and self.job.isRunning():return
        self.job=Job(operation)
        self.job.progress.connect(lambda stage,v:(self.stage.setText(stage),self.progress.setValue(int(v*100))))
        self.job.error.connect(self.error);self.job.done.connect(done)
        self.job.finished.connect(self.check_model);self.analyze_button.setEnabled(False);self.job.start()

    def register_game(self):
        if self.job and self.job.isRunning():return
        if self.session:self.error('새 경기 버튼으로 새 프로젝트를 시작하세요.');return
        if not self.name.text().strip() or not self.files.count():self.error('선수 이름과 영상 파일을 입력하세요.');return
        paths=[self.files.item(i).text() for i in range(self.files.count())]
        identity=PlayerIdentity(self.name.text().strip(),'pitcher' if self.role.currentIndex()==0 else 'batter',self.team.text(),self.jersey.text())
        game_date=self.date.text()
        self.launch(lambda job:GameSession(identity.name,identity,add_sources(paths),game_date=game_date),self.registered)

    def registered(self,session):
        self.session=session;self.dirty=True;self.refresh()
        self.start.setValue(0);self.end.setValue(min(10,sum(s.duration for s in session.sources)))
        self.stage.setText('경기 등록 완료 — 개발판 검수·출력 시험. AI 탐색 결과가 아닙니다.')

    def start_analysis(self):
        if self.development_package:self.error('개발판에는 검증된 AI 모델이 없어 자동 분석이 비활성화되어 있습니다.');return
        if self.job and self.job.isRunning():return
        if not self.name.text().strip() or not self.files.count():self.error('선수 이름과 원본 영상을 입력하세요.');return
        try:profile=json.loads(Path(self.profile.text()).read_text(encoding='utf-8'))
        except Exception as exc:self.error(exc);return
        path,_=QFileDialog.getSaveFileName(self,'분석 프로젝트 저장 위치','','JSON (*.json)')
        if not path:return
        if Path(path).exists() and (not self.project_path or Path(path)!=Path(self.project_path)):
            self.error('새 프로젝트 파일명을 선택하세요.');return
        paths=[self.files.item(i).text() for i in range(self.files.count())]
        identity=PlayerIdentity(self.name.text().strip(),'pitcher' if self.role.currentIndex()==0 else 'batter',self.team.text(),self.jersey.text(),[s.strip() for s in self.alias.text().split(',') if s.strip()])
        existing=deepcopy(self.session) if self.session else None
        manifest=self.model.text();game_date=self.date.text()
        def operation(job):
            from bsae.vision.pipeline import analyze
            session=existing or GameSession(identity.name,identity,add_sources(paths),game_date=game_date)
            if existing and any(getattr(identity,k)!=getattr(existing.player,k) for k in ('name','role','team','jersey','aliases')):
                raise ValueError('다른 선수 분석은 프로젝트를 새로 열어 진행하세요.')
            session.save(path)
            analyze(session,manifest,profile,str(Path(path).with_suffix('.sqlite')),job.stop,job.progress.emit)
            session.save(path);return session
        self.project_path=path
        self.launch(operation,self.analysis_done)

    def analysis_done(self,session):
        self.session=session;self.dirty=False;self.refresh()

    def cancel(self):
        if self.job:self.job.stop.set();self.stage.setText('중단 요청: 현재 처리 단위 종료 후 캐시 보존')

    def refresh(self):
        self.table.setRowCount(0)
        if not self.session:return
        for i,e in enumerate(self.session.events):
            self.table.insertRow(i)
            for j,value in enumerate([e.number,e.inning or '?',f'{e.timeline_start:.3f}',f'{e.timeline_end:.3f}',{'REVIEW_REQUIRED':'검수 필요','APPROVED':'승인','EXCLUDED':'제외'}[e.status]]):
                self.table.setItem(i,j,QTableWidgetItem(str(value)))

    def selected_event(self):
        i=self.table.currentRow()
        if self.session and 0<=i<len(self.session.events):return self.session.events[i]
        raise ValueError('후보를 선택하세요')

    def selected(self):
        try:e=self.selected_event()
        except ValueError:return
        self.start.setValue(e.timeline_start);self.end.setValue(e.timeline_end);self.confirm.setChecked(False)
        self.evidence.setText('\n'.join(e.warnings)+'\n'+ '; '.join(x.kind+': '+x.value[:150] for x in e.evidence))

    def apply(self,status):
        try:
            e=self.selected_event();review(self.session,e.id,status,start=self.start.value(),end=self.end.value(),confirm_identity=self.confirm.isChecked(),note='GUI 검수')
            self.dirty=True;self.refresh()
        except Exception as exc:self.error(exc)

    def manual(self):
        if not self.session:return
        try:
            a,b=self.start.value(),self.end.value()
            if b<=a:raise ValueError('시작·종료를 입력하세요')
            e=PitchEvent(self.session.id,self.session.split(a,b),a,b,number=len(self.session.events)+1,event_type='manual_candidate',evidence=[DetectionEvidence('manual','사용자 보조 추가',a)])
            self.session.events.append(e);self.session.validate();self.dirty=True;self.refresh()
        except Exception as exc:self.error(exc)

    def confirm_plate(self):
        try:
            e=self.selected_event()
            if not e.plate_id:raise ValueError('타석 그룹 없음: CLI/프로젝트에서 그룹을 지정하세요')
            pa=next(p for p in self.session.appearances if p.id==e.plate_id)
            if QMessageBox.question(self,'타석 그룹 검수',f'이 그룹의 {len(pa.event_ids)}개 투구가 한 타석인지 확인했나요?')==QMessageBox.Yes:
                pa.confirmed=True;self.dirty=True
        except Exception as exc:self.error(exc)

    def preview(self):
        try:
            self.preview_segments=self.session.split(self.start.value(),self.end.value());self.preview_index=0;self.play_segment()
        except Exception as exc:self.error(exc)

    def play_segment(self):
        seg=self.preview_segments[self.preview_index]
        source=next(s for s in self.session.sources if s.id==seg.source_id)
        self.player.setSource(QUrl.fromLocalFile(source.path))

    def preview_status(self,status):
        if status==QMediaPlayer.LoadedMedia and self.preview_segments:
            self.player.setPosition(int(self.preview_segments[self.preview_index].start*1000));self.player.play()
        elif status==QMediaPlayer.EndOfMedia and self.preview_segments:self.advance_preview()

    def preview_position(self,position):
        if self.preview_segments and position>=self.preview_segments[self.preview_index].end*1000:self.advance_preview()

    def advance_preview(self):
        self.player.pause()
        if self.preview_index+1<len(self.preview_segments):self.preview_index+=1;self.play_segment()
        else:self.preview_segments=[]

    def save_project(self):
        if not self.session:return
        path,_=QFileDialog.getSaveFileName(self,'프로젝트 저장',self.project_path or '','JSON (*.json)')
        if path:
            try:self.session.save(path);self.project_path=path;self.dirty=False
            except Exception as exc:self.error(exc)

    def open_project(self):
        if self.job and self.job.isRunning():return
        if not self.discard():return
        path,_=QFileDialog.getOpenFileName(self,'프로젝트 열기','','JSON (*.json)')
        if not path:return
        try:
            self.session=GameSession.load(path);self.project_path=path;self.files.clear()
            for s in self.session.sources:self.files.addItem(s.path)
            p=self.session.player
            self.name.setText(p.name);self.team.setText(p.team);self.jersey.setText(p.jersey);self.alias.setText(', '.join(p.aliases));self.date.setText(self.session.game_date)
            self.role.setCurrentIndex(0 if p.role=='pitcher' else 1);self.dirty=False;self.refresh()
        except Exception as exc:self.error(exc)

    def start_export(self):
        if not self.session or (self.job and self.job.isRunning()):return
        parent=QFileDialog.getExistingDirectory(self,'출력 상위 폴더')
        if not parent:return
        name,ok=QInputDialog.getText(self,'새 출력 폴더','새 폴더 이름 (기존 폴더 불가)')
        if not ok or not name:return
        if Path(name).name!=name or name in ('.','..'):self.error('폴더 이름만 입력하세요');return
        from bsae.export.render import export
        session=deepcopy(self.session);mode=['all','pitch','plate'][self.output_mode.currentIndex()]
        self.launch(lambda job:export(session,Path(parent)/name,mode,progress=lambda v:job.progress.emit('승인 영상 출력·검증',v),stop=job.stop),lambda path:self.stage.setText('검증 완료: '+str(path)))

    def closeEvent(self,event):
        if self.job and self.job.isRunning():
            self.cancel();self.error('작업 중단 후 창을 닫으세요.');event.ignore();return
        if not self.discard():event.ignore();return
        self.player.stop();event.accept()
