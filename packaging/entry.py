"""Frozen entry with an offline, executable-level synthetic smoke check."""
import sys
from pathlib import Path

if __name__=='__main__':
    if '--library-probe' in sys.argv:
        from bsae.core.library import Library
        from bsae.core.models import atomic_json
        index=sys.argv.index('--library-probe')
        try:
            row=Library().get(sys.argv[index+1]);atomic_json(sys.argv[index+2],dict(id=row['id'],name=row['player']['name']))
        except Exception as exc:
            atomic_json(sys.argv[index+2],dict(status='FAIL',error=str(exc)));raise SystemExit(1)
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
        import json,traceback
        report_path=Path(sys.argv[sys.argv.index('--self-test')+1])
        def checkpoint(stage):
            report_path.with_suffix('.progress.json').write_text(json.dumps(dict(stage=stage)),encoding='utf-8')
        checkpoint('imports')
        try:
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
            checkpoint('ocr_version')
            run('tesseract',['--version'])
            checkpoint('ocr_languages')
            languages=run('tesseract',['--list-langs']).decode(errors='replace')
            assert all(name in languages.split() for name in ('eng','kor','jpn'))
            import cv2
            from bsae.vision.scoreboard import ScoreboardOCR
            text_frame=np.full((100,600,3),255,np.uint8)
            cv2.putText(text_frame,'MARTINEZ',(10,65),cv2.FONT_HERSHEY_SIMPLEX,2,(0,0,0),3)
            checkpoint('ocr_text')
            assert 'MARTINEZ' in ScoreboardOCR({'language':'eng+kor+jpn','regions':{'pitcher_name':[0,0,1,1]}}).read(text_frame)['pitcher_name']
            checkpoint('av1_decode')
            for name in ('av1-8bit.mp4','av1-10bit.mp4'):
                run('ffmpeg',['-v','error','-xerror','-i',root/'test-fixtures'/name,'-f','null','-'])
            checkpoint('gui')
            app=QApplication([]);window=Window();window.show();app.processEvents()
            def fail_test(message):raise RuntimeError('GUI self-test: '+str(message))
            window.error=fail_test
            checkpoint('preview_layout')
            assert window.review_splitter.widget(1) is window.video
            assert window.video.height()>window.table.height()
            window.video.setFullScreen(True);app.processEvents()
            assert window.video.isFullScreen()
            from PySide6.QtCore import Qt,QEvent
            from PySide6.QtGui import QKeyEvent
            window.video.keyPressEvent(QKeyEvent(QEvent.KeyPress,Qt.Key_Escape,Qt.NoModifier));app.processEvents()
            assert not window.video.isFullScreen() and window.player.videoOutput() is window.video
            if policy['kind']=='development':
                assert not window.analyze_button.isEnabled()
            auto_scan='NOT_RUN'
            with tempfile.TemporaryDirectory(prefix='야구 Martínez ') as d:
                import os
                os.environ['BSAE_DATA_DIR']=str(Path(d)/'user-data')
                d=Path(d);video=d/'합성 원본.mp4'
                checkpoint('synthetic_media')
                run('ffmpeg',['-v','error','-nostdin','-n','-f','lavfi','-i','testsrc2=size=160x90:rate=10:duration=2','-c:v','libx264',video])
                original=fingerprint(video)
                game=GameSession('Synthetic smoke',PlayerIdentity('Synthetic'),add_sources([video]))
                if policy['kind']=='rules-preview':
                    from bsae.vision.rules import analyze_plays,load_profile,VERSION
                    window.select_broadcast(root/'profiles'/'multi-broadcast-scene-v1.json')
                    assert window.analyze_button.isEnabled()
                    checkpoint('automatic_scan')
                    analyze_plays(game,load_profile(window.profile.text() or None),d/'auto.sqlite')
                    assert game.analysis['engine']==VERSION
                    assert all(e.status!='APPROVED' for e in game.events)
                    auto_scan='PASS'
                    game.events=[];game.appearances=[]
                checkpoint('manual_review')
                window.registered(game)
                window.start.setValue(.2);window.end.setValue(.8);window.manual()
                window.start.setValue(1.0);window.end.setValue(1.5);window.manual()
                window.table.selectRow(0);window.confirm.setChecked(True);window.apply('APPROVED')
                game=window.session
                review_many(game,[e.id for e in game.events],confirm_identity=True)
                set_innings(game,[e.id for e in game.events],'9초')
                assert len(game.events)==2 and all(e.status=='APPROVED' and e.inning=='9초' for e in game.events)
                game.save(d/'project.json');game=GameSession.load(d/'project.json')
                checkpoint('pitcher_plate_edit')
                from bsae.core.review import assign_plate,split_plate,merge_previous_plate,name_plate
                ids=[e.id for e in game.events]
                assign_plate(game,ids,'Opponent batter');split_plate(game,ids[1])
                assert len(game.appearances)==2
                merge_previous_plate(game,ids[1]);name_plate(game,ids[0],'Reviewed opponent')
                assert len(game.appearances)==1 and game.player.role=='pitcher'
                assert game.appearances[0].batter_name=='Reviewed opponent'
                game.save(d/'plates.json');game=GameSession.load(d/'plates.json')
                checkpoint('render')
                export(game,d/'output')
                v=next(v for v in probe(d/'output'/'all_0001.mp4')['streams'] if v['codec_type']=='video')
                assert (v['width'],v['height'],v['avg_frame_rate'])==(1280,720,'30/1')
                from bsae.core.library import Library
                checkpoint('library_write')
                saved=Library().save(game.player,latest_project=str(d/'project.json'),favorite=True)
                import subprocess
                checkpoint('library_restart')
                child_env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1')
                child=subprocess.run([sys.executable,'--library-probe',saved['id'],str(d/'library-restart.json')],env=child_env,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
                child_report=json.loads((d/'library-restart.json').read_text(encoding='utf-8'))
                if child.returncode:raise RuntimeError('Library restart failed: '+child_report.get('error','unknown'))
                assert child_report['id']==saved['id']
                if policy['kind']=='rules-preview':
                    checkpoint('analysis_round_preservation')
                    from bsae.core.rounds import run_round,apply_round
                    from copy import deepcopy
                    old_events=deepcopy(game.events)
                    round_result=run_round(game,deepcopy(game.player),load_profile(window.profile.text()),d/'repeat.sqlite')
                    assert round_result.status=='PROPOSED' and round_result.session.events==old_events
                    checkpoint_id=next(r['id'] for r in round_result.session.analysis_runs if r['kind']=='checkpoint')
                    apply_round(round_result.session,checkpoint_id,'restore')
                    assert round_result.session.events==old_events
                    round_result.session.save(d/'rounds.json')
                    assert GameSession.load(d/'rounds.json').events==old_events
                checkpoint('portrait_output')
                portrait=d/'portrait.mp4'
                run('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=s=72x128:r=10:d=0.6','-c:v','libx264',portrait])
                portrait_game=GameSession('Portrait codec test',PlayerIdentity('Synthetic'),add_sources([portrait]))
                event=PitchEvent(portrait_game.id,portrait_game.split(0,.6),0,.6);portrait_game.events=[event]
                review(portrait_game,event.id,'APPROVED',confirm_identity=True);export(portrait_game,d/'portrait-output')
                portrait_meta=next(v for v in probe(d/'portrait-output'/'all_0001.mp4')['streams'] if v['codec_type']=='video')
                assert (portrait_meta['width'],portrait_meta['height'])==(720,1280)
                assert original==fingerprint(video)
            checkpoint('cleanup')
            window.dirty=False;window.close()
            # Explicitly does not assert baseball model accuracy or native playback.
            Path(sys.argv[sys.argv.index('--self-test')+1]).write_text(json.dumps(dict(
                pitcher_plate_edit='PASS',preview_layout='PASS',analysis_round_preservation='PASS' if policy['kind']=='rules-preview' else 'NOT_RUN',portrait_output='PASS',av1_decode='PASS',executable='PASS',gui_construction='PASS',synthetic_render='PASS',unicode_install_ocr='PASS',
                player_library_restart='PASS',multilingual_ocr_data='PASS',scene_model_integrity='PASS' if policy['kind']=='rules-preview' else 'NOT_CHECKED',batch_review='PASS',inning_edit='PASS',output_720p30='PASS',
                model_integrity='PASS' if policy['kind']=='release' else 'NOT_INCLUDED_DEVELOPMENT',automatic_analysis='RULES_AVAILABLE' if policy['kind']=='rules-preview' else 'ENABLED' if policy['kind']=='release' else 'DISABLED',synthetic_auto_scan=auto_scan,baseball_accuracy='NOT_EVALUATED',windows_user_pc='NOT_TESTED'),indent=2),encoding='utf-8')
        except BaseException as exc:
            report_path.write_text(json.dumps(dict(status='FAIL',error=str(exc),traceback=traceback.format_exc()),indent=2),encoding='utf-8')
            raise SystemExit(1)
    else:
        from bsae.app import main
        raise SystemExit(main())
