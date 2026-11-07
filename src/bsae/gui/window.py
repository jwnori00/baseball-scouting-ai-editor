"""Korean review workbench. Long-running work never runs on the GUI thread."""
from copy import deepcopy
from pathlib import Path
import sys
import json
import threading
from PySide6.QtCore import QThread, Signal, QUrl, Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QLineEdit,QComboBox,QFileDialog,QMessageBox,QListWidget,QTableWidget,QTableWidgetItem,
    QDoubleSpinBox,QProgressBar,QInputDialog,QCheckBox,QSplitter,QSizePolicy,QScrollArea)
from PySide6.QtMultimedia import QMediaPlayer,QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from bsae.core.models import GameSession,PlayerIdentity,PitchEvent,DetectionEvidence
from bsae.core.review import review
from .library_ui import LibraryUI
from .profile_ui import ProfileUI
from .rounds_ui import RoundsUI
from .output_ui import OutputUI
from .flow import ToolGrid
from bsae.ingest.media import add_sources


class ReviewVideoWidget(QVideoWidget):
    """Keep the review player in place while allowing an enlarged native view."""
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.setFullScreen(not self.isFullScreen());event.accept()
        else:super().mouseDoubleClickEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape and self.isFullScreen():
            self.setFullScreen(False);event.accept()
        else:super().keyPressEvent(event)


class Job(QThread):
    done=Signal(object)
    error=Signal(str)
    progress=Signal(str,float)
    preflight=Signal(object)

    def __init__(self, operation):
        super().__init__();self.stop=threading.Event();self.operation=operation

    def ask_preflight(self,assessment):
        from bsae.vision.pipeline import Cancelled
        self.preflight_reply=threading.Event();self.preflight_continue=False;self.preflight.emit(assessment)
        while not self.preflight_reply.wait(.1):
            if self.stop.is_set():raise Cancelled('사전 진단 중 사용자가 중단했습니다')
        if not self.preflight_continue:raise Cancelled('신원 미확정 후보 탐색을 시작하지 않았습니다')

    def run(self):
        try:self.done.emit(self.operation(self))
        except Exception as exc:self.error.emit(str(exc))


