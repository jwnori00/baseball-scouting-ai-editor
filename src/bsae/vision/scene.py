"""CPU scene classifier: supervised spatial color/edge features, no identity claim."""
import cv2
import numpy as np

FEATURE_VERSION='broadcast-grid-v1'
DIMENSION=192


def features(rgb):
    image=cv2.resize(rgb,(160,90),interpolation=cv2.INTER_AREA)
    hsv=cv2.cvtColor(image,cv2.COLOR_RGB2HSV)
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    channels=[gray,hsv[:,:,1].astype(np.float32)/255,
        ((hsv[:,:,0]>=25)&(hsv[:,:,0]<=90)&(hsv[:,:,1]>40)).astype(np.float32),
        ((hsv[:,:,0]<30)&(hsv[:,:,1]>40)&(hsv[:,:,2]<235)).astype(np.float32),
        ((hsv[:,:,1]<65)&(hsv[:,:,2]>140)).astype(np.float32),
        np.abs(cv2.Laplacian(gray,cv2.CV_32F))]
    return np.concatenate([cv2.resize(c,(8,4),interpolation=cv2.INTER_AREA).ravel() for c in channels]).astype(np.float64)


def validate(model):
    if model.get('feature_version')!=FEATURE_VERSION or model.get('labels')!=['other','pitch_camera']:
        raise ValueError('지원하지 않는 중계 구도 모델')
    for name,size in [('mean',DIMENSION),('scale',DIMENSION),('weights',DIMENSION+1)]:
        a=np.asarray(model[name],float)
        if a.shape!=(size,) or not np.isfinite(a).all():raise ValueError('중계 구도 모델 수치 오류')
    if min(model['scale'])<=0 or not np.isfinite(model['threshold']):raise ValueError('중계 구도 모델 범위 오류')
    return model


def margin(rgb,model):
    x=features(rgb)
    return float(np.append((x-np.asarray(model['mean']))/np.asarray(model['scale']),1)@np.asarray(model['weights']))


def train(samples,labels,provenance):
    x=np.asarray(samples,float);y=np.asarray(labels,int)
    if x.ndim!=2 or x.shape[1]!=DIMENSION or not np.isfinite(x).all() or set(y)!={0,1}:
        raise ValueError('두 종류의 실제 구도 학습 자료가 필요합니다')
    mean=x.mean(0);scale=np.maximum(x.std(0),.03)
    z=np.column_stack(((x-mean)/scale,np.ones(len(x))))
    balance=np.array([len(y)/(2*np.sum(y==v)) for v in y])
    regularizer=np.eye(DIMENSION+1)*10;regularizer[-1,-1]=.1
    weights=np.linalg.solve(z.T@(balance[:,None]*z)+regularizer,z.T@(balance*(2*y-1)))
    return validate(dict(feature_version=FEATURE_VERSION,labels=['other','pitch_camera'],mean=mean.tolist(),scale=scale.tolist(),weights=weights.tolist(),threshold=0.0,
        score_type='uncalibrated linear margin; not pitch or identity confidence',provenance=provenance,limitations=['Small private sample set; not universal baseball validation','No player identity, replay or play-end model']))
