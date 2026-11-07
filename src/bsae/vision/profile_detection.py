"""Try layouts on representative frames; ambiguity never confirms a player."""
from pathlib import Path
import sys
import numpy as np
from bsae.ingest.media import run,frames
from .rules import load_profile,camera_cues,canonical_team
from .scoreboard import ScoreboardOCR,normalize,broadcast_text_regions


def select_profile(source,stop=None,player=None):
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[3]))/'profiles'
    old=load_profile(root/'lmb-telemetry-v1.json');generic=load_profile(root/'multi-broadcast-scene-v1.json')
    sampled=[];anchors=0;positive=0;proposals=[];ranked=[];text_frames=0;name_frames=0;identity_frames=0;pitcher_name_frames=0;batter_name_frames=0
    language=('kor+eng' if player and (player.league=='KBO' or any('가'<=c<='힣' for c in player.name)) else 'jpn+eng' if player and player.league=='NPB' else 'eng')
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
            readings=ScoreboardOCR(old if player else dict(old,regions={k:v for k,v in old['regions'].items() if k.endswith('_team')})).read(rgb)
            pitcher_name_frames+=bool(readings.get('pitcher_name'));batter_name_frames+=bool(readings.get('batter_name'))
            if player:
                from .rules import Identity
                identity_frames+=Identity(player,old).update(t,readings)['state']=='target'
            if any(canonical_team(value,old) in old.get('team_aliases',{}) for value in readings.values() if normalize(value)):anchors+=1
        try:
            blocks=broadcast_text_regions(rgb,language=language);text_frames+=bool(blocks)
            if not proposals:proposals=blocks
            if player:
                from .batter_text import interpret
                from .rules import Identity
                from .batter_text import configure
                inferred=interpret(blocks,player,pitch_view=camera_cues(rgb,generic)['pitch_view'])
                name_frames+=bool(inferred.get('batter_name_hint'))
                identity_frames+=Identity(player,configure(generic,player)).update(t,inferred)['state']=='target'
        except RuntimeError as exc:
            if not proposals:proposals=[dict(error=str(exc),semantic_role='UNCONFIRMED')]
    chosen=old if anchors>=2 else generic
    assessment=dict(strategy='recognized LMB team/layout anchors' if anchors>=2 else 'generic experimental scene model',representative_frames=len(sampled),scene_positive_frames=positive,lmb_anchor_frames=anchors,
        confidence='LAYOUT_ANCHORED' if anchors>=2 else 'UNCERTAIN',status='REVIEW_REQUIRED' if anchors>=2 or positive else 'UNRECOGNIZED_LAYOUT',text_proposals=proposals,identity='UNCONFIRMED',notice='문자 영역은 이름·팀·스코어보드로 자동 확정되지 않았습니다. 사용자 영역 보정이 필요할 수 있습니다.')
    assessment['preflight']=dict(pitch_camera_observed=positive>0,text_frames=text_frames,requested_name_hint_frames=name_frames,roi_pitcher_name_frames=pitcher_name_frames,roi_batter_name_frames=batter_name_frames,identity_evidence_frames=identity_frames,scope='bounded sample; absence is not proof of absence in full game',player_positions='PROFILE_GEOMETRY_NOT_AUTOMATICALLY_LOCALIZED')
    return chosen,assessment
