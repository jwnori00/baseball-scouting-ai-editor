"""Try layouts on representative frames; ambiguity never confirms a player."""
from pathlib import Path
import sys
import numpy as np
from bsae.ingest.media import run,frames
from .rules import load_profile,camera_cues,canonical_team
from .scoreboard import ScoreboardOCR,normalize,text_regions


def select_profile(source,stop=None):
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))/'profiles'
    old=load_profile(root/'lmb-telemetry-v1.json');generic=load_profile(root/'multi-broadcast-scene-v1.json')
    sampled=[];anchors=0;positive=0;proposals=[];ranked=[]
    # Read a bounded opening window sequentially; do not miss short pitch shots
    # merely because five uniform seek points landed on crowd/bench closeups.
    stream=frames(source.path,fps=1,width=320,height=180,end=min(source.duration,180))
    try:
        for t,rgb in stream:
            if stop is not None and stop.is_set():
                from .pipeline import Cancelled
                raise Cancelled()
            cues=camera_cues(rgb,generic);old_cues=camera_cues(rgb,old)
            positive+=int(cues['pitch_view']);sampled.append(t)
            score=max(cues['scene_margin'],1.0 if old_cues['pitch_view'] else -100)
            ranked.append((score,t))
        # At most 180 scalars, no movie or decoded frame list in memory.
    finally:stream.close()
    selected=[]
    for score,t in sorted(ranked,reverse=True):
        if all(abs(t-other)>=5 for other in selected):selected.append(t)
        if len(selected)>=6:break
    for t in selected:
        raw=run('ffmpeg',['-v','error','-ss',str(t),'-i',source.path,'-frames:v','1','-vf','scale=1280:720','-f','rawvideo','-pix_fmt','rgb24','-'])
        if len(raw)!=1280*720*3:continue
        rgb=np.frombuffer(raw,np.uint8).reshape(720,1280,3)
        if camera_cues(rgb,old)['pitch_view']:
            readings=ScoreboardOCR(dict(old,regions={k:v for k,v in old['regions'].items() if k.endswith('_team')})).read(rgb)
            if any(canonical_team(value,old) in old.get('team_aliases',{}) for value in readings.values() if normalize(value)):anchors+=1
        if not proposals:
            try:proposals=text_regions(rgb)
            except RuntimeError as exc:proposals=[dict(error=str(exc),semantic_role='UNCONFIRMED')]
    chosen=old if anchors>=2 else generic
    assessment=dict(strategy='recognized LMB team/layout anchors' if anchors>=2 else 'generic experimental scene model',representative_frames=len(sampled),scene_positive_frames=positive,lmb_anchor_frames=anchors,
        confidence='LAYOUT_ANCHORED' if anchors>=2 else 'UNCERTAIN',status='REVIEW_REQUIRED' if anchors>=2 or positive else 'UNRECOGNIZED_LAYOUT',text_proposals=proposals,identity='UNCONFIRMED',notice='문자 영역은 이름·팀·스코어보드로 자동 확정되지 않았습니다. 사용자 영역 보정이 필요할 수 있습니다.')
    return chosen,assessment
