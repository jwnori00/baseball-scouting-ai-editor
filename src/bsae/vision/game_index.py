"""Source/config keyed common candidates, independent of requested player and review."""
import hashlib,json
QUERY_VERSION='rc1-historical-broadcast-safety'
from dataclasses import asdict


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def store(cache,session,profile,engine,source_keys):
    sources=[dict(fingerprint=s.fingerprint,duration=s.duration,offset=s.offset) for s in session.sources]
    key=digest([engine,sources,source_keys]);fingerprints={s.id:s.fingerprint for s in session.sources}
    common=[];identities=[]
    for e in session.events:
        payload=dict(start=e.timeline_start,end=e.timeline_end,segments=[dict(source_sha256=fingerprints[s.source_id],start=s.start,end=s.end) for s in e.segments],scene='replay_suspected' if e.broadcast_status=='REPLAY_SUSPECTED' else 'archive_suspected' if e.broadcast_status=='ARCHIVE_SUSPECTED' else 'play_candidate')
        event_key=digest(payload);common.append((event_key,json.dumps(payload,sort_keys=True)))
        identities.append(dict(candidate=event_key,identity_status=e.identity_status,broadcast_status=e.broadcast_status,evidence=[asdict(x) for x in e.evidence if x.kind not in ('localized_motion','pitch_camera','scene_margin')]))
    player=asdict(session.player);player.pop('id');query=digest([QUERY_VERSION,player])
    db=cache.db
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS game_index (key TEXT PRIMARY KEY, engine TEXT, sources TEXT, config TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS game_candidates (game_key TEXT, event_key TEXT, payload TEXT, PRIMARY KEY(game_key,event_key))')
        db.execute('CREATE TABLE IF NOT EXISTS player_queries (game_key TEXT, query_key TEXT, player TEXT, results TEXT, PRIMARY KEY(game_key,query_key))')
        if 'logic_version' not in {r[1] for r in db.execute('PRAGMA table_info(player_queries)')}:db.execute("ALTER TABLE player_queries ADD COLUMN logic_version TEXT NOT NULL DEFAULT 'legacy-v1'")
        db.execute('INSERT OR IGNORE INTO game_index VALUES(?,?,?,?)',(key,engine,json.dumps(sources),json.dumps({k:v for k,v in profile.items() if k!='scene_weights'},sort_keys=True)))
        for event_key,payload in common:db.execute('INSERT OR IGNORE INTO game_candidates VALUES(?,?,?)',(key,event_key,payload))
        db.execute('INSERT OR REPLACE INTO player_queries (game_key,query_key,player,results,logic_version) VALUES(?,?,?,?,?)',(key,query,json.dumps(player,ensure_ascii=False),json.dumps(identities,ensure_ascii=False),QUERY_VERSION))
    return dict(game_key=key,query_key=query,query_logic_version=QUERY_VERSION,common_candidates=len(common),known_player_queries=db.execute('SELECT COUNT(*) FROM player_queries WHERE game_key=?',(key,)).fetchone()[0],scope='Common geometry/raw frame cache + requested-player evidence, NOT a validated roster or game truth')
