"""Streaming broadcast-rule discovery. No learned action veto or pitch timetable.

Camera layout, camera-compensated local flow and OCR supply independent evidence.
Unknown identity/endpoints remain candidates, not claims of verified plays.
"""
from collections import deque
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import re
import threading
import time
import cv2
import numpy as np
from bsae.core.models import DetectionEvidence,PitchEvent,PlateAppearance,atomic_json
from bsae.ingest.media import frames,fingerprint,run,tool
from .cache import Cache
from .pipeline import Cancelled
from .scoreboard import ScoreboardOCR,normalize

VERSION='broadcast-rules-v2'


def load_profile(path=None):
    import sys
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))
    path=Path(path) if path else root/'profiles'/'lmb-telemetry-v1.json'
    profile=json.loads(path.read_text(encoding='utf-8-sig'))
    for key in ('panel','content','pitcher','catcher'):
        box=profile['camera'][key]
        if len(box)!=4 or not 0<=box[0]<box[2]<=1 or not 0<=box[1]<box[3]<=1:raise ValueError('잘못된 중계 영역: '+key)
    if not 4<=profile.get('sampling_fps',10)<=30 or not .25<=profile.get('ocr_interval',2)<=10:raise ValueError('잘못된 샘플링 설정')
    if profile['camera'].get('mode')=='learned_scene':
        model_path=path.parent/profile['scene_model']
        if model_path.resolve().parent!=path.parent.resolve():raise ValueError('구도 모델은 설정 폴더 안에 있어야 합니다')
        if hashlib.sha256(model_path.read_bytes()).hexdigest()!=profile['scene_sha256']:raise ValueError('구도 모델 체크섬 불일치')
        from .scene import validate
        profile['scene_weights']=validate(json.loads(model_path.read_text(encoding='utf-8')))
    ScoreboardOCR(profile)
    return profile


def region(rgb,box):
    h,w=rgb.shape[:2];a,b,c,d=box
    return rgb[int(b*h):int(d*h),int(a*w):int(c*w)]


def camera_cues(rgb,profile):
    camera=profile['camera'];panel=region(rgb,camera['panel'])
    hsv=cv2.cvtColor(region(rgb,camera['content']),cv2.COLOR_RGB2HSV)
    dark=float((cv2.cvtColor(panel,cv2.COLOR_RGB2GRAY)<75).mean())
    green=(hsv[:,:,0]>=25)&(hsv[:,:,0]<=90)&(hsv[:,:,1]>40)&(hsv[:,:,2]>35)
    soil=(hsv[:,:,0]<30)&(hsv[:,:,1]>40)&(hsv[:,:,2]>35)&(hsv[:,:,2]<235)
    pitch_view=bool(dark>=camera['panel_dark_min'] and green.mean()>=camera['grass_min'])
    if camera.get('mode')=='field_geometry':
        field=(green|soil).astype(np.float32)
        upper=float(region(field,[0.10,0.12,0.90,0.36]).mean())
        lower_left=float(region(field,[0.06,0.58,0.27,0.92]).mean())
        lower_right=float(region(field,[0.78,0.58,0.96,0.92]).mean())
        uniform=((hsv[:,:,1]<65)&(hsv[:,:,2]>140)).astype(np.uint8)
        _,_,components,_=cv2.connectedComponentsWithStats(region(uniform,[.25,.25,.78,.96]))
        largest=max(components[1:,cv2.CC_STAT_AREA],default=0)/float(rgb.shape[0]*rgb.shape[1])
        pitch_view=bool(upper<=camera['upper_field_max'] and min(lower_left,lower_right)>=camera['side_field_min'] and largest<=camera.get('largest_uniform_max',1))
    if camera.get('mode')=='manual_geometry':
        # Explicit user camera layout, not automatic player identification.
        pitch_view=bool(float(region(rgb,camera['content']).std())>8)
    extra={}
    if camera.get('mode')=='learned_scene':
        from .scene import margin
        score=margin(region(rgb,camera['content']),profile['scene_weights']);threshold=profile['scene_weights']['threshold']
        pitch_view=bool(score>=threshold)
        extra=dict(scene_margin=score,scene_threshold=threshold)
    return dict(pitch_view=pitch_view,**extra,
        dark=dark,grass=float(green.mean()),field=float((green|soil).mean()))