class Window(LibraryUI,ProfileUI,RoundsUI,OutputUI,QMainWindow):
    def __init__(self):
        super().__init__()
        from bsae.version import build_info,BUILD_LABEL
        self.build_information=build_info()
        self.setWindowTitle('Baseball Scouting AI Editor — '+BUILD_LABEL+' · '+self.build_information['version'])
        self.resize(1280,900)
        self.session=None;self.project_path=None;self.job=None;self.dirty=False;self.tool_rows=[]
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))
        self.development_package=self.build_information['kind']=='development'

        self.preview_segments=[];self.preview_index=0
        root_body=QWidget();self.setCentralWidget(root_body);outer=QVBoxLayout(root_body)
        body=QWidget();self.work_scroll=QScrollArea();self.work_scroll.setWidgetResizable(True);self.work_scroll.setFrameShape(QScrollArea.NoFrame);self.work_scroll.setWidget(body)
        self.work_scroll.setMinimumHeight(150);self.work_scroll.setMaximumHeight(300);outer.addWidget(self.work_scroll);layout=QVBoxLayout(body)
        layout.addWidget(QLabel('경기영상 불러오기 → 분석 선수 선택 → 선택 선수 플레이 찾기 → 후보 검수 → MP4 저장'))
        self.files=QListWidget();self.files.setMaximumHeight(55);layout.addWidget(self.files)
        row=QHBoxLayout();layout.addLayout(row)
        project_menu=self.menuBar().addMenu('프로젝트');self.project_menu=project_menu
        project_menu.addAction('검증용 독립 정답 작업 시작',self.register_game)
        for text,callback in [('새 경기',self.new_session),('프로젝트 열기',self.open_project),('프로젝트 저장',self.save_project)]:
            project_menu.addAction(text,callback)
        for text,callback in [('경기영상 불러오기',self.add_files),('위로',lambda:self.move(-1)),('아래로',lambda:self.move(1)),('삭제',self.remove_file)]:
            self.button(row,text,callback)
        if self.development_package or not getattr(sys,'frozen',False):
            diagnostic_menu=self.menuBar().addMenu('개발판 시험')
            diagnostic_menu.addAction('영상·검수·출력 시험용 경기 등록 (AI 아님)',self.register_game)
        row=QHBoxLayout();layout.addLayout(row)
        self.role=QComboBox();self.role.addItems(['투수','타자']);row.addWidget(self.role)
        self.name=QLineEdit();self.name.setPlaceholderText('선수 이름');row.addWidget(self.name)
        self.team=QLineEdit();self.team.setPlaceholderText('팀');row.addWidget(self.team)
        self.jersey=QLineEdit();self.jersey.setPlaceholderText('등번호');row.addWidget(self.jersey)
        self.alias=QLineEdit();self.alias.setPlaceholderText('다른 언어 이름·별칭 (쉼표 구분)')
        self.date=QLineEdit();self.date.setPlaceholderText('YYYY-MM-DD');row.addWidget(self.date)
        library_row=QHBoxLayout();layout.addLayout(library_row)
        from bsae.core.library import LEAGUES
        self.league=QComboBox();self.league.addItems(LEAGUES);library_row.addWidget(QLabel('리그'));library_row.addWidget(self.league)
        library_row.addWidget(self.alias);self.favorite=QCheckBox('즐겨찾기');library_row.addWidget(self.favorite)
        self.library_id=None
        self.auto_profile=True
        from bsae.core.output_settings import default_output_settings
        self.pending_output_settings=default_output_settings()
        self.button(library_row,'선수 불러오기',self.choose_player);self.button(library_row,'선수 정보 저장/수정',self.save_library)
        library_menu=project_menu.addMenu('선수 목록')
        library_menu.addAction('동명이인·별도 선수로 새 등록',lambda:self.save_library(True))
        library_menu.addAction('선택 선수의 최근 프로젝트 열기',self.open_recent_player_project)
        library_menu.addAction('선수 정보 백업',self.backup_players);library_menu.addAction('선수 정보 복원',self.restore_players)
        self.model=QLineEdit();self.profile=QLineEdit()
        self.model_settings=QWidget();settings_layout=QVBoxLayout(self.model_settings)
        for text,edit in [('모델 manifest',self.model),('중계 OCR 설정',self.profile)]:
            row=QHBoxLayout();settings_layout.addLayout(row);row.addWidget(QLabel(text));row.addWidget(edit)
            self.button(row,'선택',lambda checked=False,e=edit:self.choose_json(e))
        layout.addWidget(self.model_settings);self.model_settings.hide()
        if not getattr(sys,'frozen',False):
            action=diagnostic_menu.addAction('개발자 모델 설정 표시');action.setCheckable(True)
            action.toggled.connect(self.model_settings.setVisible)
        self.availability=QLabel('자동 탐색 준비 상태 확인 중')
        layout.addWidget(self.availability);self.model.textChanged.connect(self.check_model)
        row=QHBoxLayout();layout.addLayout(row)
        self.analyze_button=self.button(row,'선택 선수 플레이 찾기',self.start_analysis);self.analyze_button.setEnabled(False)
        self.button(row,'중단',self.cancel)
        self.progress=QProgressBar();self.progress.setFormat('%p% · 작업 진행률');row.addWidget(self.progress)
        self.stage=QLabel('대기');self.stage.setWordWrap(True);layout.addWidget(self.stage)
        self.review_filter=QComboBox();self.review_filter.addItems(['기본: 타자는 목표 근거만 / 투수는 후보','전체 플레이 후보','기존 다른 선수·OCR 오류','리플레이','누락 의심 구간','목표 선수 근거 있음','타자명 일치 근거·신원 미확정','신원 근거 충돌','다른 타자 이름 근거·검수'])
        self.review_filter.currentIndexChanged.connect(self.refresh);outer.addWidget(self.review_filter)
        self.analysis_summary=QLabel();self.analysis_summary.setWordWrap(True);outer.addWidget(self.analysis_summary)
        self.visible_events=[]
        self.active_context=QLabel();self.active_context.setWordWrap(True);outer.addWidget(self.active_context)
        self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['투구 번호','타석','이닝','시작','종료','검수','타자','신원'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows);self.table.setSelectionMode(QTableWidget.ExtendedSelection);self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.selected)
        self.review_splitter=QSplitter(Qt.Vertical)
        self.review_splitter.setChildrenCollapsible(False);self.review_splitter.setHandleWidth(9)
        self.table.setMinimumHeight(100);self.review_splitter.addWidget(self.table)
        outer.addWidget(self.review_splitter,1)
        bottom=QWidget();self.review_tools_scroll=QScrollArea();self.review_tools_scroll.setWidgetResizable(True);self.review_tools_scroll.setFrameShape(QScrollArea.NoFrame);self.review_tools_scroll.setWidget(bottom)
        self.review_tools_scroll.setMinimumHeight(110);self.review_tools_scroll.setMaximumHeight(220);outer.addWidget(self.review_tools_scroll)
        layout=QVBoxLayout(bottom)
        self.table.cellDoubleClicked.connect(lambda row,column:self.edit_pitch_number() if column==0 else self.edit_inning() if column==2 else self.edit_plate_batter() if column==6 else None)
        bulk_row=ToolGrid();self.tool_rows.append(bulk_row);layout.addLayout(bulk_row.layout)
        self.button(bulk_row,'표 전체 선택',self.table.selectAll)
        self.button(bulk_row,'선택 플레이 일괄 검수 완료',self.approve_selected)
        self.button(bulk_row,'선택 플레이 이닝 수정',self.edit_inning)
        self.button(bulk_row,'투구 번호 수정',self.edit_pitch_number)
        self.button(bulk_row,'선택 후보 선수 확인',self.confirm_selected_players)
        bulk_row.addWidget(QLabel('Ctrl/Shift 다중 선택 · 번호/이닝 칸 더블클릭'))
        self.advanced_review=QWidget();advanced_layout=QVBoxLayout(self.advanced_review);advanced_layout.setContentsMargins(0,0,0,0)
        toggle=self.button(bulk_row,'타석 편집 펼치기',lambda:self.advanced_review.setVisible(not self.advanced_review.isVisible()))
        self.advanced_review.hide();layout.addWidget(self.advanced_review)
        plate_row=ToolGrid();self.tool_rows.append(plate_row);advanced_layout.addLayout(plate_row.layout)
        self.button(plate_row,'선택 투구를 한 타석으로',self.assign_selected_plate)
        self.button(plate_row,'선택 플레이부터 새 타석',lambda:self.edit_plate(False))
        self.button(plate_row,'앞 타석과 합치기',lambda:self.edit_plate(True))
        self.button(plate_row,'타석 타자명 수정',self.edit_plate_batter)
        self.plate_summary=QLabel();plate_row.addWidget(self.plate_summary)
        self.evidence=QLabel();self.evidence.setWordWrap(True);self.evidence.setMaximumHeight(110);layout.addWidget(self.evidence);self.evidence.hide()
        self.video=ReviewVideoWidget();self.video.setMinimumHeight(180)
        self.video.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Ignored)
        self.video.setAspectRatioMode(Qt.KeepAspectRatio)
        self.video.setFocusPolicy(Qt.StrongFocus)
        self.video.fullScreenChanged.connect(lambda full:self.video.setFocus() if full else None)
        self.review_splitter.addWidget(self.video)
        self.review_splitter.setStretchFactor(0,1);self.review_splitter.setStretchFactor(1,3)
        self.review_splitter.setSizes([130,390])
        self.player=QMediaPlayer(self);self.audio=QAudioOutput(self);self.player.setAudioOutput(self.audio);self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self.preview_position)
        self.player.mediaStatusChanged.connect(self.preview_status)
        row=ToolGrid();self.tool_rows.append(row);layout.addLayout(row.layout)
        self.start=QDoubleSpinBox();self.end=QDoubleSpinBox()
        for label,spin in [('클립 시작(초)',self.start),('클립 종료(초)',self.end)]:
            spin.setRange(0,9999999);spin.setDecimals(3);spin.setMaximumWidth(140);row.addWidget(QLabel(label));row.addWidget(spin)
        self.confirm=QCheckBox('대상 선수 확인');row.addWidget(self.confirm)
        self.button(row,'플레이 후보 재생',self.preview);self.button(row,'일시정지',self.player.pause)
        self.button(row,'미리보기 크게 보기',lambda:self.video.setFullScreen(True))
        self.video.setToolTip('목록과 영상 사이 경계선을 끌어 크기 조절 · 더블클릭: 전체 화면 · Esc: 돌아오기')
        row=ToolGrid();self.tool_rows.append(row);layout.addLayout(row.layout)
        self.button(row,'수정 저장·검수 완료',lambda:self.apply('APPROVED'))
        self.button(row,'제외',lambda:self.apply('EXCLUDED'))
        self.button(row,'판단 근거',lambda:self.evidence.setVisible(not self.evidence.isVisible()))
        project_menu.addAction('선택 후보 재검수',lambda:self.apply('REVIEW_REQUIRED'))
        self.button(row,'누락 플레이 보조 추가',self.manual)
        self.button(row,'타석 구성 확인 완료',self.confirm_plate)
        self.output_mode=QComboBox();self.output_mode.addItems(['승인 클립 합본','투구별 개별 MP4','타석별 개별 MP4']);row.addWidget(self.output_mode)
        self.auto_frame_action=project_menu.addAction('MP4 검은 여백 자동 제거·확대')
        self.auto_frame_action.setCheckable(True);self.auto_frame_action.setChecked(False)
        self.auto_frame_action.toggled.connect(self.change_auto_frame)
        self.auto_frame_action.setToolTip('승인 구간 전체를 검사하고 검은 테두리를 제거합니다. 원본 구도를 유지하려면 해제하세요.')
        self.button(row,'출력 설정',self.edit_output_preferences)
        self.button(row,'MP4 저장',self.start_export)
        project_menu.addAction('탐색 회차 비교·되돌리기',lambda:self.show_analysis_rounds())
        project_menu.addAction('탐색 결과 CSV·JSON 저장',self.save_diagnostics)
        project_menu.addAction('타자명 자막 근거 보기',self.show_batter_captions)
        project_menu.addAction('근거 없는 자동 타석 정리 · 검수 보관',self.cleanup_automatic_plates)
        project_menu.addAction('선택 플레이부터 새 타석',lambda:self.edit_plate(False))
        project_menu.addAction('앞 타석과 합치기',lambda:self.edit_plate(True))
        for title,kind in [('선택 플레이를 투구로 분류','pitch_candidate'),('선택 플레이를 견제로 분류','pickoff'),('선택 플레이를 리플레이로 분류','replay')]:
            project_menu.addAction(title,lambda checked=False,k=kind:self.classify_selected(k))
        self.pickoff_option=project_menu.addAction('승인한 견제도 출력');self.pickoff_option.setCheckable(True)
        root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))
        broadcast_menu=project_menu.addMenu('경기영상 분석 설정')
        broadcast_menu.addAction('자동 설정으로 되돌리기',self.enable_profile_detection)
        broadcast_menu.addAction('화면 인식 보정',self.edit_broadcast_regions)
        broadcast_menu.addAction('저장된 영상 분석 설정 불러오기',self.open_broadcast_profile)
        advanced_menu=broadcast_menu.addMenu('고급 분석 설정')
        self.broadcast_group=QActionGroup(self);self.broadcast_group.setExclusive(True)
        for label,filename in [('다중 중계 학습 시험 · 선수 확인 필수','multi-broadcast-scene-v1.json'),('LMB 기존 실험 설정','lmb-telemetry-v1.json'),('KBO MBC 구도 시험 · 선수 확인 필수','kbo-mbc-centerfield-v1.json')]:
            action=advanced_menu.addAction(label);action.setData(filename);action.setCheckable(True);self.broadcast_group.addAction(action)
            action.setChecked(filename=='lmb-telemetry-v1.json')
            action.triggered.connect(lambda checked=False,p=root/'profiles'/filename:self.select_broadcast(p))
        help_menu=self.menuBar().addMenu('도움말');help_menu.addAction('프로그램 정보·빌드 확인',self.show_build_info)
        self.profile.setText(str(root/'profiles'/'lmb-telemetry-v1.json'))
        if (root/'models'/'model.json').is_file():
            self.model.setText(str(root/'models'/'model.json'))
        if (root/'models'/'broadcast.json').is_file():
            self.profile.setText(str(root/'models'/'broadcast.json'))
        if getattr(sys,'frozen',False):
            self.model.setReadOnly(True)
        self.name.textChanged.connect(self.update_active_context);self.role.currentIndexChanged.connect(self.update_active_context)
        project_menu.addAction('현재 검수 선수 정보로 입력 복원',lambda:self.fill_identity(self.session.player) if self.session else None)
        self.restore_profile_preferences()
        self.check_model();self.refresh()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        for row in getattr(self,'tool_rows',[]):row.reflow(max(200,self.width()-48))

    def button(self,row,text,callback):
        b=QPushButton(text);b.clicked.connect(callback);row.addWidget(b);return b

    def error(self,text):
        QMessageBox.warning(self,'확인 필요',str(text))

    def choose_json(self,edit):
        path,_=QFileDialog.getOpenFileName(self,'JSON 선택','','JSON (*.json)')
        if path:edit.setText(path)

    def enable_profile_detection(self):
        if self.job and self.job.isRunning():return
        self.auto_profile=True;self.check_model();self.save_profile_preferences();self.stage.setText('다음 분석에서 중계·문자 영역 자동 탐색을 시도합니다. 미확정 시 사용자 보정이 필요합니다.')

    def select_broadcast(self,path):
        if self.job and self.job.isRunning():
            self.error('분석이 끝난 뒤 중계 유형을 변경하세요.');return
        self.auto_profile=False;self.profile.setText(str(path));self.check_model();self.save_profile_preferences()

    def show_build_info(self):
        info=self.build_information
        QMessageBox.information(self,'프로그램 정보',f"버전: {info['version']}\n배포 종류: {info['kind']}\n실행 엔진: {info['runtime_engine']}\n빌드 엔진: {info['engine']}\nGit 커밋: {info['commit']}\n빌드 일시(UTC): {info['built_at']}\n\n배포 후보판(RC): 전체 경기 선수 식별 성능은 검증이 완료되지 않았습니다.")

    def check_model(self):
        # Legacy model fields remain developer-only. A generic action model is
        # never required to accept a rule-based pitch candidate.
        if self.development_package:
            self.availability.setText('기존 개발판 — 자동 탐색 비활성화. 자동 탐색 검증판을 사용하세요.')
            self.analyze_button.setEnabled(False);return
        try:
            from bsae.vision.rules import load_profile
            from bsae.ingest.media import tool
            profile=load_profile(self.profile.text() or None)
            for name in ('ffmpeg','ffprobe','tesseract'):tool(name)
            label='자동 화면 판별' if self.auto_profile else profile.get('display_name','직접 선택한 영상 분석 설정')
            notice='미검증 촬영 유형 · 선수 추적 미지원' if profile['camera'].get('mode')=='manual_geometry' else '플레이와 선수 확인 필요'
            self.availability.setText(label+' · 자동 탐색 시험 · '+notice)
            self.broadcast_group.setExclusive(False)
            for action in self.broadcast_group.actions():action.setChecked(not self.auto_profile and action.data()==Path(self.profile.text()).name)
            self.broadcast_group.setExclusive(True)
            self.analyze_button.setEnabled(not(self.job and self.job.isRunning()))
        except Exception as exc:
            self.availability.setText('자동 탐색 준비 안 됨: '+str(exc));self.analyze_button.setEnabled(False)

    def discard(self):
        return not self.dirty or QMessageBox.question(self,'저장하지 않은 변경','저장하지 않은 변경을 버릴까요?')==QMessageBox.Yes

    def new_session(self):
        if self.job and self.job.isRunning():return
        if not self.discard():return
        self.player.stop();self.preview_segments=[]
        self.session=None;self.project_path=None;self.dirty=False
        from bsae.core.output_settings import default_output_settings
        self.pending_output_settings=default_output_settings();self.load_output_preferences()
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
        self.locked_widgets=[(w,w.isEnabled()) for w in self.findChildren(QWidget) if isinstance(w,(QPushButton,QLineEdit,QComboBox,QDoubleSpinBox,QCheckBox,QListWidget,QTableWidget)) and not (isinstance(w,QPushButton) and w.text()=='중단')]
        for widget,enabled in self.locked_widgets:widget.setEnabled(False)
        self.project_menu.setEnabled(False)
        self.job=Job(operation)
        self.job.preflight.connect(self.show_analysis_preflight)
        self.job.progress.connect(lambda stage,v:(self.stage.setText(stage),self.progress.setValue(int(v*100))))
        self.job.error.connect(self.error);self.job.done.connect(done)
        self.job.finished.connect(self.job_finished);self.analyze_button.setEnabled(False);self.job.start()

    def job_finished(self):
        for widget,enabled in getattr(self,'locked_widgets',[]):widget.setEnabled(enabled)
        self.locked_widgets=[];self.project_menu.setEnabled(True)
        self.check_model()
        round_id=getattr(self,'pending_round_id',None)
        self.pending_round_id=None
        if round_id:self.show_analysis_rounds(round_id)

    def register_game(self):
        if self.job and self.job.isRunning():return
        if self.session:self.error('새 경기 버튼으로 새 프로젝트를 시작하세요.');return
        if not self.name.text().strip() or not self.files.count():self.error('선수 이름과 영상 파일을 입력하세요.');return
        paths=[self.files.item(i).text() for i in range(self.files.count())]
        identity=self.current_identity()
        game_date=self.date.text()
        self.launch(lambda job:GameSession(identity.name,identity,add_sources(paths),game_date=game_date),self.registered)

    def show_analysis_preflight(self,assessment):
        details=assessment.get('preflight',{})
        text=(f"대표 화면 사전 진단 (전체 경기 판정 아님)\n투구 구도 관측: {details.get('pitch_camera_observed')}\n문자 관측 화면: {details.get('text_frames',0)}\n요청 이름 자막 근거: {details.get('requested_name_hint_frames',0)}\n선수 식별 근거 화면: {details.get('identity_evidence_frames',0)}\n\n식별 준비가 확인되지 않았습니다. 신원 미확정 후보 탐색을 계속할까요? 자동 선수 확인으로 처리하지 않습니다.")
        answer=QMessageBox.question(self,'전체 분석 전 신원 근거 진단',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        self.job.preflight_continue=answer==QMessageBox.Yes;self.job.preflight_reply.set()

    def registered(self,session):
        self.session=session;self.fill_identity(session.player);self.dirty=True;self.refresh();self.load_output_preferences()
        self.start.setValue(0);self.end.setValue(min(10,sum(s.duration for s in session.sources)))
        self.stage.setText('검증용 원본 등록 완료 — 수동 정답 작업이며 자동 탐색 결과가 아닙니다.')

    def start_analysis(self):
        if self.development_package:self.error('개발판에는 검증된 분석 자산이 없어 자동 탐색이 비활성화되어 있습니다.');return
        if self.job and self.job.isRunning():return
        if not self.name.text().strip() or not self.files.count():self.error('분석 선수와 경기영상을 선택하세요.');return
        try:
            from bsae.vision.rules import load_profile
            profile=load_profile(self.profile.text() or None)
            settings=self.current_output_preferences()
        except Exception as exc:self.error(exc);return
        path=self.project_path
        if not path:
            path,_=QFileDialog.getSaveFileName(self,'경기 작업파일 저장 위치','','JSON (*.json)')
            if not path:return
            if Path(path).exists():self.error('기존 파일을 보존하려면 새 파일명을 선택하세요.');return
        paths=[self.files.item(i).text() for i in range(self.files.count())]
        identity=self.current_identity();existing=deepcopy(self.session) if self.session else None
        game_date=self.date.text();auto_profile=self.auto_profile
        def operation(job):
            from bsae.vision.rules import analyze_plays
            from bsae.core.rounds import run_round
            job.progress.emit('경기영상·원본 식별 정보 확인',0)
            session=existing or GameSession(identity.name,identity,add_sources(paths),game_date=game_date)
            session.output_settings=settings;session.save(path)
            def analyzer(work,requested,cache,stop,progress):
                from bsae.vision.workflow import analyze_for_review
                analyze_for_review(work,requested,cache,stop,progress,automatic_profile=auto_profile,preflight=job.ask_preflight)
            result=run_round(session,identity,profile,str(Path(path).with_suffix('.sqlite')),job.stop,job.progress.emit,analyzer)
            result.session.save(path);return result
        self.project_path=path;self.launch(operation,self.round_done)

    def analysis_done(self,session):
        self.session=session;self.fill_identity(session.player);self.dirty=False;self.refresh();self.load_output_preferences()
        self.remember_project(session,self.project_path)
        counts=session.analysis.get('counts',{})
        layout=session.analysis.get('layout_detection',{})
        prefix=('미검증 촬영 유형 · 선수 추적 미지원 / ' if session.analysis.get('support_status')=='UNVERIFIED_CAMERA_TYPE' else '투구 후보 없음 · 미인식/누락 검수 필요 / ' if not session.events else '화면 구성 인식 실패 · 영역 보정 필요 / ' if layout.get('status')=='UNRECOGNIZED_LAYOUT' else '중계 유형·신원 검수 필요 / ' if layout.get('confidence')=='UNCERTAIN' else '')
        self.stage.setText(('타자 식별 미완료 · 기본 목록은 목표 선수 근거가 있는 후보만 표시 · 전체/미확정 필터 확인 / ' if session.player.role=='batter' and not any(e.batter_id==session.player.id for e in session.events) else '')+prefix+f"후보 {len(session.events)}개 / 타석 {len(session.appearances)}개 / 선수 확인 필요 {counts.get('uncertain',0)}개 / 누락 의심 {len(session.analysis.get('coverage_gaps',[]))}구간 — 검수 필요")

    def cancel(self):
        if self.job:self.job.stop.set();self.stage.setText('중단 요청: 현재 처리 단위 종료 후 캐시 보존')

    def update_active_context(self,*args):
        active=f'{self.session.player.name} ({"투수" if self.session.player.role=="pitcher" else "타자"})' if self.session else '없음'
        self.active_context.setText(f'현재 검수 선수: {active} / 입력한 분석 선수: {self.name.text()} ({self.role.currentText()})')
        if self.session and self.session.player.role=='batter':
            total=len(self.session.events);automatic=sum(e.identity_status=='TARGET_CONFIRMED' for e in self.session.events);manual=sum(e.manual_identity_confirmed for e in self.session.events)
            self.active_context.setText(self.active_context.text()+f' / 자동 근거 {automatic}개 · 수동 확인 {manual}개 · 미확정 {sum(e.identity_status=="IDENTITY_UNKNOWN" and not e.manual_identity_confirmed for e in self.session.events)}개 · 전체 {total}개')

    def require_active_identity(self):
        from bsae.core.rounds import identity_key
        if self.session and identity_key(self.current_identity())!=identity_key(self.session.player):raise ValueError('입력한 선수와 현재 검수 선수가 다릅니다. 새 탐색 회차로 전환하거나 프로젝트 메뉴에서 현재 검수 선수 정보를 복원하세요.')

    def refresh(self):
        self.update_active_context()
        from bsae.core.summary import review_counts
        c=review_counts(self.session)
        self.analysis_summary.setText(f"현재 회차 전체 후보 {c['total']}개(제외 포함) · 자동 신원 근거 {c['automatic']} · 직접 확인 {c['manual']}(자동과 중복 {c['overlap']}) · 신원 미확인 {c['unknown']} · 다른 선수 근거 {c['other']} · 검수 승인 {c['approved']} · 제외 {c['excluded']} — 진행률과 검수 완료는 별개")
        self.visible_events=[];self.table.setRowCount(0)
        if not self.session:
            self.plate_summary.setText('타석 그룹 0개');return
        mode=self.review_filter.currentIndex()
        if mode==4:self.visible_events=self.session.analysis.get('coverage_gaps',[])
        else:
            for e in self.session.events:
                state=next((x.value for x in e.evidence if x.kind=='identity_state'),'unconfirmed')
                target=getattr(e,'batter_id' if self.session.player.role=='batter' else 'pitcher_id')==self.session.player.id and (e.identity_status=='TARGET_CONFIRMED' or e.manual_identity_confirmed)
                hint=any(x.kind=='ocr:batter_name_hint' for x in e.evidence)
                legacy_other=e.event_type=='other_player_or_ocr_error' or state=='other_or_ocr_error'
                other=legacy_other or (state=='other_evidence' and not target);replay=e.event_type=='replay' or e.broadcast_status in ('REPLAY_SUSPECTED','ARCHIVE_SUSPECTED')
                if mode==0 and self.session.player.role=='batter' and not target:continue
                if mode==5 and (not target or replay or e.event_type=='pickoff'):continue
                if mode==6 and (target or not hint):continue
                if mode==7 and state!='conflict':continue
                if mode==8 and (state!='other_evidence' or target):continue
                if mode==0 and (other or replay):continue
                if mode==2 and not legacy_other:continue
                if mode==3 and not replay:continue
                self.visible_events.append(e)
        plates={p.id:i+1 for i,p in enumerate(self.session.appearances)}
        self.plate_summary.setText(f'타석 그룹 {len(plates)}개 · 확정 {sum(p.confirmed for p in self.session.appearances)}개')
        plate_names={p.id:p.batter_name for p in self.session.appearances}
        for i,e in enumerate(self.visible_events):
            self.table.insertRow(i)
            if isinstance(e,dict):values=['?', '-', '-',f"{e['start']:.3f}",f"{e['end']:.3f}",'누락 의심: 투구 아님']
            else:values=[e.number,plates.get(e.plate_id,'?'),e.inning or '?',f'{e.timeline_start:.3f}',f'{e.timeline_end:.3f}',{'REVIEW_REQUIRED':'검수 필요','APPROVED':'승인','EXCLUDED':'제외'}[e.status]]
            values.append('-' if isinstance(e,dict) else plate_names.get(e.plate_id) or '미확인')
            values.append('-' if isinstance(e,dict) else {'TARGET_CONFIRMED':'자동 목표 근거','OTHER_PLAYER':'다른 선수 근거','IDENTITY_UNKNOWN':'미확정'}[e.identity_status]+(' · 수동 확인' if e.manual_identity_confirmed else ''))
            for j,value in enumerate(values):self.table.setItem(i,j,QTableWidgetItem(str(value)))
            if not isinstance(e,dict):self.table.item(i,1).setToolTip('타자: '+(plate_names.get(e.plate_id) or '미확인'))

    def selected_event(self):
        self.require_active_identity()
        i=self.table.currentRow()
        if self.session and 0<=i<len(self.visible_events):
            e=self.visible_events[i]
            if not isinstance(e,dict):return e
            raise ValueError('누락 의심 구간은 투구로 확정되지 않았습니다. 원본 확인 후 보조 후보를 추가하세요.')
        raise ValueError('후보를 선택하세요')

    def selected(self):
        i=self.table.currentRow()
        if not 0<=i<len(self.visible_events):return
        e=self.visible_events[i];self.confirm.setChecked(False)
        if isinstance(e,dict):
            self.start.setValue(e['start']);self.end.setValue(e['end']);self.evidence.setText(e['reason']);return
        self.start.setValue(e.timeline_start);self.end.setValue(e.timeline_end)
        self.evidence.setText('\n'.join(e.warnings)+'\n'+ '; '.join(x.kind+': '+x.value[:150] for x in e.evidence))

    def selected_event_ids(self):
        self.require_active_identity()
        rows=sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if not rows:raise ValueError('검수할 후보 행을 선택하세요')
        selected=[self.visible_events[i] for i in rows]
        if any(isinstance(e,dict) for e in selected):raise ValueError('누락 의심 구간은 투구 후보가 아니므로 일괄 검수할 수 없습니다.')
        return [e.id for e in selected]

    def approve_selected(self):
        try:
            from bsae.core.review import review_many
            ids=self.selected_event_ids()
            if QMessageBox.question(self,'선택 플레이 검수 완료',f'선택한 {len(ids)}개 후보의 구간과 대상 선수를 모두 확인했나요?\n현재 구간을 승인하며 미확정 신원을 자동으로 바꾸지 않습니다. 먼저 선택 후보 선수 확인을 사용하세요.')!=QMessageBox.Yes:return
            count=review_many(self.session,ids,confirm_identity=False)
            self.dirty=True;self.refresh();self.stage.setText(f'{count}개 후보 승인 완료 · 프로젝트를 저장하세요')
        except Exception as exc:self.error(exc)

    def confirm_selected_players(self):
        try:
            from PySide6.QtWidgets import QDialog
            from bsae.core.review import confirm_manual_identities
            ids=self.selected_event_ids();events=[e for e in self.session.events if e.id in ids]
            dialog=QDialog(self);dialog.setWindowTitle('직접 확인한 후보만 선수 확인 · 자동 판정은 유지');dialog.resize(800,450)
            layout=QVBoxLayout(dialog);layout.addWidget(QLabel('각 영상을 확인한 행만 체크하세요. 선수 입력만으로 확인되지 않습니다. 이 작업은 구간 승인과 별개입니다.'))
            table=QTableWidget(len(events),4);table.setHorizontalHeaderLabels(['직접 확인','투구 번호','구간','자동 신원 판정']);checks=[];layout.addWidget(table)
            for i,e in enumerate(events):
                check=QCheckBox();table.setCellWidget(i,0,check);checks.append(check)
                for j,v in enumerate([e.number,f'{e.timeline_start:.2f}–{e.timeline_end:.2f}',e.identity_status],1):table.setItem(i,j,QTableWidgetItem(str(v)))
            def confirm():
                try:
                    chosen=[e.id for e,c in zip(events,checks) if c.isChecked()]
                    count=confirm_manual_identities(self.session,chosen);self.dirty=True;self.refresh();self.stage.setText(f'{count}개 후보 수동 선수 확인 · 자동 신원 판정 유지 · 구간 검수 후 승인하세요');dialog.accept()
                except Exception as exc:self.error(exc)
            self.button(layout,'체크한 후보만 수동 선수 확인',confirm);dialog.exec()
        except Exception as exc:self.error(exc)

    def edit_pitch_number(self):
        try:
            from bsae.core.review import set_pitch_numbers
            e=self.selected_event()
            value,ok=QInputDialog.getInt(self,'투구 번호 직접 수정','현재 행의 투구 번호만 바꿉니다. 다른 행과 영상 순서는 유지합니다.',max(1,e.number),1,99999)
            if not ok:return
            duplicate=any(other.id!=e.id and other.number==value for other in self.session.events)
            if duplicate and QMessageBox.question(self,'투구 번호 중복',f'{value}번이 다른 후보에도 있습니다. 다른 번호는 자동 수정하지 않습니다. 그대로 저장할까요?')!=QMessageBox.Yes:return
            set_pitch_numbers(self.session,{e.id:value});self.dirty=True;self.refresh()
            self.stage.setText(f'투구 번호 {value}로 수정 · 번호는 투구 개수와 다릅니다 · 프로젝트를 저장하세요')
        except Exception as exc:self.error(exc)

    def edit_inning(self):
        try:
            from bsae.core.review import set_innings
            ids=self.selected_event_ids()
            values={e.inning for e in self.session.events if e.id in ids}
            initial=next(iter(values)) if len(values)==1 else ''
            value,ok=QInputDialog.getText(self,'선택 플레이 이닝 수정',f'{len(ids)}개 후보에 적용 (예: 9초, 9회말 / 빈칸: 미확정)',text=initial or '')
            if not ok:return
            count=set_innings(self.session,ids,value)
            self.dirty=True;self.refresh();self.stage.setText(f'{count}개 후보 이닝 수정 · 프로젝트를 저장하세요')
        except Exception as exc:self.error(exc)

    def classify_selected(self,kind):
        try:
            from bsae.core.review import classify_event
            classify_event(self.session,self.selected_event().id,kind)
            self.dirty=True;self.refresh()
        except Exception as exc:self.error(exc)

    def edit_plate(self,merge):
        try:
            from bsae.core.review import split_plate,merge_previous_plate
            event=self.selected_event()
            if merge and QMessageBox.question(self,'타석 병합 검수','원본에서 같은 타석임을 확인했나요?')!=QMessageBox.Yes:return
            (merge_previous_plate if merge else split_plate)(self.session,event.id)
            self.dirty=True;self.refresh()
        except Exception as exc:self.error(exc)

    def cleanup_automatic_plates(self):
        if not self.session or self.job and self.job.isRunning():return
        try:
            from bsae.core.rounds import clear_unsubstantiated_plates
            self.require_active_identity()
            if QMessageBox.question(self,'자동 타석 정리','타자 근거·검수 기록이 없는 자동 타석만 미배정으로 되돌립니다. 기존 검수는 보관하며 확인·수정한 그룹은 유지합니다. 진행할까요?')!=QMessageBox.Yes:return
            count=clear_unsubstantiated_plates(self.session)
            if count:self.dirty=True;self.refresh()
            self.stage.setText(f'자동 타석 {count}개 정리 · 회차 메뉴에서 복원 가능 · 프로젝트를 저장하세요')
        except Exception as exc:self.error(exc)

    def show_batter_captions(self):
        if not self.session:return
        from PySide6.QtWidgets import QDialog
        anchors=self.session.analysis.get('caption_anchors',[])
        dialog=QDialog(self);dialog.setWindowTitle('타자명 자막 근거 · 선수 신원·타석 확정 아님');dialog.resize(850,450)
        layout=QVBoxLayout(dialog);layout.addWidget(QLabel('입력한 이름과 일치한 OCR 자막입니다. 등번호는 자막에서 읽힌 값이며 유니폼 번호 인식이 아닙니다. 더블클릭: 주변 영상 확인'))
        table=QTableWidget(len(anchors),4);table.setHorizontalHeaderLabels(['시각(초)','읽힌 이름','역할·주변 문자','관측 팀/자막 번호']);table.setEditTriggers(QTableWidget.NoEditTriggers);layout.addWidget(table)
        for i,a in enumerate(anchors):
            for j,v in enumerate([f"{a['time']:.1f}",a['name'],a['role_text'],a['team']+' / '+a['caption_jersey']]):table.setItem(i,j,QTableWidgetItem(v))
        def preview(row,column):
            a=anchors[row]['time'];end=min(sum(s.duration for s in self.session.sources),a+10)
            self.preview_segments=self.session.split(max(0,a-3),end);self.preview_index=0;self.play_segment()
        table.cellDoubleClicked.connect(preview);dialog.exec()

    def save_diagnostics(self):
        if not self.session:return
        parent=QFileDialog.getExistingDirectory(self,'진단 결과 저장 위치')
        if not parent:return
        try:
            from datetime import datetime
            from bsae.vision.rules import export_diagnostics
            path=export_diagnostics(self.session,Path(parent)/('탐색결과_'+datetime.now().strftime('%Y%m%d_%H%M%S')))
            self.stage.setText('CSV·JSON 저장: '+str(path))
        except Exception as exc:self.error(exc)

    def apply(self,status):
        try:
            from bsae.core.review import review_many
            ids=self.selected_event_ids()
            e=self.selected_event()
            ranges={e.id:(self.start.value(),self.end.value())} if e.id in ids else {}
            if len(ids)>1 and QMessageBox.question(self,'선택 후보 일괄 검수',f'선택한 {len(ids)}개 후보만 처리합니다.\n시각 수정은 현재 행에만 적용하고 나머지는 기존 구간을 유지합니다.\n미확정 후보는 먼저 선택 후보 선수 확인을 해야 합니다. 계속할까요?')!=QMessageBox.Yes:return
            count=review_many(self.session,ids,status,confirm_identity=self.confirm.isChecked() and len(ids)==1,note='GUI 선택 검수',ranges=ranges)
            self.dirty=True;self.refresh();self.stage.setText(f'선택 후보 {count}개 처리 완료 · 프로젝트를 저장하세요')
        except Exception as exc:self.error(exc)

    def assign_selected_plate(self):
        try:
            from bsae.core.review import assign_plate
            ids=self.selected_event_ids()
            name,ok=QInputDialog.getText(self,'선택 투구 타석 구성','이 투구들을 한 타석으로 묶습니다. 타자 이름 (모르면 빈칸):')
            if not ok:return
            assign_plate(self.session,ids,name);self.dirty=True;self.refresh()
        except Exception as exc:self.error(exc)

    def edit_plate_batter(self):
        try:
            from bsae.core.review import name_plate
            e=self.selected_event();pa=next((p for p in self.session.appearances if p.id==e.plate_id),None)
            if pa is None:raise ValueError('먼저 선택 투구를 한 타석으로 묶으세요')
            name,ok=QInputDialog.getText(self,'타석 타자명 수정','상대 타자 이름 (투수의 선수 정보는 바뀌지 않습니다):',text=pa.batter_name)
            if ok:name_plate(self.session,e.id,name);self.dirty=True;self.refresh()
        except Exception as exc:self.error(exc)

    def manual(self):
        if not self.session:return
        try:
            self.require_active_identity()
            a,b=self.start.value(),self.end.value()
            if b<=a:raise ValueError('시작·종료를 입력하세요')
            e=PitchEvent(self.session.id,self.session.split(a,b),a,b,number=max((e.number for e in self.session.events),default=0)+1,event_type='manual_candidate',evidence=[DetectionEvidence('manual','사용자 보조 추가',a)])
            self.session.events.append(e);self.session.validate();self.dirty=True;self.refresh()
        except Exception as exc:self.error(exc)

    def confirm_plate(self):
        try:
            e=self.selected_event()
            if not e.plate_id:raise ValueError('선택 투구를 한 타석으로 버튼으로 먼저 구성하세요')
            pa=next(p for p in self.session.appearances if p.id==e.plate_id)
            if QMessageBox.question(self,'타석 그룹 검수',f'이 그룹의 {len(pa.event_ids)}개 투구가 한 타석인지 확인했나요?')==QMessageBox.Yes:
                pa.confirmed=True;self.dirty=True;self.refresh()
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
            try:self.session.save(path);self.project_path=path;self.dirty=False;self.remember_project(self.session,path)
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
            self.fill_identity(p);self.date.setText(self.session.game_date)
            self.role.setCurrentIndex(0 if p.role=='pitcher' else 1);self.dirty=False;self.refresh();self.load_output_preferences();self.remember_project(self.session,path)
        except Exception as exc:self.error(exc)

    def start_export(self):
        try:self.require_active_identity()
        except ValueError as exc:self.error(exc);return
        if not self.session or (self.job and self.job.isRunning()):return
        if not any(e.status=='APPROVED' for e in self.session.events):self.error('검수 완료된 플레이가 없습니다.');return
        if not self.edit_output_preferences(for_export=True):return
        parent=QFileDialog.getExistingDirectory(self,'출력 상위 폴더')
        if not parent:return
        name,ok=QInputDialog.getText(self,'새 출력 폴더','새 폴더 이름 (기존 폴더 불가)')
        if not ok or not name:return
        if Path(name).name!=name or name in ('.','..'):self.error('폴더 이름만 입력하세요');return
        from bsae.export.render import export
        session=deepcopy(self.session);mode=['all','pitch','plate'][self.output_mode.currentIndex()]
        include_pickoffs=self.pickoff_option.isChecked()
        settings=self.current_output_preferences();self.session.output_settings=deepcopy(settings);session.output_settings=settings;self.dirty=True
        auto_frame=settings['auto_frame']
        self.launch(lambda job:export(session,Path(parent)/name,mode,include_pickoffs=include_pickoffs,auto_frame=auto_frame,progress=lambda v:job.progress.emit('승인 영상 출력·검증',v),stop=job.stop),lambda path:self.stage.setText('검증 완료: '+str(path)))

    def closeEvent(self,event):
        self.video.setFullScreen(False)
        if self.job and self.job.isRunning():
            self.cancel();self.error('작업 중단 후 창을 닫으세요.');event.ignore();return
        if not self.discard():event.ignore();return
        self.player.stop();self.player.setVideoOutput(None);self.player.setAudioOutput(None);event.accept()
