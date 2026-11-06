"""Local reusable broadcast/camera profiles with drag-to-select normalized ROIs."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,uuid
from PySide6.QtCore import Qt,QRectF,Signal
from PySide6.QtGui import QImage,QPixmap,QPainter,QPen
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QLineEdit,QPushButton,QFileDialog
from bsae.core.library import data_directory
from bsae.core.models import atomic_json
from bsae.ingest.media import run

FIELDS={'투수/마운드 움직임':'camera:pitcher','타자·포수/홈플레이트 움직임':'camera:catcher','경기 화면':'camera:content','기존 LMB 패널':'camera:panel','투수 이름':'pitcher_name','투수 팀':'pitcher_team','투수 등번호':'pitcher_jersey','타자 이름':'batter_name','타자 팀':'batter_team','타자 등번호':'batter_jersey','이닝':'inning','볼·스트라이크 숫자':'count','리플레이 표식':'replay'}
TYPES={'방송형 중계':'broadcast','단순/스코어보드 없는 중계':'no_scoreboard','고정 카메라 · 실영상 미검증':'fixed_camera','이동/휴대전화 · 실영상 미검증':'moving_camera'}


class RegionCanvas(QLabel):
    box=Signal(list)
    def __init__(self,image):
        super().__init__();self.setFixedSize(800,450);self.setPixmap(QPixmap.fromImage(image).scaled(800,450));self.origin=None;self.current=None
    def mousePressEvent(self,event):self.origin=event.position();self.current=self.origin;self.update()
    def mouseMoveEvent(self,event):
        if self.origin is not None:self.current=event.position();self.update()
    def mouseReleaseEvent(self,event):
        if self.origin is None:return
        self.current=event.position();rect=QRectF(self.origin,self.current).normalized().intersected(QRectF(0,0,self.width(),self.height()))
        if rect.width()>=5 and rect.height()>=5:self.box.emit([rect.left()/self.width(),rect.top()/self.height(),rect.right()/self.width(),rect.bottom()/self.height()])
        self.origin=None;self.update()
    def paintEvent(self,event):
        super().paintEvent(event)
        if self.origin is not None:
            painter=QPainter(self);painter.setPen(QPen(Qt.red,2));painter.drawRect(QRectF(self.origin,self.current).normalized());painter.end()


class ProfileUI:
    def edit_broadcast_regions(self):
        if self.job and self.job.isRunning():return
        if not self.files.count():self.error('먼저 영상을 선택하세요.');return
        from bsae.vision.rules import load_profile
        from bsae.ingest.media import probe
        try:
            source=self.files.item(max(0,self.files.currentRow())).text();duration=float(probe(source)['format']['duration'])
            time,ok=__import__('PySide6.QtWidgets',fromlist=['QInputDialog']).QInputDialog.getDouble(self,'대표 프레임','영상 내 시각(초)',min(self.start.value(),max(0,duration-.1)),0,max(0,duration-.1),2)
            if not ok:return
            raw=run('ffmpeg',['-v','error','-ss',str(time),'-i',source,'-frames:v','1','-vf','scale=1280:720','-f','rawvideo','-pix_fmt','rgb24','-'])
            if len(raw)!=1280*720*3:raise ValueError('대표 프레임을 읽을 수 없습니다')
            image=QImage(raw,1280,720,1280*3,QImage.Format_RGB888).copy()
            path=Path(self.profile.text());profile=deepcopy(load_profile(path));profile.pop('scene_weights',None)
        except Exception as exc:self.error(exc);return
        dialog=QDialog(self);dialog.setWindowTitle('대표 프레임에서 영역 지정 · 저장 후 재사용');layout=QVBoxLayout(dialog)
        label=QLineEdit();label.setPlaceholderText('방송/구장/카메라 설정 이름');layout.addWidget(label)
        row=QHBoxLayout();layout.addLayout(row);kind=QComboBox();kind.addItems(TYPES);row.addWidget(kind)
        language=QComboBox();language.addItems(['eng','eng+kor','eng+jpn','eng+kor+jpn']);language.setCurrentText(profile.get('language','eng'));row.addWidget(language)
        fields=QComboBox();fields.addItems(FIELDS);layout.addWidget(fields)
        canvas=RegionCanvas(image);layout.addWidget(canvas);status=QLabel('지정할 항목을 고르고 화면에서 드래그하세요. 신원 지정이 아니라 분석 영역 설정입니다.');layout.addWidget(status)
        def selected(box):
            key=FIELDS[fields.currentText()]
            if key.startswith('camera:'):profile['camera'][key.split(':')[1]]=box
            else:profile.setdefault('regions',{})[key]=box
            status.setText(fields.currentText()+' 영역 지정됨')
        canvas.box.connect(selected)
        def detect_text():
            try:
                from bsae.vision.scoreboard import text_regions
                import numpy as np
                boxes=text_regions(np.frombuffer(raw,np.uint8).reshape(720,1280,3),language.currentText())
                status.setText(f'문자 블록 {len(boxes)}개 탐색. 이름의 역할과 스코어보드 여부는 미확정입니다. 영역을 직접 지정하세요.')
                profile['text_region_proposals']=boxes
            except Exception as exc:self.error(exc)
        button=QPushButton('문자 영역 자동 탐색 시도');button.clicked.connect(detect_text);layout.addWidget(button)
        def save():
            try:
                if not label.text().strip():raise ValueError('설정 이름을 입력하세요')
                directory=data_directory()/'profiles';directory.mkdir(parents=True,exist_ok=True)
                profile.update(id='user-'+uuid.uuid4().hex,display_name=label.text().strip(),input_type=TYPES[kind.currentText()],language=language.currentText(),scope='User-corrected layout; not validated accuracy')
                if profile['input_type'] in ('fixed_camera','moving_camera'):
                    profile['camera']['mode']='manual_geometry';profile['regions']={};profile['identity_policy']='unconfirmed; no player tracker'
                elif profile['input_type']=='no_scoreboard':profile['regions']={}
                if profile.get('scene_model'):
                    data=(path.parent/profile['scene_model']).read_bytes();name=hashlib.sha256(data).hexdigest()[:16]+'-scene.json'
                    model=directory/name
                    if not model.exists():model.write_bytes(data)
                    profile['scene_model']=name
                import re
                safe=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',label.text().strip()).strip(' .')[:60] or 'profile'
                target=directory/(safe+'-'+profile['id'][-8:]+'.profile.json');atomic_json(target,profile)
                load_profile(target);self.select_broadcast(target);self.stage.setText('사용자 프로필 저장: '+str(target));dialog.accept()
            except Exception as exc:self.error(exc)
        button=QPushButton('사용자 데이터 폴더에 프로필 저장');button.clicked.connect(save);layout.addWidget(button);dialog.exec()

    def open_broadcast_profile(self):
        path,_=QFileDialog.getOpenFileName(self,'저장한 방송·카메라 프로필',str(data_directory()/'profiles'),'방송 프로필 (*.profile.json);;JSON (*.json)')
        if path:self.select_broadcast(Path(path))

    def save_profile_preferences(self):
        path=Path(self.profile.text())
        root=Path(getattr(__import__('sys'),'_MEIPASS',Path(__file__).resolve().parents[3]))/'profiles'
        atomic_json(data_directory()/'preferences.json',dict(auto_profile=self.auto_profile,builtin=path.name if path.parent.resolve()==root.resolve() else None,profile_path=str(path)))

    def restore_profile_preferences(self):
        preferences=data_directory()/'preferences.json'
        if not preferences.exists():return
        try:
            data=json.loads(preferences.read_text(encoding='utf-8'))
            root=Path(getattr(__import__('sys'),'_MEIPASS',Path(__file__).resolve().parents[3]))/'profiles'
            name=data.get('builtin')
            candidate=root/name if isinstance(name,str) and Path(name).name==name else Path(data.get('profile_path',''))
            if candidate.is_file():self.profile.setText(str(candidate))
            self.auto_profile=data.get('auto_profile') is True
        except (ValueError,TypeError,OSError):pass
