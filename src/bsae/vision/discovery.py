"""Broadcast-assisted automatic candidates, never a claim of complete pitching AI.

Real R3D inference + broadcast geometry + localized temporal motion + OCR.
No reference timestamps are read by this module. All events require review.
"""
from collections import deque
import hashlib
import json
import math
import threading
import cv2
import numpy as np
from bsae.core.models import DetectionEvidence,PitchEvent
from bsae.ingest.media import frames,fingerprint,run
from .action import ActionModel
from .broadcast import IdentityContext,replay_text
from .cache import Cache
from .pipeline import Cancelled,group_appearances
from .scoreboard import ScoreboardOCR


def roi(frame,box):
    h,w=frame.shape[:2];x1,y1,x2,y2=box
    if not 0<=x1<x2<=1 or not 0<=y1<y2<=1:raise ValueError('잘못된 방송 영역')
    return frame[int(y1*h):int(y2*h),int(x1*w):int(x2*w)]


def geometry(rgb,profile):
    settings=profile['discovery']
    panel=roi(rgb,settings['telemetry_panel'])
    hsv=cv2.cvtColor(roi(rgb,settings['content']),cv2.COLOR_RGB2HSV)
    # Measurable broadcast cues, not calibrated scene-class probabilities.
    dark=float((cv2.cvtColor(panel,cv2.COLOR_RGB2GRAY)<75).mean())
    green=float(((hsv[:,:,0]>=25)&(hsv[:,:,0]<=90)&(hsv[:,:,1]>40)&(hsv[:,:,2]>35)).mean())
    soil=((hsv[:,:,0]<30)&(hsv[:,:,1]>40)&(hsv[:,:,2]>35)&(hsv[:,:,2]<235))
    field=float((((hsv[:,:,0]>=25)&(hsv[:,:,0]<=90)&(hsv[:,:,1]>40))|soil).mean())
    gate=dark>=settings.get('panel_dark_fraction',.68) and green>=settings.get('minimum_grass_fraction',.20)
    return bool(gate),field,dict(panel_dark=dark,grass=green)


def motion_energy(previous,current,profile):
    if previous is None:return 0.0
    a=cv2.cvtColor(roi(previous,profile['discovery']['pitcher_motion']),cv2.COLOR_RGB2GRAY)
    b=cv2.cvtColor(roi(current,profile['discovery']['pitcher_motion']),cv2.COLOR_RGB2GRAY)
    flow=cv2.calcOpticalFlowFarneback(a,b,None,.5,3,15,3,5,1.2,0)
    # Camera/background displacement is removed with the median flow vector.
    flow=flow-np.median(flow.reshape(-1,2),axis=0)
    magnitude=np.linalg.norm(flow,axis=2)
    return float(np.percentile(magnitude,90))


