from pathlib import Path
import subprocess
import numpy as np
import pytest
from bsae.ingest.media import tool
from bsae.vision.model import LABELS, features, train


@pytest.fixture(scope='session')
def trained(tmp_path_factory):
    root=tmp_path_factory.mktemp('model')
    rng=np.random.default_rng(17)
    templates={label:rng.integers(20,230,(90,160,3),dtype=np.uint8) for label in LABELS}
    samples,labels=[],[]
    for label,image in templates.items():
        for i in range(8):
            frame=np.clip(image.astype(int)+rng.integers(-3,4,image.shape),0,255).astype(np.uint8)
            samples.append(features(frame,frame if i%2 else None));labels.append(label)
    manifest=train(samples,labels,root,license_name='CC0 synthetic test data',provenance='NumPy seeded synthetic noise; no real game footage')
    return manifest,templates


@pytest.fixture
def make_video(tmp_path,trained):
    _,templates=trained
    def create(sequence,name='합성 Martínez.mkv',audio=False):
        path=tmp_path/name
        raw=b''.join(templates[label].tobytes()*4 for label in sequence)
        args=[tool('ffmpeg'),'-v','error','-nostdin','-n','-f','rawvideo','-pix_fmt','rgb24','-s','160x90','-r','4','-i','pipe:0']
        if audio:args+=['-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t',str(len(sequence))]
        if audio:args+=['-c:a','aac']
        args+=['-c:v','ffv1',str(path)]
        subprocess.run(args,input=raw,check=True,capture_output=True)
        return path
    return create


@pytest.fixture(autouse=True)
def isolated_user_data(tmp_path,monkeypatch):
    monkeypatch.setenv('BSAE_DATA_DIR',str(tmp_path/'user-data'))
