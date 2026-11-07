"""Reviewed-event rendering. Each export is a new directory, never an overwrite."""
from dataclasses import asdict
from pathlib import Path
import os
import shutil
import tempfile
from bsae.core.models import ExportManifest, atomic_json
from bsae.ingest.media import run, probe, fingerprint


def verify(path, expected, expected_size=None):
    data = probe(path)
    videos = [s for s in data['streams'] if s['codec_type'] == 'video']
    audios = [s for s in data['streams'] if s['codec_type'] == 'audio']
    if not videos or not audios or videos[0]['codec_name'] != 'h264' or audios[0]['codec_name'] != 'aac':
        raise ValueError('출력 코덱/스트림 검증 실패')
    if expected_size is not None:
        from fractions import Fraction
        if (videos[0]['width'],videos[0]['height'])!=expected_size or Fraction(videos[0]['avg_frame_rate'])!=30:raise ValueError('출력 해상도/프레임레이트 검증 실패')
    duration = float(data['format']['duration'])
    if abs(duration-expected) > max(.3, expected*.01):
        raise ValueError('출력 길이 검증 실패')
    run('ffmpeg', ['-v','error','-xerror','-nostdin','-i',path,'-f','null','-'])
    return dict(file=Path(path).name, duration=duration, video='h264', audio='aac', decoded=True)


def concatenate(paths, output):
    listing = output.with_suffix('.txt')
    # Intermediates have generated ASCII names; never interpolate user paths.
    listing.write_text(''.join(f"file '{p.name}'\n" for p in paths), encoding='utf-8')
    run('ffmpeg', ['-v','error','-nostdin','-n','-f','concat','-safe','1','-i',listing,
        '-c','copy','-movflags','+faststart', output])


def export(session, destination, mode='all', progress=lambda value: None, stop=None, include_pickoffs=False, auto_frame=None, output_settings=None):
    from bsae.core.output_settings import validate_output_settings
    from .geometry import output_dimensions
    settings=validate_output_settings(output_settings if output_settings is not None else session.output_settings)
    if auto_frame is None:auto_frame=settings['auto_frame']
    if not isinstance(auto_frame,bool):raise ValueError('자동 여백 제거 설정 오류')
    settings['auto_frame']=auto_frame
    if mode not in ('all', 'pitch', 'plate'):
        raise ValueError('출력 모드 오류')
    session.validate()
    if any(e.status=='APPROVED' and e.event_type in ('replay','other_player_or_ocr_error') for e in session.events):
        raise ValueError('리플레이·다른 선수 후보는 원본 확인 후 투구로 재분류해야 출력할 수 있습니다')
    events = sorted([e for e in session.events if e.status == 'APPROVED' and (include_pickoffs or e.event_type != 'pickoff')], key=lambda e:e.timeline_start)
    if not events:
        raise ValueError('검수 승인된 투구가 없습니다')
    role_field = 'pitcher_id' if session.player.role == 'pitcher' else 'batter_id'
    if any(getattr(e, role_field) != session.player.id for e in events):
        raise ValueError('대상 선수 미확정 이벤트')
    for a,b in zip(events, events[1:]):
        if a.timeline_end > b.timeline_start + 1e-5:
            raise ValueError('승인 이벤트 구간이 겹칩니다')
    sources = {s.id:s for s in session.sources}
    for s in sources.values():
        if fingerprint(s.path) != s.fingerprint:
            raise ValueError('원본이 변경되었습니다')
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    if any(destination == Path(s.path).resolve() or destination in Path(s.path).resolve().parents for s in sources.values()):
        raise ValueError('원본과 출력 경로 충돌')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode == 'plate':
        selected = {e.id for e in events}
        groups = [[e for e in events if e.id in pa.event_ids] for pa in session.appearances if pa.confirmed]
        groups = sorted([g for g in groups if g], key=lambda g:g[0].timeline_start)
        if {e.id for g in groups for e in g} != selected:
            raise ValueError('모든 승인 투구의 타석 그룹을 먼저 확정하세요')
    elif mode == 'pitch':
        groups = [[e] for e in events]
    else:
        groups = [events]
    # Reserve target atomically. On failure remove only our own created output.
    destination.mkdir()
    try:
        outputs = []
        with tempfile.TemporaryDirectory(prefix='.bsae-', dir=destination.parent) as temp:
            temp = Path(temp)
            framing=[];completed=0
            for group_index,group in enumerate(groups):
                first_source=sources[group[0].segments[0].source_id]
                first_video=next(v for v in probe(first_source.path)['streams'] if v['codec_type']=='video' and not v.get('disposition',{}).get('attached_pic'))
                width,height=output_dimensions(first_video,settings);paths=[]
                for e in group:
                    for j,seg in enumerate(e.segments):
                        if stop is not None and stop.is_set():raise RuntimeError('출력 취소')
                        source=sources[seg.source_id];meta=probe(source.path)
                        source_video=next(v for v in meta['streams'] if v['codec_type']=='video' and not v.get('disposition',{}).get('attached_pic'))
                        from .framing import detect_crop,crop_filter
                        crop=detect_crop(source.path,seg.start,seg.end,source_video,stop) if auto_frame else None
                        framing.append(dict(event_id=e.id,source_id=seg.source_id,start=seg.start,end=seg.end,crop=crop,output_width=width,output_height=height))
                        prefix=crop_filter(crop,source_video)
                        audio=any(s['codec_type']=='audio' for s in meta['streams'])
                        path=temp/f'piece_{completed:06d}_{j:03d}.mp4'
                        args=['-v','error','-nostdin','-n','-ss',str(seg.start),'-i',source.path]
                        if not audio:args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                        args+=['-t',str(seg.end-seg.start),'-map','0:V:0','-map','0:a:0' if audio else '1:a:0',
                            '-vf',prefix+f"scale=w='trunc(iw*if(gt(sar,0),sar,1)/2)*2':h=ih:flags=lanczos,setsar=1,scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                            '-r','30','-c:v','libx264','-crf','18','-preset','medium','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(path)]
                        run('ffmpeg',args);verify(path,seg.end-seg.start,(width,height));paths.append(path)
                    completed+=1;progress(completed/len(events)*.9)
                output=temp/f'{mode}_{group_index+1:04d}.mp4';concatenate(paths,output)
                report=verify(output,sum(e.timeline_end-e.timeline_start for e in group),(width,height))
                report.update(sha256=fingerprint(output),width=width,height=height,fps=30,aspect_mode=settings['aspect'])
                with output.open('rb') as src,(destination/output.name).open('xb') as dst:shutil.copyfileobj(src,dst)
                outputs.append(report)
        manifest = ExportManifest([e.id for e in events], outputs, {s.id:s.fingerprint for s in sources.values()})
        atomic_json(destination/'manifest.json', asdict(manifest))
        atomic_json(destination/'framing.json', dict(automatic=auto_frame, output_settings=settings, segments=framing))
        atomic_json(destination/'events.json', [asdict(e) for e in events])
        from bsae.evaluation import write_csv
        write_csv(destination/'events.csv', [dict(id=e.id, inning=e.inning, plate_id=e.plate_id,
            start=e.timeline_start, end=e.timeline_end, type=e.event_type, status=e.status) for e in events])
        for s in sources.values():
            if fingerprint(s.path) != s.fingerprint:
                raise ValueError('출력 중 원본 변경 감지')
    except BaseException:
        shutil.rmtree(destination)
        raise
    progress(1)
    return destination
