from copy import deepcopy
import json
import pytest
from bsae.core.models import GameSession,PlayerIdentity,VideoSource,PitchEvent,DetectionEvidence
from bsae.core.review import review_many,confirm_manual_identities
from bsae.vision.batter_text import configure,interpret
from bsae.vision.rules import Identity,load_profile


def game():
 s=GameSession('Identity separation',PlayerIdentity('정수빈','batter','두산','31',league='KBO'),[VideoSource('/synthetic',30,'synthetic')]);s.events=[PitchEvent(s.id,s.split(t,t+2),t,t+2) for t in (0,5)];return s


def test_manual_identity_is_separate_and_does_not_approve():
 s=game();old=deepcopy(s)
 with pytest.raises(ValueError):review_many(s,[e.id for e in s.events])
 assert s==old
 confirm_manual_identities(s,[s.events[0].id]);assert s.events[0].manual_identity_confirmed
 assert s.events[0].identity_status=='IDENTITY_UNKNOWN' and s.events[0].status=='REVIEW_REQUIRED'
 review_many(s,[s.events[0].id]);assert s.events[0].status=='APPROVED' and s.events[1]==old.events[1]


def test_old_approval_migrates_as_human_not_automatic(tmp_path):
 from dataclasses import asdict
 from bsae.core.models import atomic_json
 s=game();review_many(s,[s.events[0].id],confirm_identity=True);d=asdict(s)
 for e in d['events']:
  for key in ('identity_status','manual_identity_confirmed','broadcast_status'):e.pop(key)
 p=tmp_path/'old.json';atomic_json(p,d);loaded=GameSession.load(p)
 assert not loaded.events[0].manual_identity_confirmed and loaded.events[0].identity_status=='IDENTITY_UNKNOWN'
 assert loaded.events[0].status=='APPROVED' and any('구버전 승인' in x for x in loaded.events[0].warnings)


def test_explicit_position_and_batter_graphic_on_pitch_view():
 s=game();p=s.player;profile=configure(dict(load_profile(),regions={}),p)
 def block(text):return dict(text=text,region=[.02,.1,.3,.2])
 readings=interpret([block('9 CF 정 수 빈 .254')],p,pitch_view=True)
 i=Identity(p,profile);assert i.update(0,readings)['state']=='target'
 assert 'batter_jersey' not in readings
 other=interpret([block('B. 강민호 2타수')],p,pitch_view=True)
 assert i.update(1,other)['state']!='target'
 assert i.update(3,other)['state']=='other_evidence'
 assert i.update(4,{})['state']!='target'
 assert 'batter_name' not in interpret([block('9 CF 정수빈')],p,pitch_view=False)
 assert 'batter_current_role' not in interpret([block('1 CF 정수빈'),block('2 RF 강민호')],p,pitch_view=True)


def test_inning_reset_and_replay_do_not_leak_identity():
 p=game().player;i=Identity(p,configure(load_profile(),p))
 assert i.update(0,dict(batter_name='정수빈',batter_team='두산',inning='1초',count='1-2'))['state']=='target'
 assert i.update(1,dict(inning='2초'))['state']!='target'
 i.update(2,dict(batter_name='정수빈',batter_team='두산',count='1-2'))
 assert i.update(3,dict(count='0-0'))['state']!='target'
 i.update(4,dict(batter_name='정수빈',batter_team='두산'))
 assert i.update(5,dict(replay='REPLAY'))['state']!='target'


def test_common_index_ignores_player_uuid_and_reuses_frame_cache(make_video,tmp_path,monkeypatch):
 from bsae.ingest.media import add_sources
 from bsae.vision.rules import analyze_plays
 import bsae.vision.scoreboard as scoreboard
 path=make_video(['setup']*4);profile=load_profile();profile['regions']={};cache=tmp_path/'game.sqlite';calls=[]
 monkeypatch.setattr(scoreboard,'text_regions',lambda *a,**kw:calls.append(1) or [])
 s=GameSession('A',game().player,add_sources([path]));analyze_plays(s,profile,cache)
 first=len(calls);index=s.analysis['game_index']
 other=PlayerIdentity('강민호','batter','삼성',league='KBO');t=GameSession('B',other,add_sources([path]));analyze_plays(t,profile,cache)
 assert len(calls)==first and t.analysis['game_index']['game_key']==index['game_key']
 assert t.analysis['game_index']['known_player_queries']==2
 assert t.analysis['cache_usage'][0]['complete_before']


def test_gui_bulk_does_not_implicitly_confirm_unknowns(monkeypatch):
 from PySide6.QtWidgets import QApplication,QMessageBox
 from bsae.gui.window import Window
 app=QApplication.instance() or QApplication([]);w=Window();w.session=game();w.fill_identity(w.session.player);w.review_filter.setCurrentIndex(1);w.refresh();w.table.selectAll()
 errors=[];monkeypatch.setattr(w,'error',errors.append);monkeypatch.setattr(QMessageBox,'question',lambda *a,**kw:QMessageBox.Yes)
 w.approve_selected();assert errors
 assert all(e.status=='REVIEW_REQUIRED' and not e.manual_identity_confirmed and e.batter_id is None for e in w.session.events)
 w.dirty=False;w.close()


