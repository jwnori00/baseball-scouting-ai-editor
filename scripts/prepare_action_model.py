"""Developer-only official-weight conversion; never compiles media or builds EXEs."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def prepare(destination):
    import torch,torchvision,onnxruntime as ort
    from torchvision.models.video import r3d_18,R3D_18_Weights
    if torch.__version__.split('+')[0]!='2.6.0' or torchvision.__version__.split('+')[0]!='0.21.0':
        raise RuntimeError('검증된 변환 도구 버전: torch 2.6.0 / torchvision 0.21.0')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    if any(destination.iterdir()):raise FileExistsError('새 모델 폴더를 사용하세요')
    weights=R3D_18_Weights.KINETICS400_V1
    # The expected hash prefix is embedded in the official torchvision URL.
    if weights.url!='https://download.pytorch.org/models/r3d_18-b3b3357e.pth':raise ValueError('공식 가중치 URL 변경')
    source=destination/'r3d_18-b3b3357e.pth'
    torch.hub.download_url_to_file(weights.url,str(source),hash_prefix='b3b3357e',progress=True)
    with source.open('rb') as f:source_digest=hashlib.file_digest(f,'sha256').hexdigest()
    model=r3d_18(weights=None).eval()
    model.load_state_dict(torch.load(source,map_location='cpu',weights_only=True))
    torch.set_num_threads(2)
    dummy=torch.from_numpy(np.random.default_rng(31).normal(size=(1,3,16,112,112)).astype(np.float32))
    artifact=destination/'r3d18.onnx'
    torch.onnx.export(model,dummy,str(artifact),input_names=['video'],output_names=['logits'],opset_version=17,dynamo=False)
    with torch.no_grad():expected=model(dummy).numpy()
    options=ort.SessionOptions();options.intra_op_num_threads=2
    session=ort.InferenceSession(str(artifact),sess_options=options,providers=['CPUExecutionProvider'])
    actual=session.run(None,{'video':dummy.numpy()})[0]
    np.testing.assert_allclose(actual,expected,atol=2e-4,rtol=2e-4)
    with artifact.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    info=dict(backend='r3d18-kinetics400-onnx-v1',artifact=artifact.name,sha256=digest,
        categories=weights.meta['categories'],source_url=weights.url,source_sha256=source_digest,
        source_version='torchvision 0.21.0 / R3D_18_Weights.KINETICS400_V1',
        license_notice='Torchvision code BSD-3-Clause; weight/dataset usage rights must be reviewed separately before commercial redistribution.',
        license_url='https://github.com/pytorch/vision/blob/v0.21.0/LICENSE',
        preprocessing=dict(resize=[128,171],crop=[112,112],mean=[.43216,.394666,.37645],std=[.22803,.22145,.216989],frames=16,fps=15),
        validation=dict(onnx_max_abs_error=float(np.abs(actual-expected).max()),baseball_recall='NOT_EVALUATED',identity_accuracy='NOT_EVALUATED',commercial_use_review='REQUIRED'))
    from bsae.core.models import atomic_json
    atomic_json(destination/'action-model.json',info)
    print(json.dumps(dict(manifest=str(destination/'action-model.json'),source_sha256=source_digest,
        onnx_sha256=digest,max_abs_error=info['validation']['onnx_max_abs_error'],baseball_performance='NOT_EVALUATED'),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination')
    prepare(parser.parse_args().destination)
