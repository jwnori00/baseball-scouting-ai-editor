import numpy as np
from bsae.export import framing


def test_union_preserves_late_fullscreen_and_caption(monkeypatch):
    small=np.zeros((360,640,3),np.uint8);small[145:220,250:390]=150
    caption=small.copy();caption[300:315,50:500]=200
    def detect(images):
        monkeypatch.setattr(framing,'frames',lambda *a,**k:enumerate(images))
        return framing.detect_crop('unused',0,3,dict(width=1920,height=1080))
    crop=detect([small,caption])
    w,h,x,y=crop
    assert x<=150 and y+h>=945
    assert detect([small,np.full_like(small,100)]) is None
    assert detect([np.zeros_like(small)]) is None


def test_real_export_expands_padded_video_and_can_disable(tmp_path):
    import json
    from bsae.ingest.media import run,add_sources,frames
    from bsae.core.models import GameSession,PlayerIdentity,PitchEvent
    from bsae.core.review import review
    from bsae.export.render import export
    path=tmp_path/'padded.mp4'
    run('ffmpeg',['-v','error','-f','lavfi','-i','color=c=red:s=160x90:r=30:d=1',
        '-vf','pad=640:360:240:134','-c:v','libx264','-pix_fmt','yuv420p',path])
    s=GameSession('Synthetic border test',PlayerIdentity('Test','pitcher','T','1'),add_sources([path]))
    event=PitchEvent(s.id,s.split(0,1),0,1,number=1);s.events=[event]
    review(s,event.id,'APPROVED',confirm_identity=True)
    for enabled in (True,False):
        target=tmp_path/str(enabled)
        export(s,target,auto_frame=enabled)
        _,image=next(frames(target/'all_0001.mp4',fps=1,width=640,height=360))
        coverage=np.mean(image[:,:,0]>100)
        assert coverage>.75 if enabled else coverage<.10
        data=json.loads((target/'framing.json').read_text())
        assert bool(data['segments'][0]['crop'])==enabled
