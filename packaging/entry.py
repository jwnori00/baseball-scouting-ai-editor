"""Frozen entry with an offline, executable-level synthetic smoke check."""
import sys
from pathlib import Path

if __name__=='__main__':
    if '--acceptance-test' in sys.argv:
        from bsae.acceptance import run_acceptance
        from bsae.core.models import atomic_json
        index=sys.argv.index('--acceptance-test')
        report=Path(sys.argv[index+2])
        if report.exists():
            raise SystemExit(3)
        try:
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
        from bsae.core.review import review
        from bsae.ingest.media import run,add_sources,fingerprint
        from bsae.vision.model import TemporalModel
        from bsae.export.render import export
        root=Path(sys._MEIPASS)
        policy=json.loads((root/'build-policy.json').read_text(encoding='utf-8-sig'))
        if policy['kind']=='release':
            model=TemporalModel(root/'models'/'model.json')
            model.predict(np.zeros(456))
        run('tesseract',['--version'])
        run('tesseract',['--list-langs'])
        app=QApplication([]);window=Window();window.show();app.processEvents()
        if policy['kind']=='development':
            assert not window.analyze_button.isEnabled()
        with tempfile.TemporaryDirectory(prefix='야구 Martínez ') as d:
            d=Path(d);video=d/'합성 원본.mp4'
            run('ffmpeg',['-v','error','-nostdin','-n','-f','lavfi','-i','testsrc2=size=160x90:rate=10:duration=2','-c:v','libx264',video])
            original=fingerprint(video)
            game=GameSession('Synthetic smoke',PlayerIdentity('Synthetic'),add_sources([video]))
            window.registered(game)
            window.start.setValue(.2);window.end.setValue(1.5);window.manual()
            window.table.selectRow(0);window.confirm.setChecked(True);window.apply('APPROVED')
            game=window.session
            assert len(game.events)==1 and game.events[0].status=='APPROVED'
            game.save(d/'project.json');game=GameSession.load(d/'project.json')
            export(game,d/'output')
            assert original==fingerprint(video)
        window.dirty=False;window.close()
        # Explicitly does not assert baseball model accuracy or native playback.
        Path(sys.argv[sys.argv.index('--self-test')+1]).write_text(json.dumps(dict(
            executable='PASS',gui_construction='PASS',synthetic_render='PASS',
            model_integrity='PASS' if policy['kind']=='release' else 'NOT_INCLUDED_DEVELOPMENT',automatic_analysis='ENABLED' if policy['kind']=='release' else 'DISABLED',baseball_accuracy='NOT_EVALUATED',windows_user_pc='NOT_TESTED'),indent=2),encoding='utf-8')
    else:
        from bsae.app import main
        raise SystemExit(main())