def local_motion(previous,rgb,box):
    if previous is None:return 0.0
    a=cv2.cvtColor(region(previous,box),cv2.COLOR_RGB2GRAY)
    b=cv2.cvtColor(region(rgb,box),cv2.COLOR_RGB2GRAY)
    flow=cv2.calcOpticalFlowFarneback(a,b,None,.5,3,15,3,5,1.2,0)
    # Remove median camera displacement rather than counting a pan as delivery.
    flow-=np.median(flow.reshape(-1,2),axis=0)
    return float(np.percentile(np.linalg.norm(flow,axis=2),90))


def parse_inning(value):
    match=re.fullmatch(r'\s*([1-9][0-9]?)\s*(?:회|回)?\s*(초|말|表|裏|TOP|BOT|BOTTOM|T|B|▲|△|▼|▽)?\s*',value.upper())
    if not match:return None
    number,half=match.groups()
    return number+('초' if half in ('초','表','TOP','T','▲','△') else '말' if half else '')


def parse_count(value):
    text=value.strip(' |[]_').upper().replace('O','0').replace('I','1').replace('L','1')
    m=re.fullmatch(r'\s*([0-4])\s*[-:]?\s*([0-3])\s*',text)
    return tuple(map(int,m.groups())) if m else None


def canonical_team(value,profile):
    n=normalize(value)
    for canonical,aliases in profile.get('team_aliases',{}).items():
        if n in {normalize(v) for v in [canonical,*aliases]}:return canonical
    return n


def clean_name(value):
    words=re.findall(r'[^\W\d_]+',value,flags=re.UNICODE)
    # Thin graphic borders in these ROIs are sometimes OCR'd as i/f/if.
    # Do not drop general suffixes (Jr, II, etc.) or initials in short names.
    while len(words)>=3 and words[-1].lower() in ('i','l','f','if'):words.pop()
    while len(words)>=3 and words[0].lower() in ('i','l','if'):words.pop(0)
    return ' '.join(words)


def compatible_name(a,b):
    a,b=normalize(clean_name(a)),normalize(clean_name(b))
    return bool(a and b) and (a==b or (min(len(a),len(b))>=6 and (a.startswith(b) or b.startswith(a) or a.endswith(b) or b.endswith(a))))


def name_matches(value,player):
    n=normalize(clean_name(value))
    return bool(n) and n in {normalize(v) for v in [player.name,*player.aliases] if v.strip()}


