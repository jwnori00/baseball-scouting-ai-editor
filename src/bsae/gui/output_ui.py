"""One export window; detailed geometry stays collapsed unless requested."""
from copy import deepcopy
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QDoubleSpinBox,QCheckBox,QPushButton,QWidget,QLineEdit,QFileDialog
from bsae.core.output_settings import validate_output_settings
from bsae.ingest.media import probe
from bsae.export.geometry import output_dimensions


class OutputSettingsPane(QWidget):
    def __init__(self,settings,video,parent=None):
        super().__init__(parent);self.video=video;layout=QVBoxLayout(self)
        self.keys=['source','16:9','4:3','9:16','1:1','custom'];self.aspect=QComboBox();self.aspect.addItems(['원본 표시 비율 유지','16:9','4:3','9:16 (스마트폰 세로)','1:1','사용자 지정']);self.aspect.setCurrentIndex(self.keys.index(settings['aspect']))
        layout.addWidget(QLabel('화면비율'));layout.addWidget(self.aspect);row=QHBoxLayout();layout.addLayout(row);self.custom=[]
        for label,key in [('가로 비','custom_width'),('세로 비','custom_height')]:
            box=QDoubleSpinBox();box.setRange(.001,10000);box.setDecimals(3);box.setValue(settings[key]);row.addWidget(QLabel(label));row.addWidget(box);self.custom.append(box)
        self.resolution=QComboBox();self.resolution.addItems(['720급 · 짧은 변 720px','1080급 · 짧은 변 1080px']);self.resolution.setCurrentIndex(0 if settings['resolution']==720 else 1);layout.addWidget(self.resolution)
        self.crop=QCheckBox('검은 여백 제거·확대 (원본 구도가 달라질 수 있음)');self.crop.setChecked(settings['auto_frame']);layout.addWidget(self.crop)
        self.preview=QLabel();self.preview.setWordWrap(True);layout.addWidget(self.preview)
        layout.addWidget(QLabel('전체 화면 보존 · 비율이 다르면 여백 추가 · 30fps\n확대는 원본에서 손실된 세부 화질을 복원하지 않습니다.'))
        self.aspect.currentIndexChanged.connect(self.update_preview);self.resolution.currentIndexChanged.connect(self.update_preview);self.crop.toggled.connect(self.update_preview)
        for box in self.custom:box.valueChanged.connect(self.update_preview)
        self.update_preview()
    def values(self):
        return validate_output_settings(dict(aspect=self.keys[self.aspect.currentIndex()],custom_width=self.custom[0].value(),custom_height=self.custom[1].value(),resolution=(720,1080)[self.resolution.currentIndex()],placement='fit',auto_frame=self.crop.isChecked()))
    def update_preview(self,*args):
        for box in self.custom:box.setEnabled(self.aspect.currentIndex()==5)
        try:
            settings=self.values()
            if self.video is None and settings['aspect']=='source':self.preview.setText('영상 선택 후 출력 크기를 확인합니다.');return
            w,h=output_dimensions(self.video or dict(width=16,height=9),settings);self.preview.setText(f'출력 예상: {w} × {h} / 30fps / 화면 전체 보존')
        except ValueError as exc:self.preview.setText(str(exc))


