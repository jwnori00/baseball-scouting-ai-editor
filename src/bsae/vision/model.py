"""Small CPU temporal classifier trained locally; no shipped baseball weights.

Spatial RGB/gradient and inter-frame motion features are classified using a
regularized linear model. Scores are NOT calibrated probabilities.
"""
from pathlib import Path
import hashlib
import json
import cv2
import numpy as np
from bsae.core.models import atomic_json

LABELS = ('other', 'setup', 'delivery', 'receive', 'live', 'dead', 'replay', 'pickoff')
FEATURE_VERSION = 'grid-motion-v1'


def features(frame, previous=None):
    small = cv2.resize(frame, (16, 9)).astype(np.float32) / 255
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    motion = np.zeros((3, 4), np.float32)
    if previous is not None:
        old = cv2.cvtColor(previous, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
        motion = cv2.resize(np.abs(gray-old), (4, 3), interpolation=cv2.INTER_AREA)
    edges = cv2.resize(np.abs(cv2.Laplacian(gray, cv2.CV_32F)), (4, 3), interpolation=cv2.INTER_AREA)
    return np.concatenate([small.ravel(), motion.ravel(), edges.ravel()])


class TemporalModel:
    def __init__(self, manifest):
        self.path = Path(manifest)
        self.info = json.loads(self.path.read_text(encoding='utf-8'))
        if self.info.get('feature_version') != FEATURE_VERSION or self.info.get('labels') != list(LABELS):
            raise ValueError('지원하지 않는 모델 형식')
        if not self.info.get('license') or not self.info.get('training_provenance'):
            raise ValueError('모델 라이선스/학습자료 출처 누락')
        artifact = self.path.parent / self.info['artifact']
        if artifact.resolve().parent != self.path.parent.resolve():
            raise ValueError('모델 파일은 manifest 폴더 안에 있어야 합니다')
        self.digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if self.digest != self.info['sha256']:
            raise ValueError('모델 체크섬 불일치')
        with np.load(artifact, allow_pickle=False) as data:
            self.mean, self.scale, self.weights = [data[k].copy() for k in ('mean', 'scale', 'weights')]
        if self.mean.shape != (456,) or self.scale.shape != (456,) or self.weights.shape != (457, len(LABELS)):
            raise ValueError('모델 차원 불일치')
        if not all(np.isfinite(x).all() for x in (self.mean, self.scale, self.weights)) or (self.scale <= 0).any():
            raise ValueError('유효하지 않은 모델 수치')

    def predict(self, x):
        scores = np.append((x-self.mean)/self.scale, 1) @ self.weights
        return LABELS[int(np.argmax(scores))], dict(zip(LABELS, map(float, scores)))


def train(samples, labels, destination, *, license_name, provenance):
    if set(labels) != set(LABELS):
        raise ValueError('모든 상태의 학습 예제가 필요합니다: ' + ', '.join(LABELS))
    if len(samples) < len(LABELS)*3 or not license_name.strip() or not provenance.strip():
        raise ValueError('상태별 예제/라이선스/출처를 확인하세요')
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != 456 or not np.isfinite(x).all():
        raise ValueError('잘못된 학습 특징')
    mean, scale = x.mean(0), np.maximum(x.std(0), 0.01)
    z = np.column_stack([(x-mean)/scale, np.ones(len(x))])
    y = np.eye(len(LABELS))[[LABELS.index(label) for label in labels]]
    weights = np.linalg.solve(z.T@z + np.eye(z.shape[1])*1.0, z.T@y)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    artifact = destination / 'temporal.npz'
    manifest = destination / 'model.json'
    if artifact.exists() or manifest.exists():
        raise FileExistsError('기존 모델을 덮어쓰지 않습니다')
    with artifact.open('xb') as f:
        np.savez_compressed(f, mean=mean, scale=scale, weights=weights)
    atomic_json(manifest, dict(feature_version=FEATURE_VERSION, labels=list(LABELS),
        artifact=artifact.name, sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        license=license_name, training_provenance=provenance,
        sample_counts={label: labels.count(label) for label in LABELS},
        validation='NOT_EVALUATED', confidence_calibration='NOT_EVALUATED'))
    return manifest