class Identity:
    def __init__(self,player,profile):
        self.player=player;self.profile=profile;self.fields={};self.confirmation=None

    def update(self,t,readings):
        prefix=self.player.role+'_';name=clean_name(readings.get(prefix+'name',''))
        if readings.get(prefix+'identity_conflict'):
            self.fields={};self.confirmation=None
            return dict(state='conflict',proof=[('conflict',readings[prefix+'identity_conflict'])])
        if self.player.role=='batter' and self.profile.get('auto_batter_text') and name_matches(name,self.player) and self.player.jersey and readings.get('batter_jersey') and readings['batter_jersey']!=self.player.jersey:
            self.fields={};self.confirmation=None
            return dict(state='conflict',proof=[('caption_number_mismatch',readings['batter_jersey'])])
        old=self.fields.get(prefix+'name')
        if name and old and not compatible_name(name,old[1]):
            self.fields={};self.confirmation=None
        for key,value in readings.items():
            if key.startswith(prefix) and value.strip():
                if key.endswith('_name'):
                    value=clean_name(value)
                    existing=self.fields.get(key)
                    if existing and compatible_name(value,existing[1]) and len(normalize(value))<len(normalize(existing[1])):continue
                self.fields[key]=(t,value.strip())
        self.fields={k:v for k,v in self.fields.items() if t-v[0]<=6}
        values={k:v[1] for k,v in self.fields.items()}
        observed=values.get(prefix+'name','')
        match=name_matches(observed,self.player)
        proof=[]
        if match:proof.append(('name',observed))
        if normalize(self.player.team) and normalize(values.get(prefix+'team','')) and canonical_team(values.get(prefix+'team',''),self.profile)==canonical_team(self.player.team,self.profile):proof.append(('team',values[prefix+'team']))
        if self.player.jersey and values.get(prefix+'jersey','')==self.player.jersey:proof.append(('jersey',self.player.jersey))
        if match and len(proof)>=2:self.confirmation=(t,proof)
        if self.confirmation and t-self.confirmation[0]<=20:return dict(state='target',proof=self.confirmation[1])
        # Nonmatching text can be OCR noise. Preserve it, never assert a substitute
        # from one fuzzy name. Another player's candidate requires fresh name+team.
        if observed and not match and len(normalize(observed))>=(2 if any(ord(c)>127 for c in observed) else 8) and values.get(prefix+'team'):
            return dict(state='other_evidence' if self.player.role=='batter' else 'other_or_ocr_error',proof=[('observed_name',observed),('observed_team',values[prefix+'team'])])
        return dict(state='unconfirmed',proof=proof)


def source_cache_key(source,profile):
    parts=[VERSION,source.fingerprint,profile]
    if profile.get('regions') or profile.get('auto_batter_text'):parts.append('tsv-quote-none-v1')
    return hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest()


