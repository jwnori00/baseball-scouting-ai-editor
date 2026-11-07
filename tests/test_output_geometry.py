from pathlib import Path
import pytest
from bsae.core.models import GameSession,PlayerIdentity,PitchEvent
from bsae.core.review import review
from bsae.core.output_settings import default_output_settings,legacy_output_settings
from bsae.ingest.media import run,probe,add_sources
from bsae.export.geometry import output_dimensions
from bsae.export.render import export


@pytest.mark.parametrize('size,sar,rotation,expected',[
 ('96x72','1',0,(960,720)),('72x128','1',0,(720,1280)),('72x72','1',0,(720,720)),
 ('168x72','1',0,(1680,720)),('36x78','1',0,(720,1560)),('96x72','4/3',0,(1280,720)),('128x72','1',90,(720,1280))])
def test_real_output_preserves_display_geometry(size,sar,rotation,expected,tmp_path):
    path=tmp_path/'source.mp4'
    run('ffmpeg',['-v','error','-f','lavfi','-i',f'testsrc2=s={size}:r=10:d=0.6','-vf',f'setsar={sar}','-c:v','libx264','-pix_fmt','yuv420p',path])
    if rotation:
        rotated=tmp_path/'rotated.mp4';run('ffmpeg',['-v','error','-display_rotation',str(rotation),'-i',path,'-c','copy',rotated]);path=rotated
    s=GameSession('Geometry',PlayerIdentity('Synthetic'),add_sources([path]));e=PitchEvent(s.id,s.split(0,.6),0,.6);s.events=[e];review(s,e.id,'APPROVED',confirm_identity=True)
    export(s,tmp_path/'out')
    v=next(v for v in probe(tmp_path/'out'/'all_0001.mp4')['streams'] if v['codec_type']=='video')
    assert (v['width'],v['height'])==expected and v['avg_frame_rate']=='30/1' and v['sample_aspect_ratio']=='1:1'
    assert all(abs(float(d.get('rotation',0)))%360<.001 for d in v.get('side_data_list',[]))


def test_legacy_project_settings_and_custom_bounds(tmp_path):
    from dataclasses import asdict
    from bsae.core.models import atomic_json
    s=GameSession('Old',PlayerIdentity('Synthetic'))
    payload=asdict(s);payload.pop('output_settings');payload.pop('analysis_runs');payload.pop('active_round_id')
    p=tmp_path/'old.json';atomic_json(p,payload)
    assert GameSession.load(p).output_settings==legacy_output_settings()
    settings=dict(default_output_settings(),aspect='custom',custom_width=19.5,custom_height=9)
    assert output_dimensions(dict(width=16,height=9),settings)==(1560,720)
    with pytest.raises(ValueError):output_dimensions(dict(width=16,height=9),dict(settings,custom_width=0))


def test_mixed_ratio_concat_is_one_canvas(tmp_path):
    paths=[]
    for i,size in enumerate(('96x72','72x128')):
        p=tmp_path/f'{i}.mp4';run('ffmpeg',['-v','error','-f','lavfi','-i',f'testsrc2=s={size}:r=10:d=0.6','-c:v','libx264',p]);paths.append(p)
    s=GameSession('Mixed',PlayerIdentity('Synthetic'),add_sources(paths))
    s.events=[PitchEvent(s.id,s.split(0,1.2),0,1.2)];review(s,s.events[0].id,'APPROVED',confirm_identity=True)
    export(s,tmp_path/'out')
    v=next(v for v in probe(tmp_path/'out'/'all_0001.mp4')['streams'] if v['codec_type']=='video')
    assert (v['width'],v['height'])==(960,720)


def test_vfr_audio_timestamps_and_cfr_output(tmp_path):
    path=tmp_path/'variable-rate.mp4'
    run('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=s=96x54:r=20:d=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2',
        '-vf',"select='not(eq(mod(n,4),2))'",'-fps_mode','vfr','-c:v','libx264','-c:a','aac',path])
    streams=probe(path)['streams'];video=next(v for v in streams if v['codec_type']=='video')
    assert video['r_frame_rate']!=video['avg_frame_rate']
    s=GameSession('VFR sync test',PlayerIdentity('Synthetic'),add_sources([path]))
    s.events=[PitchEvent(s.id,s.split(0,1.5),0,1.5)];review(s,s.events[0].id,'APPROVED',confirm_identity=True)
    export(s,tmp_path/'out');streams=probe(tmp_path/'out'/'all_0001.mp4')['streams']
    v=next(v for v in streams if v['codec_type']=='video');a=next(v for v in streams if v['codec_type']=='audio')
    assert v['avg_frame_rate']=='30/1'
    assert abs(float(v['start_time'])-float(a['start_time']))<.05
    assert abs(float(v['duration'])-float(a['duration']))<.1