class OutputUI:
    def load_output_preferences(self):
        settings=self.session.output_settings if self.session else self.pending_output_settings
        self.auto_frame_action.blockSignals(True);self.auto_frame_action.setChecked(settings['auto_frame']);self.auto_frame_action.blockSignals(False)
    def change_auto_frame(self,checked):
        settings=self.session.output_settings if self.session else self.pending_output_settings
        if settings['auto_frame']!=bool(checked):
            settings['auto_frame']=bool(checked)
            if self.session:self.dirty=True
    def current_output_preferences(self):
        settings=deepcopy(self.session.output_settings if self.session else self.pending_output_settings);settings['auto_frame']=self.auto_frame_action.isChecked()
        return validate_output_settings(settings)
    def output_video(self):
        first=next(iter(sorted([e for e in self.session.events if e.status=='APPROVED'],key=lambda e:e.timeline_start)),None) if self.session else None
        source=next((s for s in self.session.sources if first and s.id==first.segments[0].source_id),None) if self.session else None
        path=source.path if source else self.session.sources[0].path if self.session and self.session.sources else self.files.item(0).text() if self.files.count() else None
        return next(s for s in probe(path)['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')) if path else None
    def apply_output_settings(self,settings):
        self.pending_output_settings=deepcopy(settings)
        if self.session:self.session.output_settings=deepcopy(settings);self.dirty=True
        self.auto_frame_action.setChecked(settings['auto_frame'])
    def edit_output_preferences(self,for_export=False):
        if self.job and self.job.isRunning():return
        try:video=self.output_video()
        except Exception as exc:self.error(exc);return
        dialog=QDialog(self);dialog.setWindowTitle('고급 출력 설정');layout=QVBoxLayout(dialog);pane=OutputSettingsPane(self.current_output_preferences(),video);layout.addWidget(pane)
        def apply():
            try:
                settings=pane.values()
                if video:output_dimensions(video,settings)
                self.apply_output_settings(settings);dialog.accept()
            except Exception as exc:self.error(exc)
        button=QPushButton('출력 설정 반영');button.clicked.connect(apply);layout.addWidget(button);return dialog.exec()==QDialog.Accepted
    def choose_export(self):
        include=self.pickoff_option.isChecked();events=[e for e in self.session.events if e.status=='APPROVED' and (include or e.event_type!='pickoff')]
        if not events:self.error('먼저 출력할 클립을 승인하세요.');return
        try:video=self.output_video()
        except Exception as exc:self.error(exc);return
        dialog=QDialog(self);dialog.setWindowTitle('MP4 저장');dialog.resize(620,430);layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel(f'현재 검수 선수: {self.session.player.name} / 실제 출력 대상: 승인 클립 {len(events)}개'))
        form=QFormLayout();layout.addLayout(form);mode=QComboBox();mode.setObjectName('export-mode');mode.addItems(['승인 클립 합본 MP4','투구별 개별 MP4','타석별 개별 MP4']);mode.setCurrentIndex(self.output_mode.currentIndex());form.addRow('출력 방식',mode)
        folder=QLineEdit(str(Path(self.project_path).parent if self.project_path else Path.home()/'Videos'));folder.setObjectName('export-folder');row=QHBoxLayout();row.addWidget(folder);browse=QPushButton('폴더 찾기');row.addWidget(browse);form.addRow('저장 위치',row)
        name=QLineEdit('scouting_clips');name.setObjectName('export-name');form.addRow('새 폴더 이름',name)
        info=QLabel();info.setWordWrap(True);layout.addWidget(info)
        groups=QCheckBox('표시된 타석 구성과 승인 클립을 확인했습니다');groups.setObjectName('export-confirm-groups');layout.addWidget(groups)
        pane=OutputSettingsPane(self.current_output_preferences(),video);pane.hide();toggle=QPushButton('화면비율·화질 설정 (고급)');toggle.setCheckable(True);toggle.toggled.connect(pane.setVisible);layout.addWidget(toggle);layout.addWidget(pane)
        def refresh(*args):
            if mode.currentIndex()!=2:info.setText('승인 클립만 시간순으로 저장합니다. 기존 파일은 덮어쓰지 않습니다.');groups.hide();return
            chosen={e.id for e in events};pas=[p for p in self.session.appearances if chosen.intersection(p.event_ids)];pending=[p for p in pas if not p.confirmed]
            info.setText('타석 구성: '+(' / '.join(f'{i+1}타석 승인 {len(chosen.intersection(p.event_ids))}/{len(p.event_ids)}클립' for i,p in enumerate(pas)) or '그룹 없음 · 고급 편집에서 구성 필요'))
            groups.setVisible(bool(pending))
        def browse_folder():
            chosen=QFileDialog.getExistingDirectory(dialog,'저장 위치',folder.text())
            if chosen:folder.setText(chosen)
        result=[]
        def save():
            try:
                part=name.text().strip()
                if not folder.text().strip() or not part or Path(part).name!=part or part in ('.','..') or any(c in part for c in '<>:"/\\|?*'):raise ValueError('저장 위치와 새 폴더 이름을 확인하세요')
                destination=Path(folder.text()).expanduser()/part
                if destination.exists():raise FileExistsError('같은 이름의 폴더가 있습니다. 새 이름을 사용하세요.')
                if not destination.parent.is_dir():raise ValueError('저장 위치 폴더가 없습니다')
                settings=pane.values()
                if video:output_dimensions(video,settings)
                pending=[]
                if mode.currentIndex()==2:
                    chosen={e.id for e in events};pas=[p for p in self.session.appearances if chosen.intersection(p.event_ids)]
                    if {i for p in pas for i in p.event_ids}&chosen!=chosen:raise ValueError('타석 미지정 클립이 있습니다. 고급 편집에서 타석을 구성하세요.')
                    pending=[p.id for p in pas if not p.confirmed]
                    if pending and not groups.isChecked():raise ValueError('타석 구성을 확인하거나 고급 편집에서 수정하세요.')
                result.append(dict(destination=destination,mode=['all','pitch','plate'][mode.currentIndex()],settings=settings,confirm_groups=pending));self.output_mode.setCurrentIndex(mode.currentIndex());dialog.accept()
            except Exception as exc:self.error(exc)
        browse.clicked.connect(browse_folder);mode.currentIndexChanged.connect(refresh);button=QPushButton('MP4 저장');button.setObjectName('export-save');button.clicked.connect(save);layout.addWidget(button);refresh();dialog.exec()
        return result[0] if result else None
