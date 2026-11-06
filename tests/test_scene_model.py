import json
from pathlib import Path
import numpy as np
import pytest
from bsae.vision.scene import features,validate,DIMENSION
from bsae.vision.rules import load_profile,camera_cues


def test_bundled_scene_and_corrupt_model():
    p=load_profile(Path(__file__).resolve().parents[1]/'profiles'/'multi-broadcast-scene-v1.json')
    rgb=np.zeros((180,320,3),np.uint8)
    assert features(rgb).shape==(DIMENSION,)
    assert np.isfinite(camera_cues(rgb,p)['scene_margin'])
    bad=dict(p['scene_weights'],scale=[0]*DIMENSION)
    with pytest.raises(ValueError):validate(bad)


def test_training_rejects_duplicate_source_across_splits(tmp_path,monkeypatch):
    import importlib.util
    import sys
    path=Path(__file__).resolve().parents[1]/'scripts'/'train_camera_scene.py'
    spec=importlib.util.spec_from_file_location('train_camera_scene_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    a=tmp_path/'a.mp4';b=tmp_path/'b.mp4';a.write_bytes(b'not decoded');b.write_bytes(a.read_bytes())
    manifest=tmp_path/'labels.json';manifest.write_text(json.dumps(dict(samples=[dict(path=str(a),time=0,label=0,group='one',split='train'),dict(path=str(b),time=0,label=1,group='two',split='holdout')])))
    monkeypatch.setattr(sys,'argv',['train',str(manifest),str(tmp_path/'model.json')])
    with pytest.raises(ValueError,match='중복'):module.main()
    assert not (tmp_path/'model.json').exists()