def scan(source,profile,cache,stop,progress):
    fps=profile['sampling_fps'];interval=profile['ocr_interval']
    key=source_cache_key(source,profile)
    last=None
    for t,row in cache.rows(key):
        if stop.is_set():raise Cancelled()
        last=t;yield t,row
    if cache.complete(key):return
    previous=None;last_slot=-1
    start=max(0,round((last-1/fps)*fps)/fps) if last is not None else 0
    ocr=ScoreboardOCR(profile)
    stream=frames(source.path,fps=fps,width=320,height=180,start=start)
    try:
        for t,rgb in stream:
            t=round(t*fps)/fps
            if stop.is_set():raise Cancelled()
            cues=camera_cues(rgb,profile)
            row=dict(**cues,motion=local_motion(previous,rgb,profile['camera']['pitcher']),
                catcher_motion=local_motion(previous,rgb,profile['camera']['catcher']),
                cut=previous is not None and float(np.abs(rgb.astype(np.float32)-previous).mean()/255)>.18,
                signature=hashlib.sha256(rgb.tobytes()).hexdigest())
            previous=rgb
            slot=int((t+1e-5)//interval)
            if last is not None and t<=last+1e-5:last_slot=slot;continue
            if slot!=last_slot and (profile.get('regions') or profile.get('auto_batter_text')):
                raw=run('ffmpeg',['-v','error','-nostdin','-ss',str(t),'-i',source.path,'-frames:v','1',
                    '-vf','scale=1280:720','-threads','1','-f','rawvideo','-pix_fmt','rgb24','-'])
                if len(raw)!=1280*720*3:raise RuntimeError('OCR 프레임 디코딩 실패')
                image=np.frombuffer(raw,np.uint8).reshape(720,1280,3)
                row['ocr']=ocr.read(image);row['ocr_time']=t
                if profile.get('auto_batter_text'):
                    from .scoreboard import text_regions
                    row['text_blocks']=text_regions(image,language=profile['language'])
            last_slot=slot
            cache.put(key,t,row);progress(t/source.duration)
            yield t,row
        cache.finish(key)
    finally:stream.close()


def peaks(rows,profile):
    if len(rows)<8:return []
    values=np.array([r['motion'] for _,r in rows]);smooth=np.convolve(values,np.ones(3)/3,'same')
    low=smooth[smooth<=np.median(smooth)]
    base=float(np.quantile(smooth,.2));mad=float(np.median(np.abs(low-np.median(low))))
    # Short broadcast shots may consist almost entirely of delivery. Estimate
    # quiet motion from the lower half, not the median of the whole action.
    threshold=max(base+3*mad,float(smooth.max())*.40,profile.get('minimum_motion',.12))
    edge=max(1,int(.3*profile['sampling_fps']))
    choices=[i for i in range(edge,len(rows)-edge) if smooth[i]>=threshold and smooth[i]>=smooth[i-1] and smooth[i]>smooth[i+1]]
    selected=[]
    for i in sorted(choices,key=lambda i:smooth[i],reverse=True):
        if all(abs(rows[i][0]-rows[j][0])>=profile.get('minimum_motion_separation',2.5) for j in selected):selected.append(i)
    merged=[]
    quiet_threshold=max(base+1.5*mad,.20)
    for i in sorted(selected):
        if merged:
            previous=merged[-1][0]
            longest=run=0
            for value in smooth[previous+1:i]:
                run=run+1 if value<=quiet_threshold else 0
                longest=max(longest,run)
            # Windup, release, receiving the return and settling are one motion
            # episode unless a genuinely quiet preparation interval intervenes.
            if longest<max(3,int(.8*profile['sampling_fps'])):
                merged[-1]=(previous,max(merged[-1][1],float(smooth[i])),threshold,base)
                continue
        merged.append((i,float(smooth[i]),threshold,base))
    return merged


def replay_marker(readings):
    return normalize(readings.get('replay','')) in ('replay','repeticion','repeticao')


class Assembly:
    """Bounded episode buffer; no whole-game frame/metadata list."""
    def __init__(self,session,profile):
        self.session=session;self.profile=profile;self.identity=Identity(session.player,profile)
        self.episode=[];self.pending=[];self.recent=deque();self.events=[];self.gaps=[]
        self.last_t=0.;self.gap_start=0.;self.last_view=None;self.signatures={};self.ocr={};self.camera_episodes=0
        self.caption_samples=0;self.caption_hits=0;self.caption_anchors=[]

    def feed(self,t,row):
        self.last_t=t
        if 'text_blocks' in row:
            self.caption_samples+=1
            from .batter_text import interpret
            readings=dict(row.get('ocr',{}));automatic=interpret(row['text_blocks'],self.session.player)
            for key,value in automatic.items():
                if key not in readings or not readings[key]:readings[key]=value
                elif key=='batter_name' and not compatible_name(readings[key],value):readings['batter_identity_conflict']='ROI and full-frame names disagree'
            row=dict(row,ocr=readings)
            if automatic.get('batter_name_hint'):
                self.caption_hits+=1
                if len(self.caption_anchors)<1000:self.caption_anchors.append(dict(time=t,name=automatic['batter_name_hint'],role_text=automatic.get('batter_role_text',''),team=automatic.get('batter_team',''),caption_jersey=automatic.get('batter_jersey',''),state='caption_evidence_requires_review'))
        if row.get('ocr'):
            for key,value in row['ocr'].items():
                if value.strip():self.ocr[key]=(t,value)
        self.ocr={k:v for k,v in self.ocr.items() if t-v[0]<=6}
        row=dict(row,identity=self.identity.update(t,row.get('ocr',{})),readings={k:v[1] for k,v in self.ocr.items()})
        self.recent.append((t,row))
        while self.recent and t-self.recent[0][0]>8:self.recent.popleft()
        if row['pitch_view']:
            if self.last_view is None:
                if t-self.gap_start>=self.profile.get('coverage_gap_seconds',15):self.gaps.append(dict(start=self.gap_start,end=t,reason='투구 구도 미관측: 광고·다른 앵글 또는 누락 가능'))
                self.last_view=t;self.camera_episodes+=1
            if self.pending and not self.episode:self.finalize_pending(t,'next_pitch_camera')
            self.episode.append((t,row))
            limit=self.profile.get('max_episode_seconds',60)
            if self.episode[-1][0]-self.episode[0][0]>=limit:
                self.extract(self.episode,chunk=True)
                self.episode=[item for item in self.episode if t-item[0]<=8]
        else:
            if self.episode:
                self.extract(self.episode);self.episode=[];self.last_view=None;self.gap_start=t
            if self.pending:
                if row['field']>=self.profile['camera']['field_extension_min']:
                    for event in self.pending:event['extended']=True
                else:self.finalize_pending(t,'non_field_camera')

    def extract(self,rows,chunk=False):
        for index,energy,threshold,baseline in peaks(rows,self.profile):
            t,row=rows[index]
            if any(abs(t-float(e.evidence[0].time))<self.profile.get('minimum_motion_separation',2.5) for e in self.events):continue
            if any(abs(t-e['peak'])<self.profile.get('minimum_motion_separation',2.5) for e in self.pending):continue
            start=index
            while start>0 and rows[start-1][1]['motion']>baseline:start-=1
            start=max(0,start-int(self.profile.get('preparation_padding_seconds',.75)*self.profile['sampling_fps']))
            # Include earliest visible preparation when onset is ambiguous.
            if index-start<3:start=0
            identity=row['identity']
            if identity['state']!='target' and self.session.player.role!='batter':
                for _,following in rows[index:index+int(4*self.profile['sampling_fps'])]:
                    if following['identity']['state']=='target':identity=following['identity'];break
            readings=dict(row['readings'])
            for following_time,following in rows[index:index+int(4*self.profile['sampling_fps'])]:
                for key,value in following.get('ocr',{}).items():
                    if self.session.player.role=='batter' and following_time>t and key.startswith('batter_'):continue
                    if not value.strip():continue
                    if key.endswith('_name') and compatible_name(value,readings.get(key,'')) and len(normalize(clean_name(value)))<len(normalize(clean_name(readings[key]))):continue
                    readings[key]=clean_name(value) if key.endswith('_name') else value
            signature=[r['signature'] for _,r in rows[max(0,index-5):index+6]]
            duplicate=len(set(signature))>=4 and len(signature)>=8 and tuple(signature) in self.signatures
            if len(signature)>=8:self.signatures[tuple(signature)]=t
            if len(self.signatures)>5000:self.signatures.pop(next(iter(self.signatures)))
            catcher=max(r['catcher_motion'] for _,r in rows[index:index+int(1.5*self.profile['sampling_fps'])])
            self.pending.append(dict(start=rows[start][0],peak=t,energy=energy,threshold=threshold,catcher=catcher,at_camera_start=start<=1,
                identity=identity,readings=readings,scene_margin=row.get('scene_margin'),extended=False,replay=replay_marker(readings) or duplicate,
                signature_duplicate=duplicate,chunk=chunk))
        if chunk and self.pending:
            # Commit only bursts fully behind the overlap; still conservative.
            self.finalize_pending(rows[-1][0]-8,'continuous_camera_chunk',before=rows[-1][0]-8)

    def finalize_pending(self,end,reason,before=None):
        remaining=[]
        for item in self.pending:
            if before is not None and item['peak']>=before:remaining.append(item);continue
            a=item['start'];b=end
            if b<=a:continue
            identity=item['identity'];readings=item['readings']
            warnings=['컷 경계·반환 송구·후속 플레이 종료는 검수 필요',
                '방송 레이아웃 규칙 기반 후보; 일반 중계 전체 성능 미평가']
            if self.profile['camera'].get('mode')=='manual_geometry':warnings.append('사용자 지정 고정/이동 촬영 영역: 실영상 미검증·선수 추적 미지원. 모든 후보 검수 필요')
            if self.profile['camera'].get('mode')=='learned_scene':warnings.append('학습된 구도 판별일 뿐 투구·선수·리플레이·플레이 종료 자동 검증이 아닙니다')
            if identity['state']!='target':warnings.append('대상 선수 신원 미확정; 이름·팀·등번호 원본 대조 필요')
            if item['extended']:warnings.append('수비·주루 보존을 위해 다음 필드 장면까지 확장; 불필요한 여유 검수 필요')
            if item['chunk']:warnings.append('장시간 동일 앵글: 연속 구도 경계 검수 필요')
            event_type='pitch_candidate'
            if item['catcher']<.20:
                event_type='pitch_or_pickoff_candidate';warnings.append('포수 반응 근거 약함: 투구·견제 구별 검수 필요')
            if item['at_camera_start']:warnings.append('준비동작 전에 방송 화면이 전환됐을 가능성: 가장 이른 확인 장면 사용')
            if identity['state']=='other_or_ocr_error' and self.session.player.role!='batter':event_type='other_player_or_ocr_error'
            if item['replay']:event_type='replay';warnings.append('명시적 리플레이 표식 또는 동일 프레임 시퀀스')
            proof=[DetectionEvidence('localized_motion',json.dumps(dict(energy=item['energy'],threshold=item['threshold'])),item['peak'],VERSION),
                DetectionEvidence('pitch_camera',self.profile['camera'].get('mode','telemetry_panel')+' + field geometry; not a pitch by itself',a,VERSION),
                DetectionEvidence('identity_state',identity['state'],item['peak']),
                DetectionEvidence('end',reason,b,VERSION)]
            if item.get('scene_margin') is not None:proof.append(DetectionEvidence('scene_margin',str(item['scene_margin'])+' (uncalibrated; not confidence)',item['peak'],VERSION))
            proof += [DetectionEvidence(k,v,item['peak']) for k,v in identity['proof']]
            proof += [DetectionEvidence('ocr:'+k,v,item['peak']) for k,v in readings.items() if v]
            event=PitchEvent(self.session.id,self.session.split(a,b),a,b,
                pitcher_id=self.session.player.id if identity['state']=='target' and self.session.player.role=='pitcher' else None,
                batter_id=self.session.player.id if identity['state']=='target' and self.session.player.role=='batter' else None,
                inning=parse_inning(readings.get('inning','')),event_type=event_type,evidence=proof,warnings=warnings,
                status='EXCLUDED' if item['replay'] else 'REVIEW_REQUIRED')
            self.events.append(event)
        self.pending=remaining

    def finish(self,end):
        if self.last_view is None and end-self.gap_start>=self.profile.get('coverage_gap_seconds',15):
            self.gaps.append(dict(start=self.gap_start,end=end,reason='투구 구도 미관측 구간: 별도 확인 필요'))
        if self.episode:self.extract(self.episode);self.episode=[]
        if self.pending:
            self.finalize_pending(end,'source_end_unconfirmed')
            self.events[-1].warnings.append('원본 끝으로 실제 플레이 종료 확인 불가')
        self.events.sort(key=lambda e:e.timeline_start)
        merged=[]
        for event in self.events:
            if merged and abs(event.evidence[0].time-merged[-1].evidence[0].time)<self.profile.get('minimum_motion_separation',2.5):
                merged[-1].timeline_end=max(merged[-1].timeline_end,event.timeline_end)
                merged[-1].segments=self.session.split(merged[-1].timeline_start,merged[-1].timeline_end)
                continue
            if merged and merged[-1].timeline_end>event.timeline_start:
                if merged[-1].timeline_start==event.timeline_start:
                    event.timeline_start=(merged[-1].evidence[0].time+event.evidence[0].time)/2
                merged[-1].timeline_end=event.timeline_start
                merged[-1].segments=self.session.split(merged[-1].timeline_start,merged[-1].timeline_end)
                event.segments=self.session.split(event.timeline_start,event.timeline_end)
                merged[-1].warnings.append('다음 동작 후보 앞에서 구간 분리: 반환 송구 확인 필요')
            merged.append(event)
        for i,event in enumerate(merged,1):event.number=i
        return merged


def group_plates(events):
    result=[];previous=None
    for event in events:
        event.plate_id=None
        if event.event_type in ('replay','pickoff'):previous=None;continue
        readings={e.kind[4:]:e.value for e in event.evidence if e.kind.startswith('ocr:')}
        batter=clean_name(readings.get('batter_name',''))
        inning=event.inning
        count=parse_count(readings.get('count',''))
        new=not result or previous is None
        if not batter:
            event.warnings.append('타석 미배정: 타자 근거 없음; 후보마다 타석을 생성하지 않음')
            previous=None
            continue
        if previous:
            if batter and previous['batter'] and not compatible_name(batter,previous['batter']) and not (event.batter_id and event.batter_id==previous['batter_id']):new=True
            if event.timeline_start-previous['end']>90:
                new=True;event.warnings.append('장시간 간격: 타석 연속성 미확정')
            if inning and previous['inning'] and inning!=previous['inning']:new=True
            if count==(0,0) and previous['count'] not in (None,(0,0)):new=True
        if new:result.append(PlateAppearance([],event.batter_id,inning,batter_name=batter))
        result[-1].event_ids.append(event.id);event.plate_id=result[-1].id
        event.warnings.append('타석 그룹 제안: 타자 변경·타석 종료 검수 필요')
        previous=dict(batter_id=event.batter_id,end=event.timeline_end,batter=batter or (previous or {}).get('batter',''),inning=inning or (previous or {}).get('inning'),count=count or (previous or {}).get('count'))
    return result


def analyze_plays(session,profile=None,cache_path=None,stop=None,progress=lambda stage,value:None):
    from .batter_text import configure
    profile=configure(profile or load_profile(),session.player);session.validate()
    if cache_path is None:raise ValueError('분석 캐시 경로를 지정하세요')
    if not session.sources:raise ValueError('원본 영상 없음')
    if any(e.history or e.status=='APPROVED' for e in session.events):raise ValueError('검수 기록을 보존하려면 새 분석 프로젝트를 만드세요. 기존 캐시는 재사용됩니다.')
    stop=stop or threading.Event();cache=Cache(cache_path);assembler=Assembly(session,profile)
    total=sum(s.duration for s in session.sources);started=time.monotonic();last_progress=0;last_fraction=-1.;current_source=None;last_source_time=0;cache_usage=[]
    try:
        for source in session.sources:
            current_source=source.id;last_source_time=0
            key=source_cache_key(source,profile)
            cache_usage.append(dict(source_id=source.id,complete_before=cache.complete(key),cached_samples_before=cache.db.execute('SELECT COUNT(*) FROM frames WHERE key=?',(key,)).fetchone()[0]))
            if fingerprint(source.path)!=source.fingerprint:raise ValueError('원본 파일 변경 감지')
            for t,row in scan(source,profile,cache,stop,lambda v:None):
                last_source_time=t;assembler.feed(source.offset+t,row)
                now=time.monotonic()
                fraction=(source.offset+t)/total
                if now-last_progress>=.2 or fraction-last_fraction>=.02:
                    progress('자동 플레이 탐색 / OCR·캐시',fraction);last_progress=now;last_fraction=fraction
        session.events=assembler.finish(total)
        session.appearances=group_plates(session.events)
        previous_count=None;previous_event=None
        for event in session.events:
            text=next((p.value for p in event.evidence if p.kind=='ocr:pitch_count'),'')
            match=re.search(r'P\s*[:.]?\s*(\d{1,3})',text.upper())
            count=int(match.group(1)) if match else None
            if count is not None and previous_count is not None:
                if count-previous_count>1:
                    assembler.gaps.append(dict(start=previous_event.timeline_end,end=max(previous_event.timeline_end,event.timeline_start),reason='OCR 투구 수 증가에 비해 발견 후보 부족',suspected_missing=count-previous_count-1))
                elif count<previous_count:event.warnings.append('투구 수 초기화: 투수 교체 또는 OCR 오류 확인 필요')
            if count is not None:previous_count=count;previous_event=event
        session.analysis=dict(engine=VERSION,status='COMPLETE_REVIEW_REQUIRED',profile_id=profile['id'],camera_episodes=assembler.camera_episodes,
            performance='NOT_EVALUATED',analysis_seconds=time.monotonic()-started,cache_usage=cache_usage,coverage_gaps=assembler.gaps,
            limitations=['other layouts/innings/pickoffs/replays NOT_EVALUATED','endpoints are conservative, not semantic play-end proof'],
            counts=dict(all=len(session.events),target=sum(e.pitcher_id==session.player.id or e.batter_id==session.player.id for e in session.events),
                uncertain=sum(any(p.kind=='identity_state' and p.value!='target' for p in e.evidence) for e in session.events)))
        session.analysis['profile_snapshot']={k:v for k,v in profile.items() if k!='scene_weights'}
        session.analysis['identity_diagnostics']=dict(patch_version='batter-evidence-v1',full_frame_ocr_samples=assembler.caption_samples,name_hint_samples=assembler.caption_hits,caption_anchors_truncated=assembler.caption_hits>len(assembler.caption_anchors),ocr_evidence_events=sum(any(p.kind.startswith('ocr:') for p in e.evidence) for e in session.events),name_hint_events=sum(any(p.kind=='ocr:batter_name_hint' for p in e.evidence) for e in session.events),uniform_number_recognition='NOT_IMPLEMENTED',player_tracking='NOT_IMPLEMENTED',auto_batter_text=bool(profile.get('auto_batter_text')))
        session.analysis['caption_anchors']=assembler.caption_anchors
        if session.player.role=='batter' and not any(e.batter_id==session.player.id for e in session.events):
            session.analysis['recognition_status']='TARGET_BATTER_NOT_IDENTIFIED'
            session.analysis['status']='TARGET_BATTER_NOT_IDENTIFIED'
        session.analysis['input_type']=profile.get('input_type','broadcast')
        session.analysis['support_status']='UNVERIFIED_CAMERA_TYPE' if profile.get('input_type') in ('fixed_camera','moving_camera') else 'EXPERIMENTAL_BROADCAST'
        if session.analysis['support_status']=='UNVERIFIED_CAMERA_TYPE':session.analysis['status']='UNVERIFIED_INPUT_REVIEW_REQUIRED'
        if not session.events:
            session.analysis['recognition_status']='NO_CANDIDATES_REVIEW_REQUIRED'
            session.analysis['status']='NO_CANDIDATES_REVIEW_REQUIRED'
        session.validate();progress('후보 생성 완료 — 검수 필요',1)
        return session
    except BaseException as exc:
        session.analysis=dict(engine=VERSION,status='INTERRUPTED' if isinstance(exc,(Cancelled,KeyboardInterrupt)) else 'FAILED',error=str(exc),cache_preserved=True,source_id=current_source,last_source_time=last_source_time,cache_usage=cache_usage)
        raise
    finally:cache.close()


def export_diagnostics(session,destination):
    from bsae.evaluation import write_csv
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    atomic_json(destination/'analysis.json',session.analysis)
    atomic_json(destination/'detections.json',[asdict(e) for e in session.events])
    write_csv(destination/'detections.csv',[dict(id=e.id,pitch=e.number,plate=e.plate_id,start=e.timeline_start,
        end=e.timeline_end,status=e.status,type=e.event_type,player_confirmed=bool(e.pitcher_id or e.batter_id),
        review_required=e.status!='APPROVED') for e in session.events])
    return destination
