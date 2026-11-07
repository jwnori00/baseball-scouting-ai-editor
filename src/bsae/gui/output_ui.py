"""Client-facing output preferences, independent of analysis profiles."""
from copy import deepcopy
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QDoubleSpinBox,QCheckBox,QPushButton
from bsae.core.output_settings import default_output_settings,validate_output_settings
from bsae.ingest.media import probe
from bsae.export.geometry import output_dimensions


class OutputUI:
    def load_output_preferences(self):
        settings=self.session.output_settings if self.session else self.pending_output_settings
        self.auto_frame_action.blockSignals(True)
        self.auto_frame_action.setChecked(settings['auto_frame'])
        self.auto_frame_action.blockSignals(False)

    def change_auto_frame(self,checked):
        settings=self.session.output_settings if self.session else self.pending_output_settings
        if settings['auto_frame']!=bool(checked):
            settings['auto_frame']=bool(checked)
            if self.session:self.dirty=True

    def current_output_preferences(self):
        settings=deepcopy(self.session.output_settings if self.session else self.pending_output_settings)
        settings['auto_frame']=self.auto_frame_action.isChecked()
        return validate_output_settings(settings)

    def edit_output_preferences(self,for_export=False):
        if self.job and self.job.isRunning():return
        settings=self.current_output_preferences();video=None
        try:
            first=next(iter(sorted([e for e in self.session.events if e.status=='APPROVED'],key=lambda e:e.timeline_start)),None) if self.session else None
            source=next((s for s in self.session.sources if first and s.id==first.segments[0].source_id),None) if self.session else None
            path=source.path if source else self.session.sources[0].path if self.session and self.session.sources else self.files.item(0).text() if self.files.count() else None
            if path:video=next(s for s in probe(path)['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic'))
        except Exception as exc:self.error(exc);return
        dialog=QDialog(self);dialog.setWindowTitle('스카우팅 영상 출력 설정');layout=QVBoxLayout(dialog)
        aspect=QComboBox();labels=['원본 표시 비율 유지','16:9','4:3','9:16 (스마트폰 세로)','1:1','사용자 지정'];keys=['source','16:9','4:3','9:16','1:1','custom']
        aspect.addItems(labels);aspect.setCurrentIndex(keys.index(settings['aspect']));layout.addWidget(QLabel('화면비율'));layout.addWidget(aspect)
        row=QHBoxLayout();layout.addLayout(row);custom=[]
        for label,key in [('가로 비', 'custom_width'),('세로 비','custom_height')]:
            box=QDoubleSpinBox();box.setRange(.001,10000);box.setDecimals(3);box.setValue(settings[key]);row.addWidget(QLabel(label));row.addWidget(box);custom.append(box)
        resolution=QComboBox();resolution.addItems(['720급 · 짧은 변 720px','1080급 · 짧은 변 1080px']);resolution.setCurrentIndex(0 if settings['resolution']==720 else 1)
        layout.addWidget(QLabel('해상도 (긴 변 최대 3840px)'));layout.addWidget(resolution)
        layout.addWidget(QLabel('화면 배치: 전체 화면 보존 · 비율이 다르면 여백 추가 · 30fps'))
        crop=QCheckBox('검은 여백 제거·확대 (원본 구도가 달라질 수 있음)');crop.setChecked(settings['auto_frame']);layout.addWidget(crop)
        preview=QLabel();layout.addWidget(preview)
        layout.addWidget(QLabel('통합 파일은 첫 플레이 원본의 비율을 기준으로 통일합니다.\n투구별·타석별 파일은 각 파일의 첫 원본을 기준으로 합니다.\n확대는 원본에서 손실된 세부 화질을 복원하지 않습니다.'))
        def values():return dict(aspect=keys[aspect.currentIndex()],custom_width=custom[0].value(),custom_height=custom[1].value(),resolution=(720,1080)[resolution.currentIndex()],placement='fit',auto_frame=crop.isChecked())
        def update(*args):
            for box in custom:box.setEnabled(keys[aspect.currentIndex()]=='custom')
            try:
                if video is None and values()['aspect']=='source':preview.setText('원본 영상 선택 후 출력 크기를 확인할 수 있습니다.');return
                w,h=output_dimensions(video or dict(width=16,height=9),values());preview.setText(f'출력 예상 크기: {w} × {h} / 30fps')
            except ValueError as exc:preview.setText(str(exc))
        def apply():
            try:
                result=validate_output_settings(values())
                if video is not None:output_dimensions(video,result)
                self.pending_output_settings=deepcopy(result)
                if self.session:self.session.output_settings=result;self.dirty=True
                self.auto_frame_action.setChecked(result['auto_frame']);self.stage.setText('출력 설정 반영 · 프로젝트를 저장하세요');dialog.accept()
            except Exception as exc:self.error(exc)
        aspect.currentIndexChanged.connect(update);resolution.currentIndexChanged.connect(update)
        for box in custom:box.valueChanged.connect(update)
        button=QPushButton('이 설정으로 출력 계속' if for_export else '출력 설정 반영');button.clicked.connect(apply);layout.addWidget(button);update();return dialog.exec()==QDialog.Accepted