def test_nonempty_common_candidate_index_does_not_copy_target_identity(tmp_path):
 from bsae.vision.cache import Cache
 from bsae.vision.game_index import store
 s=game();c=Cache(tmp_path/'index.sqlite')
 try:
  s.events=s.events[:1];s.events[0].identity_status='TARGET_CONFIRMED';s.events[0].batter_id=s.player.id
  one=store(c,s,{},'test',['features-v1'])
  t=game();t.player.name='다른타자';t.events=t.events[:1]
  two=store(c,t,{},'test',['features-v1'])
  assert one['game_key']==two['game_key'] and two['known_player_queries']==2
  rows=c.db.execute('SELECT payload FROM game_candidates').fetchall();assert len(rows)==1
  assert '정수빈' not in rows[0][0] and 'batter_id' not in rows[0][0]
  states=[json.loads(r[0])[0]['identity_status'] for r in c.db.execute('SELECT results FROM player_queries')]
  assert sorted(states)==['IDENTITY_UNKNOWN','TARGET_CONFIRMED']
 finally:c.close()


def test_preflight_decline_keeps_thread_responsive():
 from bsae.gui.window import Job
 from bsae.vision.pipeline import Cancelled
 import threading,time
 job=Job(lambda *a:None);errors=[]
 def ask():
  try:job.ask_preflight({'preflight':{}})
  except Cancelled as exc:errors.append(str(exc))
 thread=threading.Thread(target=ask);thread.start()
 while not hasattr(job,'preflight_reply'):time.sleep(.005)
 job.preflight_reply.set();thread.join(2)
 assert not thread.is_alive() and errors


def test_gui_preflight_decline_preserves_existing_review(make_video,tmp_path,monkeypatch):
 from PySide6.QtWidgets import QApplication,QMessageBox
 from PySide6.QtCore import QEventLoop,QTimer
 from bsae.gui.window import Window
 from bsae.ingest.media import add_sources
 import bsae.vision.rules as rules
 import bsae.vision.profile_detection as detection
 app=QApplication.instance() or QApplication([]);s=GameSession('Existing',game().player,add_sources([make_video(['setup']*5)]))
 s.events=[PitchEvent(s.id,s.split(0,2),0,2)];review_many(s,[s.events[0].id],confirm_identity=True);old=deepcopy(s.events)
 w=Window();w.registered(s);w.files.addItem(s.sources[0].path);w.project_path=str(tmp_path/'work.json');w.error=lambda *a:None
 profile=load_profile();profile['regions']={}
 monkeypatch.setattr(detection,'select_profile',lambda *a,**k:(profile,dict(preflight=dict(identity_evidence_frames=0))))
 monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.No)
 called=[];monkeypatch.setattr(rules,'analyze_plays',lambda *a,**k:called.append(1))
 w.start_analysis();loop=QEventLoop();w.job.finished.connect(loop.quit);QTimer.singleShot(5000,loop.quit);loop.exec()
 assert not w.job.isRunning() and not called and w.session.events==old
 assert w.session.analysis_runs[-1]['status']=='INTERRUPTED'
 w.dirty=False;w.close()


def test_generic_caption_loss_or_cut_does_not_keep_previous_batter_confirmed():
 from bsae.vision.rules import Assembly
 s=game();profile=configure(dict(load_profile(),regions={}),s.player);a=Assembly(s,profile)
 def feed(t,blocks=None,cut=False):
  row=dict(pitch_view=True,motion=0,catcher_motion=0,field=.2,signature=str(t),cut=cut)
  if blocks is not None:row['text_blocks']=blocks
  a.feed(t,row)
 caption=[dict(text='타자 정수빈 두산',region=[.1,.7,.4,.8],ocr_confidence=90)]
 feed(0,caption);assert a.recent[-1][1]['identity']['state']=='target'
 feed(2,[]);assert a.recent[-1][1]['identity']['state']!='target'
 feed(4,caption);feed(4.2,cut=True)
 assert a.recent[-1][1]['identity']['state']!='target'


def test_same_fresh_caption_slot_retains_role_but_not_after_name_loss():
 from bsae.vision.rules import Assembly
 s=game();a=Assembly(s,configure(dict(load_profile(),regions={}),s.player))
 def feed(t,text):
  a.feed(t,dict(pitch_view=True,motion=0,catcher_motion=0,field=.2,signature=str(t),cut=False,text_blocks=[dict(text=text,region=[.1,.7,.4,.8],ocr_confidence=90)] if text else []))
 feed(0,'9 CF 정수빈');assert a.recent[-1][1]['identity']['state']=='target'
 feed(2,'정수빈 .254');assert a.recent[-1][1]['identity']['state']=='target'
 assert a.recent[-1][1]['readings']['batter_context_kind']=='caption_slot_only; NOT person_tracking'
 feed(4,'');assert a.recent[-1][1]['identity']['state']!='target'


def test_caption_of_another_batter_breaks_previous_slot_context():
 from bsae.vision.rules import Assembly
 s=game();a=Assembly(s,configure(dict(load_profile(),regions={}),s.player))
 def feed(t,text):a.feed(t,dict(pitch_view=True,motion=0,catcher_motion=0,field=.2,signature=str(t),cut=False,text_blocks=[dict(text=text,region=[.1,.7,.4,.8],ocr_confidence=90)]))
 feed(0,'9 CF 정수빈');feed(2,'B. 강민호 2타수');feed(4,'정수빈 .254')
 assert a.recent[-1][1]['identity']['state']!='target'
