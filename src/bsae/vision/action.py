"""Actual pretrained R3D-18 inference. Kinetics actions are NOT pitch labels."""
from pathlib import Path
import hashlib
import json
import cv2
import numpy as np

BASEBALL_ACTIONS = ('catching or throwing baseball', 'hitting baseball')


class ActionModel:
    def __init__(self, manifest):
        path=Path(manifest)
        self.info=json.loads(path.read_text(encoding='utf-8'))
        if self.info.get('backend')!='r3d18-kinetics400-onnx-v1':raise ValueError('지원하지 않는 동작 모델')
        artifact=(path.parent/self.info['artifact']).resolve(strict=True)
        if artifact.parent!=path.parent.resolve():raise ValueError('외부 모델 경로')
        with artifact.open('rb') as f:self.digest=hashlib.file_digest(f,'sha256').hexdigest()
        if self.digest!=self.info['sha256']:raise ValueError('동작 모델 체크섬 불일치')
        self.labels=self.info['categories']
        if len(self.labels)!=400 or len(set(self.labels))!=400 or not set(BASEBALL_ACTIONS)<=set(self.labels):
            raise ValueError('Kinetics 클래스 목록 오류')
        if not self.info.get('source_url') or not self.info.get('license_notice'):raise ValueError('모델 출처/고지 누락')
        # Do not accept altered preprocessing under an official-model identifier.
        p=self.info.get('preprocessing',{})
        if p!={'resize':[128,171],'crop':[112,112],'mean':[0.43216,0.394666,0.37645],'std':[0.22803,0.22145,0.216989],'frames':16,'fps':15}:
            raise ValueError('공식 R3D-18 전처리 불일치')
        try:import onnxruntime as ort
        except ImportError as exc:raise RuntimeError('이 개발 환경에 선택적 ONNX Runtime이 없습니다. 배포 통합 전 준비가 필요합니다.') from exc
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(artifact),sess_options=options,providers=['CPUExecutionProvider'])
        inputs=self.session.get_inputs()
        if len(inputs)!=1 or inputs[0].shape!=[1,3,16,112,112] or inputs[0].type!='tensor(float)':
            raise ValueError('동작 모델 입력 규격 불일치')
        self.input_name=inputs[0].name

    @staticmethod
    def preprocess(frames):
        if len(frames)!=16:raise ValueError('16개 시계열 프레임 필요')
        cropped=[]
        for frame in frames:
            if frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3:raise ValueError('RGB uint8 프레임 필요')
            resized=cv2.resize(frame,(171,128),interpolation=cv2.INTER_LINEAR)
            cropped.append(resized[8:120,30:142])
        x=np.asarray(cropped,np.float32)/255.0
        x=(x-np.array([.43216,.394666,.37645],np.float32))/np.array([.22803,.22145,.216989],np.float32)
        return np.ascontiguousarray(x.transpose(3,0,1,2)[None])

    def predict(self, frames, top_k=3):
        if not 1<=top_k<=10:raise ValueError('top_k는 1~10')
        logits=self.session.run(None,{self.input_name:self.preprocess(frames)})[0]
        if logits.shape!=(1,400) or not np.isfinite(logits).all():raise ValueError('잘못된 동작 모델 출력')
        order=np.argsort(logits[0])[::-1]
        top=[dict(label=self.labels[i],logit=float(logits[0,i]),rank=n+1) for n,i in enumerate(order[:10])]
        baseball=[r for r in top[:top_k] if r['label'] in BASEBALL_ACTIONS]
        return dict(baseball=bool(baseball),actions=baseball,top=top,
                    confidence=None,calibration='NOT_EVALUATED')
