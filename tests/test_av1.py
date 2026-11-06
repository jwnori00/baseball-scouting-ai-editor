from pathlib import Path
import pytest
from bsae.ingest.media import probe,frames,add_sources,media_error
from bsae.core.models import GameSession,PlayerIdentity,PitchEvent
from bsae.core.review import review
from bsae.export.render import export


@pytest.mark.parametrize('bitdepth',[8,10])
def test_cpu_av1_input_frames_and_reviewed_export(bitdepth,tmp_path):
    source=Path(__file__).parent/'fixtures'/f'av1-{bitdepth}bit.mp4'
    v=next(v for v in probe(source)['streams'] if v['codec_type']=='video')
    assert v['codec_name']=='av1'
    assert ('10' in v['pix_fmt'])==(bitdepth==10)
    assert list(frames(source,fps=2,width=96,height=54))
    s=GameSession('Synthetic AV1',PlayerIdentity('Synthetic'),add_sources([source]))
    e=PitchEvent(s.id,s.split(0,1),0,1);s.events=[e]
    review(s,e.id,'APPROVED',confirm_identity=True)
    export(s,tmp_path/'out')
    assert next(v for v in probe(tmp_path/'out'/'all_0001.mp4')['streams'] if v['codec_type']=='video')['codec_name']=='h264'


def test_missing_decoder_has_readable_error():
    error=media_error('ffmpeg',b'Metadata... Decoding requested, but no decoder found for: av1')
    assert 'AV1' in str(error) and '업데이트' in str(error) and 'Metadata' not in str(error)
