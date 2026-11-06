"""Reviewed-event rendering. Each export is a new directory, never an overwrite."""
from dataclasses import asdict
from pathlib import Path
import os
import shutil
import tempfile
from bsae.core.models import ExportManifest, atomic_json
from bsae.ingest.media import run, probe, fingerprint


def verify(path, expected):
    data = probe(path)
    videos = [s for s in data['streams'] if s['codec_type'] == 'video']
    audios = [s for s in data['streams'] if s['codec_type'] == 'audio']
    if not videos or not audios or videos[0]['codec_name'] != 'h264' or audios[0]['codec_name'] != 'aac':
        raise ValueError('출력 코덱/스트림 검증 실패')
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


def export(session, destination, mode='all', progress=lambda value: None, stop=None, include_pickoffs=False, auto_frame=True):
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
            encoded = {}
            framing = []
            first = probe(sources[events[0].segments[0].source_id].path)
            video = next(s for s in first['streams'] if s['codec_type']=='video')
            height = max(2, int(video['height'])//2*2)
            from fractions import Fraction
            sar = video.get('sample_aspect_ratio', '1:1').replace(':','/')
            aspect = float(Fraction(sar)) if sar not in ('N/A','0/1') else 1
            width = max(2, round(int(video['width'])*aspect/2)*2)
            for i,e in enumerate(events):
                pieces = []
                for j,seg in enumerate(e.segments):
                    if stop is not None and stop.is_set():
                        raise RuntimeError('출력 취소')
                    source = sources[seg.source_id]
                    meta = probe(source.path)
                    source_video = next(v for v in meta['streams'] if v['codec_type']=='video')
                    crop = None
                    if auto_frame:
                        from .framing import detect_crop
                        crop = detect_crop(source.path, seg.start, seg.end, source_video, stop)
                    framing.append(dict(event_id=e.id, source_id=seg.source_id, start=seg.start, end=seg.end, crop=crop))
                    prefix = ('crop='+':'.join(map(str,crop))+',') if crop else ''
                    audio = any(s['codec_type']=='audio' for s in meta['streams'])
                    path = temp/f'piece_{i:06d}_{j:03d}.mp4'
                    args = ['-v','error','-nostdin','-n','-ss',str(seg.start),'-i',source.path]
                    if not audio:
                        args += ['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                    args += ['-t',str(seg.end-seg.start),'-map','0:v:0','-map','0:a:0' if audio else '1:a:0',
                        '-vf',prefix+f'scale=trunc(iw*sar/2)*2:ih,setsar=1,scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2',
                        '-r','30','-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(path)]
                    run('ffmpeg', args)
                    verify(path, seg.end-seg.start)
                    pieces.append(path)
                encoded[e.id] = pieces
                progress((i+1)/len(events)*.9)
            for i, group in enumerate(groups):
                paths = [p for e in group for p in encoded[e.id]]
                output = temp/f'{mode}_{i+1:04d}.mp4'
                concatenate(paths, output)
                report = verify(output, sum(e.timeline_end-e.timeline_start for e in group))
                report['sha256'] = fingerprint(output)
                with output.open('rb') as src, (destination/output.name).open('xb') as dst:
                    shutil.copyfileobj(src,dst)
                outputs.append(report)
        manifest = ExportManifest([e.id for e in events], outputs, {s.id:s.fingerprint for s in sources.values()})
        atomic_json(destination/'manifest.json', asdict(manifest))
        atomic_json(destination/'framing.json', dict(automatic=auto_frame, segments=framing))
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
