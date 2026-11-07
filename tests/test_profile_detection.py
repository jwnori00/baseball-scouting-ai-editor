import numpy as np
from bsae.core.models import VideoSource


def test_unrecognized_layout_never_claims_identity(monkeypatch):
    from bsae.vision import profile_detection as detection
    monkeypatch.setattr(detection,'frames',lambda *a,**k:(row for row in [(0,np.zeros((180,320,3),np.uint8))]))
    monkeypatch.setattr(detection,'camera_cues',lambda rgb,p:dict(pitch_view=False,scene_margin=-1))
    monkeypatch.setattr(detection,'run',lambda *a,**k:bytes(1280*720*3))
    monkeypatch.setattr(detection,'text_regions',lambda *a,**k:[])
    profile,assessment=detection.select_profile(VideoSource('unused',30,'synthetic'))
    assert profile['camera']['mode']=='learned_scene'
    assert assessment['status']=='UNRECOGNIZED_LAYOUT'
    assert assessment['identity']=='UNCONFIRMED'
