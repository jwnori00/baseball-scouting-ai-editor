"""Frozen entry with an offline, executable-level synthetic smoke check."""
import sys
from pathlib import Path

if __name__=='__main__':
    if '--library-probe' in sys.argv:
        from bsae.core.library import Library
        from bsae.core.models import atomic_json
        index=sys.argv.index('--library-probe');row=Library().get(sys.argv[index+1])
        atomic_json(sys.argv[index+2],dict(id=row['id'],name=row['player']['name']))
    elif '--compare-reviewed' in sys.argv:
        from bsae.validation import compare_projects
        index=sys.argv.index('--compare-reviewed')
        compare_projects(*sys.argv[index+1:index+4],reference_complete='--complete-reference' in sys.argv)
    elif '--acceptance-test' in sys.argv:
        from bsae.acceptance import run_acceptance
        from bsae.core.models import atomic_json
        index=sys.argv.index('--acceptance-test')
        report=Path(sys.argv[index+2])
        if report.exists():
            raise SystemExit(3)
        try:
            import json
            policy=json.loads((Path(sys._MEIPASS)/'build-policy.json').read_text(encoding='utf-8-sig'))
            if policy['kind']!='release':
                raise ValueError('Development package: automatic analysis is disabled without a validated baseball model')
            outcome=run_acceptance(sys.argv[index+1],report)
            raise SystemExit(0 if outcome['status']=='PASS' else 2)
        except Exception as exc:
            atomic_json(report,dict(status='FAIL',error=str(exc)))
            raise SystemExit(1)
    elif '--self-test' in sys.argv:
        import json
        import tempfile
        import numpy as np
        from PySide6.QtWidgets import QApplication
        from bsae.gui.window import Window
        from bsae.core.models import GameSession,PlayerIdentity,PitchEvent
        from bsae.core.review import review,review_many,set_innings
        from bsae.ingest.media import run,add_sources,fingerprint,probe
        from bsae.vision.model import TemporalModel
        from bsae.export.render import export
        root=Path(sys._MEIPASS)
        policy=json.loads((root/'build-policy.json').read_text(encoding='utf-8-sig'))
        if policy['kind']=='release':
            model=TemporalModel(root/'models'/'model.json')
            model.predict(np.zeros(456))
        run('tesseract',['--version'])
        languages=run('tesseract',['--list-langs']).decode(errors='replace')
        assert all(name in languages.split() for name in ('eng','kor','jpn'))
        import cv2
        from bsae.vision.scoreboard import ScoreboardOCR
        text_frame=np.full((100,600,3),255,np.uint8)
        cv2.putText(text_frame,'MARTINEZ',(10,65),cv2.FONT_HERSHEY_SIMPLEX,2,(0,0,0),3)
        assert 'MARTINEZ' in ScoreboardOCR({'language':'eng+kor+jpn','regions':{'pitcher_name':[0,0,1,1]}}).read(text_frame)['pitcher_name']
        app=QApplication([]);window=Window();window.show();app.processEvents()
        if policy['kind']=='development':
            assert not window.analyze_button.isEnabled()
        auto_scan='NOT_RUN'
        with tempfile.TemporaryDirectory(prefix='야구 Martínez ') as d:
            import os
            os.environ['BSAE_DATA_DIR']=str(Path(d)/'user-data')
            d=Path(d);video=d/'합성 원본.mp4'
            run('ffmpeg',['-v','error','-nostdin','-n','-f','lavfi','-i','testsrc2=size=160x90:rate=10:duration=2','-c:v','libx264',video])
            original=fingerprint(video)
            game=GameSession('Synthetic smoke',PlayerIdentity('Synthetic'),add_sources([video]))
            if policy['kind']=='rules-preview':
                from bsae.vision.rules import analyze_plays,load_profile,VERSION
                window.select_broadcast(root/'profiles'/'multi-broadcast-scene-v1.json')
                assert window.analyze_button.isEnabled()
                analyze_plays(game,load_profile(window.profile.text() or None),d/'auto.sqlite')
                assert game.analysis['engine']==VERSION
                assert all(e.status!='APPROVED' for e in game.events)
                auto_scan='PASS'
                game.events=[];game.appearances=[]
            window.registered(game)
            window.start.setValue(.2);window.end.setValue(.8);window.manual()
            window.start.setValue(1.0);window.end.setValue(1.5);window.manual()
            window.table.selectRow(0);window.confirm.setChecked(True);window.apply('APPROVED')
            game=window.session
            review_many(game,[e.id for e in game.events],confirm_identity=True)
            set_innings(game,[e.id for e in game.events],'9초')
            assert len(game.events)==2 and all(e.status=='APPROVED' and e.inning=='9초' for e in game.events)
            game.save(d/'project.json');game=GameSession.load(d/'project.json')
            export(game,d/'output')
            v=next(v for v in probe(d/'output'/'all_0001.mp4')['streams'] if v['codec_type']=='video')
            assert (v['width'],v['height'],v['avg_frame_rate'])==(1280,720,'30/1')
            from bsae.core.library import Library
            saved=Library().save(game.player,latest_project=str(d/'project.json'),favorite=True)
            import subprocess
            subprocess.run([sys.executable,'--library-probe',saved['id'],str(d/'library-restart.json')],check=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            assert json.loads((d/'library-restart.json').read_text(encoding='utf-8'))['id']==saved['id']
            assert original==fingerprint(video)
        window.dirty=False;window.close()
        # Explicitly does not assert baseball model accuracy or native playback.
        Path(sys.argv[sys.argv.index('--self-test')+1]).write_text(json.dumps(dict(
            executable='PASS',gui_construction='PASS',synthetic_render='PASS',unicode_install_ocr='PASS',
            player_library_restart='PASS',multilingual_ocr_data='PASS',scene_model_integrity='PASS' if policy['kind']=='rules-preview' else 'NOT_CHECKED',batch_review='PASS',inning_edit='PASS',output_720p30='PASS',
            model_integrity='PASS' if policy['kind']=='release' else 'NOT_INCLUDED_DEVELOPMENT',automatic_analysis='RULES_AVAILABLE' if policy['kind']=='rules-preview' else 'ENABLED' if policy['kind']=='release' else 'DISABLED',synthetic_auto_scan=auto_scan,baseball_accuracy='NOT_EVALUATED',windows_user_pc='NOT_TESTED'),indent=2),encoding='utf-8')
    else:
        from bsae.app import main
        raise SystemExit(main())
