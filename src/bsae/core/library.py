"""Local player catalogue, stored outside the portable ZIP directory."""
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import sqlite3
import uuid
from .models import PlayerIdentity,atomic_json

LEAGUES=('', 'KBO','NPB','MLB','LMB','LMP','LIDOM','LVBP','LBPRC','CPBL','국가대항전','기타')


def data_directory():
    if os.environ.get('BSAE_DATA_DIR'):return Path(os.environ['BSAE_DATA_DIR'])
    if os.name=='nt':return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'BaseballScoutingAIEditor'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local'/'share'))/'BaseballScoutingAIEditor'


class Library:
    def __init__(self,path=None):
        self.path=Path(path) if path else data_directory()/'players.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS players(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')

    def connect(self):return sqlite3.connect(self.path,timeout=10)

    @staticmethod
    def validate(row):
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']:raise ValueError('선수 기록 ID 오류')
        p=row.get('player',{})
        if not isinstance(p,dict) or not str(p.get('name','')).strip() or p.get('role') not in ('pitcher','batter') or p.get('league','') not in LEAGUES:raise ValueError('선수 이름·역할·리그 오류')
        if not all(isinstance(p.get(k,''),str) for k in ('name','team','jersey','league')) or not isinstance(p.get('aliases',[]),list) or not all(isinstance(s,str) for s in p.get('aliases',[])):raise ValueError('선수 정보 형식 오류')
        if not isinstance(row.get('favorite',False),bool) or not isinstance(row.get('latest_project',''),str):raise ValueError('선수 부가 정보 오류')
        row=dict(row);row['player']=asdict(PlayerIdentity(**p))
        row.setdefault('favorite',False);row.setdefault('latest_project','');row.setdefault('updated_at','')
        return row

    def records(self,query=''):
        from bsae.vision.scoreboard import normalize
        with self.connect() as db:rows=[json.loads(p) for p, in db.execute('SELECT payload FROM players')]
        terms=[normalize(t) for t in query.split() if normalize(t)]
        def matches(r):
            p=r['player'];hay=normalize(' '.join([p['name'],*p.get('aliases',[]),p.get('team',''),p.get('league',''),p.get('jersey','')]))
            return all(t in hay for t in terms)
        return sorted([r for r in rows if matches(r)],key=lambda r:(not r['favorite'],r['player']['name'],r['id']))

    def get(self,record_id):
        with self.connect() as db:row=db.execute('SELECT payload FROM players WHERE id=?',(record_id,)).fetchone()
        if not row:raise ValueError('선수 기록을 찾을 수 없습니다')
        return json.loads(row[0])

    def save(self,player,*,record_id=None,favorite=None,latest_project=None,force_new=False):
        from bsae.vision.scoreboard import normalize
        p=asdict(player)
        if not force_new and record_id is None:
            # Automatic exact matching needs team+jersey; name alone is not identity.
            key=lambda v:tuple(normalize(v.get(k,'')) for k in ('name','league','team','jersey','role'))
            matches=[r for r in self.records() if key(r['player'])==key(p)] if p['team'] and p['jersey'] else []
            if len(matches)>1:raise ValueError('동명이인·중복 기록이 있습니다. 라이브러리에서 사용할 선수를 선택하세요.')
            if matches:record_id=matches[0]['id']
        previous=self.get(record_id) if record_id and not force_new else None
        row=dict(id=previous['id'] if previous else uuid.uuid4().hex,player=p,
            favorite=bool(favorite) if favorite is not None else previous['favorite'] if previous else False,
            latest_project=str(latest_project) if latest_project is not None else previous['latest_project'] if previous else '',
            updated_at=datetime.now(timezone.utc).isoformat())
        self.validate(row)
        with self.connect() as db:db.execute('INSERT OR REPLACE INTO players VALUES(?,?)',(row['id'],json.dumps(row,ensure_ascii=False)))
        return row

    def backup(self,path):
        path=Path(path)
        if path.exists():raise FileExistsError('기존 백업을 보존하려면 새 파일명을 사용하세요')
        atomic_json(path,dict(schema=1,players=self.records()))

    def restore(self,path):
        path=Path(path)
        if path.stat().st_size>10*1024*1024:raise ValueError('백업 크기 제한 초과')
        payload=json.loads(path.read_text(encoding='utf-8-sig'))
        if payload.get('schema')!=1 or not isinstance(payload.get('players'),list) or len(payload['players'])>10000:raise ValueError('지원하지 않는 선수 백업')
        rows=[self.validate(r) for r in payload['players']]
        if len({r['id'] for r in rows})!=len(rows):raise ValueError('백업에 중복 ID가 있습니다')
        added=0
        with self.connect() as db:
            for original in rows:
                row=dict(original);old=db.execute('SELECT payload FROM players WHERE id=?',(row['id'],)).fetchone()
                if old:
                    if json.loads(old[0])==row:continue
                    row['id']=uuid.uuid4().hex  # Preserve both versions, never overwrite local edits.
                db.execute('INSERT INTO players VALUES(?,?)',(row['id'],json.dumps(row,ensure_ascii=False)));added+=1
        return added
