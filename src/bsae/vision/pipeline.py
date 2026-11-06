"""Streaming model inference and conservative event assembly, independent of GUI."""
from dataclasses import asdict
from collections import deque
import hashlib
import json
import threading
import numpy as np
from bsae.core.models import PitchEvent, DetectionEvidence, PlateAppearance
from bsae.ingest.media import frames, fingerprint, run
from .model import TemporalModel, features, FEATURE_VERSION
from .scoreboard import ScoreboardOCR, identify
from .cache import Cache


class Cancelled(Exception):
    pass


def scan(source, model, profile, cache, stop, progress, fps=4):
    key = hashlib.sha256(json.dumps([source.fingerprint, model.digest, model.info,
        profile, fps, FEATURE_VERSION, 'scanner-v1'], sort_keys=True).encode()).hexdigest()
    if cache.complete(key):
        yield from cache.rows(key)
        return
    # Resume using cached samples, then decode from a context sample before the
    # checkpoint so inter-frame motion is identical to uninterrupted scanning.
    last = None
    for t, row in cache.rows(key):
        if stop.is_set():
            raise Cancelled()
        last = t
        yield t, row
    previous = None
    previous_label = None
    ocr = ScoreboardOCR(profile)
    start = max(0, last - 1/fps) if last is not None else 0
    stream = frames(source.path, fps=fps, start=start)
    try:
        for t, rgb in stream:
            if stop.is_set():
                raise Cancelled()
            x = features(rgb, previous)
            previous = rgb
            label, scores = model.predict(x)
            if last is not None and t <= last + 1e-5:
                previous_label = label
                continue
            readings = {}
            # Fine pass only at relevant state changes or once/second while
            # the pitch camera is present. No whole-video high-res storage.
            if profile.get('regions') and label in ('setup', 'delivery', 'receive', 'dead') and (label != previous_label or round(t*fps) % fps == 0):
                raw = run('ffmpeg', ['-v', 'error', '-nostdin', '-ss', str(t), '-i', source.path,
                    '-frames:v', '1', '-vf', 'scale=960:540', '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
                if len(raw) == 960*540*3:
                    readings = ocr.read(np.frombuffer(raw, np.uint8).reshape(540,960,3))
            row = dict(label=label, scores=scores, ocr=readings,
                       frame_hash=hashlib.sha256(rgb.tobytes()).hexdigest())
            cache.put(key, t, row)
            previous_label = label
            progress(t/source.duration)
            yield t, row
        cache.finish(key)
    finally:
        stream.close()


class Assembler:
    def __init__(self, session):
        self.session = session
        self.setup = None
        self.active = None
        self.observations = deque()
        self.events = []
        self.previous_label = None
        self.last_time = 0

    def feed(self, t, row):
        label = row['label']
        self.last_time = t
        if row.get('ocr'):
            self.observations.append((t, row['ocr']))
        while self.observations and t-self.observations[0][0] > 12:
            self.observations.popleft()
        if label == 'replay':
            if self.active:
                self.active['warnings'].append('리플레이 전환: 실제 플레이 종료 확인 필요')
            self.setup = None
            self.previous_label = label
            return
        if label == 'setup' and self.previous_label != 'setup':
            if self.active:
                self.finish(t, '다음 투구 준비: 이전 플레이 종료를 보수적으로 추정')
            self.setup = t
        if label in ('delivery', 'pickoff') and self.previous_label != label and self.active is None:
            readings = {}
            for _, obs in self.observations:
                readings.update({k: v for k, v in obs.items() if v.strip()})
            certain, identity = identify(self.session.player, readings)
            self.active = dict(start=self.setup if self.setup is not None else t,
                release=t, readings=readings, identified=certain, identity=identity,
                evidence=[DetectionEvidence('temporal_model', json.dumps(row['scores']), t, 'linear-grid-motion-v1')],
                received=False, warnings=[], kind='pickoff' if label == 'pickoff' else 'pitch_candidate')
            if self.setup is None:
                self.active['warnings'].append('준비동작 미확인: 방송에서 확인된 동작부터 시작')
        if self.active:
            if label in ('receive', 'live'):
                self.active['received'] = True
                self.active['evidence'].append(DetectionEvidence('state', label, t))
            if row.get('ocr'):
                self.active['readings'].update({k: v for k, v in row['ocr'].items() if v.strip()})
                certain, identity = identify(self.session.player, self.active['readings'])
                self.active['identified'] = certain
                self.active['identity'] = identity
            if label == 'dead' and self.active['received']:
                self.finish(t, '학습 모델의 dead 상태: 반환 송구/후속 플레이 수동 검수 필요')
        self.previous_label = label

    def finish(self, end, reason):
        a = self.active
        self.active = None
        self.setup = None
        if not a or end <= a['start']:
            return
        p = self.session.player
        warnings = list(dict.fromkeys(a['warnings']))
        if not a['identified']:
            warnings.append('대상 선수 미확정: 이름 외 팀/등번호 근거 필요')
        warnings += ['플레이 유형 및 후속 플레이 보존은 검수 필요', '모델 점수 미보정: 신뢰도 NOT_EVALUATED']
        evidence = a['evidence'] + [DetectionEvidence(k, v, a['release']) for k,v in a['identity']]
        evidence += [DetectionEvidence('start', 'setup' if a['start'] < a['release'] else 'first_visible_delivery', a['start']),
                     DetectionEvidence('end', reason, end)]
        evidence += [DetectionEvidence('ocr:'+k, v, a['release']) for k,v in a['readings'].items()]
        e = PitchEvent(self.session.id, self.session.split(a['start'], end), a['start'], end,
            pitcher_id=p.id if p.role == 'pitcher' and a['identified'] else None,
            batter_id=p.id if p.role == 'batter' and a['identified'] else None,
            inning=a['readings'].get('inning'), number=len(self.events)+1,
            event_type=a['kind'], evidence=evidence, warnings=warnings)
        self.events.append(e)


def group_appearances(events):
    groups = []
    previous_marker = None
    for e in events:
        if e.event_type == 'pickoff':
            continue
        readings = {x.kind[4:]: x.value for x in e.evidence if x.kind.startswith('ocr:')}
        marker = (e.batter_id, e.inning, readings.get('plate_id'))
        # Unknown identity/inning cannot safely establish a shared appearance.
        known = e.batter_id is not None and e.inning is not None
        if not groups or not known or marker != previous_marker or readings.get('count') in ('0-0', '0:0'):
            groups.append(PlateAppearance([], e.batter_id, e.inning))
        groups[-1].event_ids.append(e.id)
        e.plate_id = groups[-1].id
        e.warnings.append('타석 그룹 자동 제안: 종료·타순 검수 필요')
        previous_marker = marker
    return groups


def analyze(session, manifest, profile, cache_path, stop=None, progress=lambda stage, value: None):
    session.validate()
    if not session.sources:
        raise ValueError('원본 영상이 없습니다')
    if any(e.history or e.status != 'REVIEW_REQUIRED' for e in session.events):
        raise ValueError('검수 기록이 있는 프로젝트는 새 프로젝트로 재분석하세요. 캐시는 보존됩니다.')
    model = TemporalModel(manifest)  # Missing/bad weights fail before candidate creation.
    stop = stop or threading.Event()
    cache = Cache(cache_path)
    assembler = Assembler(session)
    from .replay import BoundaryTracker
    tracker = BoundaryTracker()
    overlaps = []
    total = sum(s.duration for s in session.sources)
    try:
        for source in session.sources:
            if fingerprint(source.path) != source.fingerprint:
                raise ValueError('원본 파일이 변경되었습니다')
            for t, row in scan(source, model, profile, cache, stop,
                    lambda fraction: progress('저해상도 탐색 / 선택 구간 OCR', (source.offset+fraction*source.duration)/total)):
                tracker.add(row)
                assembler.feed(source.offset+t, row)
            count = tracker.finish_source()
            if count:
                overlaps.append(dict(source_id=source.id, start=source.offset, end=source.offset+count/4, evidence='exact decoded frame suffix/prefix', samples=count))
        if assembler.active:
            assembler.active['warnings'].append('영상 종료: 실제 플레이 종료 확인 불가')
            assembler.finish(total, '원본 영상 종료')
    finally:
        cache.close()
    # Never silently erase reviewed events on reanalysis.
    reviewed = [e for e in session.events if e.history or e.status != 'REVIEW_REQUIRED']
    if reviewed:
        raise ValueError('검수 기록이 있는 프로젝트는 새 프로젝트로 재분석하세요. 캐시는 보존됩니다.')
    for event in assembler.events:
        for overlap in overlaps:
            if event.timeline_start < overlap['end'] and event.timeline_end > overlap['start']:
                event.warnings.append('분할 원본 중복 구간: 검수 후 중복 후보 제외 필요')
                event.evidence.append(DetectionEvidence('source_overlap', json.dumps(overlap), overlap['start']))
    session.events = assembler.events
    session.appearances = group_appearances(session.events)
    session.analysis = dict(model_sha256=model.digest, performance='NOT_EVALUATED',
        calibration='NOT_EVALUATED', target_filter='unidentified candidates retained for review',
        replay='model classification; exact source boundary overlap only', source_overlaps=overlaps, complete=True)
    session.validate()
    progress('후보 생성 완료 — 전수 검출 성능 미평가', 1)
    return session