def scan(source,model,profile,cache,stop,progress):
    key=hashlib.sha256(json.dumps(['broadcast-discovery-v1',source.fingerprint,model.digest,profile],sort_keys=True).encode()).hexdigest()
    if cache.complete(key):
        for item in cache.rows(key):
            if stop.is_set():raise Cancelled()
            yield item
        return
    last=-1.0
    for t,row in cache.rows(key):last=t;yield t,row
    previous=None;clip=deque(maxlen=16);last_ocr_slot=-1
    ocr=ScoreboardOCR(profile)
    stream=frames(source.path,fps=15,width=320,height=180)
    try:
        for i,(t,rgb) in enumerate(stream):
            if stop.is_set():raise Cancelled()
            clip.append(rgb)
            gate,field,cues=geometry(rgb,profile)
            energy=motion_energy(previous,rgb,profile)
            cut=previous is not None and float(np.abs(rgb.astype(np.float32)-previous).mean()/255)>.18
            previous=rgb
            if t<=last+1e-5:
                last_ocr_slot=int(t//2);continue
            row=dict(gate=gate,field=field,motion=energy,cut=bool(cut),cues=cues,
                     frame_hash=hashlib.sha256(rgb.tobytes()).hexdigest())
            if len(clip)==16 and (i-15)%16==0:row['action']=model.predict(list(clip))
            slot=int(t//2)
            if slot!=last_ocr_slot:
                raw=run('ffmpeg',['-v','error','-nostdin','-ss',str(t),'-i',source.path,
                    '-frames:v','1','-vf','scale=1280:720','-threads','1','-f','rawvideo','-pix_fmt','rgb24','-'])
                if len(raw)==1280*720*3:row['ocr']=ocr.read(np.frombuffer(raw,np.uint8).reshape(720,1280,3))
                last_ocr_slot=slot
            cache.put(key,t,row);progress(t/source.duration)
            yield t,row
        cache.finish(key)
    finally:stream.close()


def motion_peaks(rows):
    """Adaptive motion bursts, not scene cuts or preset pitch timestamps."""
    if len(rows)<8:return []
    values=np.array([r['motion'] for _,r in rows])
    smooth=np.convolve(values,np.ones(3)/3,mode='same')
    baseline=float(np.median(smooth));mad=float(np.median(np.abs(smooth-baseline)))
    threshold=max(baseline+3*mad,baseline*1.8,.12)
    peaks=[i for i in range(1,len(rows)-1) if smooth[i]>=threshold and smooth[i]>=smooth[i-1] and smooth[i]>smooth[i+1]]
    selected=[]
    for i in sorted(peaks,key=lambda i:smooth[i],reverse=True):
        if all(abs(rows[i][0]-rows[j][0])>=2.5 for j in selected):selected.append(i)
    return [(i,float(smooth[i]),threshold) for i in sorted(selected)]


def candidates(session,observations,model_digest):
    """Compact metadata only; no decoded frames survive scan iteration."""
    settings=observations['profile']['discovery'];rows=observations['rows']
    identity=IdentityContext(session.player)
    identity_at=[]
    for t,row in rows:identity_at.append(identity.update(t,row.get('ocr',{})))
    # Isolated one-frame gate failures are bridged; hard cuts remain evidence.
    mask=np.array([r['gate'] for _,r in rows],bool)
    for i in range(1,len(mask)-1):
        if mask[i-1] and mask[i+1] and not rows[i][1]['cut']:mask[i]=True
    groups=[];begin=None
    for i,yes in enumerate([*mask,False]):
        if yes and begin is None:begin=i
        if not yes and begin is not None:
            if rows[i-1][0]-rows[begin][0]>=.4:groups.append((begin,i))
            begin=None
    events=[];rejections=[]
    actions=[(i,r['action']) for i,(_,r) in enumerate(rows) if 'action' in r]
    for begin,end in groups:
        part=rows[begin:end]
        for peak,energy,threshold in motion_peaks(part):
            index=begin+peak;time=rows[index][0]
            nearby=[a for i,a in actions if abs(rows[i][0]-time)<=1.6]
            if not any(a['baseball'] for a in nearby):
                rejections.append(dict(time=time,reason='motion_without_baseball_model_support'));continue
            readings={}
            for i in range(max(0,index-90),min(len(rows),index+45)):
                readings.update({k:v for k,v in rows[i][1].get('ocr',{}).items() if v.strip()})
            if replay_text(readings):
                rejections.append(dict(time=time,reason='explicit_replay_overlay'));continue
            certain,evidence=identity_at[index]
            if not certain:
                # OCR immediately after release can resolve the same short action.
                for j in range(index,min(len(rows),index+45)):
                    if identity_at[j][0]:certain,evidence=identity_at[j];break
            # Adaptive onset: backtrack from delivery to the preceding low-motion
            # posture. It may include waiting; never claim a frame-exact set pose.
            lower=max(0,peak-90)
            low=float(np.median([r['motion'] for _,r in part]))
            onset=peak
            while onset>lower and part[onset-1][1]['motion']>low:onset-=1
            start=part[max(0,onset-3)][0]
            if peak-onset<3:start=part[0][0]
            stop_index=end
            # Retain downstream fielding/running camera shots. A camera cut
            # alone never ends an in-play extension.
            while stop_index<len(rows) and not mask[stop_index] and rows[stop_index][1]['field']>=settings.get('field_extension_fraction',.55):
                stop_index+=1
            finish=rows[stop_index][0] if stop_index<len(rows) else sum(s.duration for s in session.sources)
            if finish<=start:continue
            warnings=['방송 레이아웃에 의존하는 실험 후보: 전수 검출 성능 미평가',
                '세트/반환 송구/후속 플레이 종료는 검수 필요',
                'R3D 일반 동작 점수는 투구 확률 또는 선수 식별 확률이 아님']
            if not certain:warnings.append('대상 선수 미확정: OCR 식별 근거 부족')
            if stop_index>end:warnings.append('후속 수비·주루 보존을 위해 필드 장면까지 확장; 종료 여유 검수 필요')
            proof=[DetectionEvidence('localized_motion',json.dumps(dict(energy=energy,adaptive_threshold=threshold)),time,'optical-flow-v1'),
                DetectionEvidence('action_model',json.dumps(nearby,ensure_ascii=False),time,model_digest),
                DetectionEvidence('broadcast_camera',json.dumps(rows[index][1]['cues']),time),
                DetectionEvidence('start','adaptive motion onset within broadcast pitch view',start),
                DetectionEvidence('end','field-scene extension until non-field camera; not semantic play-end proof',finish)]
            proof += [DetectionEvidence(k,v,time) for k,v in evidence]
            proof += [DetectionEvidence('ocr:'+k,v,time) for k,v in readings.items()]
            e=PitchEvent(session.id,session.split(start,finish),start,finish,
                pitcher_id=session.player.id if certain and session.player.role=='pitcher' else None,
                batter_id=session.player.id if certain and session.player.role=='batter' else None,
                inning=readings.get('inning'),number=len(events)+1,evidence=proof,warnings=warnings)
            events.append(e)
    # Multiple motion bursts in one camera must not produce overlapping output.
    events.sort(key=lambda e:e.timeline_start)
    for a,b in zip(events,events[1:]):
        if a.timeline_end>b.timeline_start:
            a.timeline_end=b.timeline_start;a.segments=session.split(a.timeline_start,a.timeline_end)
            a.warnings.append('동일 중계 앵글의 다음 동작 후보 앞에서 경계 분리: 검수 필요')
    return events,rejections


def discover(session,manifest,profile,cache_path,stop=None,progress=lambda stage,value:None):
    session.validate()
    if not session.sources:raise ValueError('원본 영상 없음')
    if any(e.history or e.status!='REVIEW_REQUIRED' for e in session.events):raise ValueError('검수 프로젝트는 별도 분석 프로젝트로 보존하세요')
    if not profile.get('discovery'):raise ValueError('중계 카메라/동작 영역 프로필 필요')
    model=ActionModel(manifest);stop=stop or threading.Event();cache=Cache(cache_path)
    rows=[];total=sum(s.duration for s in session.sources)
    try:
        for source in session.sources:
            if fingerprint(source.path)!=source.fingerprint:raise ValueError('원본 변경 감지')
            for t,row in scan(source,model,profile,cache,stop,lambda v:progress('동작 모델·OCR·움직임 분석',(source.offset+v*source.duration)/total)):
                rows.append((source.offset+t,row))
    finally:cache.close()
    session.events,rejected=candidates(session,dict(profile=profile,rows=rows),model.digest)
    session.appearances=group_appearances(session.events)
    session.analysis=dict(backend=model.info['backend'],model_sha256=model.digest,
        status='EXPERIMENTAL_REQUIRES_REVIEW',performance='NOT_EVALUATED',
        rejected=rejected,source_count=len(session.sources),sampled_observations=len(rows))
    session.validate();progress('자동 후보 생성 완료 — 정답 대조 필요',1)
    return session
