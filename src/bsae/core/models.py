"""Versioned project data. Timeline seconds are relative to decoded media start."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import math
import os
import tempfile
import uuid
from .output_settings import default_output_settings,legacy_output_settings,validate_output_settings


def uid():
    return uuid.uuid4().hex


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass
class VideoSource:
    path: str
    duration: float
    fingerprint: str
    offset: float = 0
    pts_origin: float = 0
    id: str = field(default_factory=uid)


@dataclass
class PlayerIdentity:
    name: str
    role: str = 'pitcher'
    team: str = ''
    jersey: str = ''
    aliases: list[str] = field(default_factory=list)
    id: str = field(default_factory=uid)
    league: str = ''


@dataclass
class DetectionEvidence:
    kind: str
    value: str
    time: float
    model: str = ''


@dataclass
class PlaySegment:
    source_id: str
    start: float
    end: float


@dataclass
class ReviewRecord:
    action: str
    before: dict
    after: dict
    note: str
    timestamp: str


@dataclass
class PitchEvent:
    game_id: str
    segments: list[PlaySegment]
    timeline_start: float
    timeline_end: float
    pitcher_id: str | None = None
    batter_id: str | None = None
    inning: str | None = None
    number: int = 0
    event_type: str = 'pitch_candidate'
    evidence: list[DetectionEvidence] = field(default_factory=list)
    confidence: float | None = None
    status: str = 'REVIEW_REQUIRED'
    warnings: list[str] = field(default_factory=list)
    history: list[ReviewRecord] = field(default_factory=list)
    plate_id: str | None = None
    id: str = field(default_factory=uid)
    identity_status: str = 'IDENTITY_UNKNOWN'
    manual_identity_confirmed: bool = False
    broadcast_status: str = 'UNVERIFIED'


@dataclass
class PlateAppearance:
    event_ids: list[str]
    batter_id: str | None
    inning: str | None
    confirmed: bool = False
    id: str = field(default_factory=uid)
    batter_name: str = ''


@dataclass
class ExportManifest:
    event_ids: list[str]
    outputs: list[dict]
    source_fingerprints: dict[str, str]
    completeness: str = 'NOT_EVALUATED'


@dataclass
class GameSession:
    title: str
    player: PlayerIdentity
    sources: list[VideoSource] = field(default_factory=list)
    events: list[PitchEvent] = field(default_factory=list)
    appearances: list[PlateAppearance] = field(default_factory=list)
    game_date: str = ''
    id: str = field(default_factory=uid)
    schema: int = 1
    analysis: dict = field(default_factory=dict)
    output_settings: dict = field(default_factory=default_output_settings)
    analysis_runs: list[dict] = field(default_factory=list)
    active_round_id: str | None = None

    def validate(self):
        validate_output_settings(self.output_settings)
        if not isinstance(self.analysis_runs,list) or any(not isinstance(r,dict) or not r.get("id") for r in self.analysis_runs):raise ValueError("분석 회차 형식 오류")
        if self.schema != 1 or self.player.role not in ('pitcher', 'batter'):
            raise ValueError('지원하지 않는 프로젝트/선수 역할')
        ids = [s.id for s in self.sources]
        if len(ids) != len(set(ids)) or len({e.id for e in self.events}) != len(self.events):
            raise ValueError('중복 ID')
        by_id = {s.id: s for s in self.sources}
        for s in self.sources:
            if not all(math.isfinite(x) for x in (s.duration, s.offset, s.pts_origin)) or s.duration <= 0 or s.offset < 0:
                raise ValueError('잘못된 원본 시간')
        for e in self.events:
            if e.identity_status not in ('TARGET_CONFIRMED','OTHER_PLAYER','IDENTITY_UNKNOWN') or type(e.manual_identity_confirmed) is not bool or e.broadcast_status not in ('UNVERIFIED','REPLAY_SUSPECTED','ARCHIVE_SUSPECTED'):raise ValueError('선수 신원/방송 상태 형식 오류')
            if e.game_id != self.id or e.status not in ('REVIEW_REQUIRED', 'APPROVED', 'EXCLUDED'):
                raise ValueError('잘못된 이벤트/검수 상태')
            if not e.segments or not all(math.isfinite(x) for x in (e.timeline_start, e.timeline_end)) or not 0 <= e.timeline_start < e.timeline_end:
                raise ValueError('잘못된 이벤트 시간')
            if e.confidence is not None and (not math.isfinite(e.confidence) or not 0 <= e.confidence <= 1):
                raise ValueError('잘못된 신뢰도')
            previous = e.timeline_start
            for seg in e.segments:
                s = by_id.get(seg.source_id)
                if s is None or not all(math.isfinite(x) for x in (seg.start, seg.end)) or not 0 <= seg.start < seg.end <= s.duration + 1e-5:
                    raise ValueError('원본 범위 밖 구간')
                a, b = s.offset + seg.start, s.offset + seg.end
                if abs(a - previous) > 1e-4:
                    raise ValueError('통합 타임라인 불연속')
                previous = b
            if abs(previous - e.timeline_end) > 1e-4:
                raise ValueError('통합 타임라인 종료 불일치')
        if len({p.id for p in self.appearances}) != len(self.appearances):
            raise ValueError('중복 타석 ID')
        grouped = set()
        event_map = {e.id: e for e in self.events}
        for pa in self.appearances:
            if not pa.event_ids or any(i not in event_map for i in pa.event_ids):
                raise ValueError('없는 투구를 참조하는 타석')
            if len(set(pa.event_ids)) != len(pa.event_ids) or grouped.intersection(pa.event_ids):
                raise ValueError('투구가 여러 타석에 중복 포함되었습니다')
            if any(event_map[i].plate_id != pa.id for i in pa.event_ids):
                raise ValueError('타석 연결 불일치')
            grouped.update(pa.event_ids)
        if any(e.plate_id is not None and e.id not in grouped for e in self.events):
            raise ValueError('이벤트의 타석 그룹이 없습니다')

    def save(self, path):
        self.validate()
        if Path(path).resolve() in {Path(s.path).resolve() for s in self.sources}:
            raise ValueError('원본에 프로젝트를 저장할 수 없습니다')
        atomic_json(path, asdict(self))

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8-sig')))

    @classmethod
    def from_dict(cls,data):
        from copy import deepcopy
        d=deepcopy(data)
        if 'output_settings' not in d:d['output_settings']=legacy_output_settings()
        d['player'] = PlayerIdentity(**d['player'])
        d['sources'] = [VideoSource(**s) for s in d['sources']]
        for e in d['events']:
            role_field='pitcher_id' if d['player'].role=='pitcher' else 'batter_id'
            if 'identity_status' not in e:
                states=[x.get('value') for x in e['evidence'] if x.get('kind')=='identity_state']
                proof={x.get('kind') for x in e['evidence']}
                known=e.get(role_field)==d['player'].id
                e['identity_status']='TARGET_CONFIRMED' if known and ('target' in states or 'name' in proof and bool(proof.intersection({'team','jersey'}))) else 'OTHER_PLAYER' if 'other_evidence' in states else 'IDENTITY_UNKNOWN'
            if 'manual_identity_confirmed' not in e:
                e['manual_identity_confirmed']=bool(e['status']=='APPROVED' and e.get(role_field)==d['player'].id and any(h.get('action')=='APPROVED' for h in e.get('history',[])))
                if e['manual_identity_confirmed']:e['warnings'].append('구버전 사용자 승인 이력을 직접 확인 기록으로 보존; 자동 신원 판정은 유지')
            if e['status']=='APPROVED' and e['identity_status']=='IDENTITY_UNKNOWN' and e.get(role_field)==d['player'].id and any(h.get('action')=='APPROVED' for h in e.get('history',[])):
                e['manual_identity_confirmed']=True
            e.setdefault('broadcast_status','REPLAY_SUSPECTED' if e['event_type']=='replay' else 'UNVERIFIED')
            e['segments'] = [PlaySegment(**s) for s in e['segments']]
            e['evidence'] = [DetectionEvidence(**v) for v in e['evidence']]
            e['history'] = [ReviewRecord(**v) for v in e['history']]
        d['events'] = [PitchEvent(**e) for e in d['events']]
        d['appearances'] = [PlateAppearance(**p) for p in d['appearances']]
        result = cls(**d)
        result.validate()
        return result

    def split(self, start, end):
        result = []
        for s in self.sources:
            a, b = max(start, s.offset), min(end, s.offset + s.duration)
            if b > a:
                result.append(PlaySegment(s.id, a - s.offset, b - s.offset))
        if not result or abs(sum(x.end-x.start for x in result)-(end-start)) > 1e-4:
            raise ValueError('원본에 없는 타임라인 구간')
        return result
