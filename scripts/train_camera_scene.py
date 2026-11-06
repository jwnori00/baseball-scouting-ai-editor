"""Train/evaluate from a private human-labeled manifest; media stays local.

Usage: python scripts/train_camera_scene.py private/labels.json output/model.json
Manifest: {samples:[{path,time,label:0|1,group,split:train|holdout},...]}
Split groups must describe source games/recording families, not individual frames.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from bsae.ingest.media import run,fingerprint
from bsae.vision.scene import features,train,margin


def main():
    parser=argparse.ArgumentParser();parser.add_argument('manifest');parser.add_argument('output');args=parser.parse_args()
    rows=json.loads(Path(args.manifest).read_text(encoding='utf-8'))['samples']
    groups={};hashes={};digest_cache={};x=[];labels=[];evaluations=[]
    for row in rows:
        if row['split'] not in ('train','holdout') or row['label'] not in (0,1) or not row['group'] or row['time']<0:raise ValueError('라벨 형식 오류')
        path=str(Path(row['path']).resolve());digest=digest_cache.setdefault(path,None)
        if digest is None:digest=fingerprint(path);digest_cache[path]=digest
        for mapping,key in ((groups,row['group']),(hashes,digest)):
            if key in mapping and mapping[key]!=row['split']:raise ValueError('학습/검증에 같은 경기·중복 파일이 포함됐습니다')
            mapping[key]=row['split']
    for row in rows:
        raw=run('ffmpeg',['-v','error','-ss',str(row['time']),'-i',row['path'],'-frames:v','1','-vf','scale=320:180','-threads','1','-f','rawvideo','-pix_fmt','rgb24','-'])
        if len(raw)!=320*180*3:raise ValueError('라벨 프레임 디코딩 실패')
        image=np.frombuffer(raw,np.uint8).reshape(180,320,3)
        if row['split']=='train':
            # Illumination augmentation, confined to training frames.
            for gain in (.85,1.,1.15):x.append(features(np.clip(image.astype(float)*gain,0,255).astype(np.uint8)));labels.append(row['label'])
        else:evaluations.append((row,image.copy()))
    model=train(x,labels,dict(annotation='Assistant visual frame labels; not independent human truth',train_groups=sorted(k for k,v in groups.items() if v=='train'),holdout_groups=sorted(k for k,v in groups.items() if v=='holdout'),train_source_sha256=sorted(k for k,v in hashes.items() if v=='train'),holdout_source_sha256=sorted(k for k,v in hashes.items() if v=='holdout'),manifest_sha256=hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest()))
    counts=dict(tp=0,fp=0,fn=0,tn=0);results=[]
    for row,image in evaluations:
        score=margin(image,model);prediction=int(score>=model['threshold']);truth=row['label']
        counts[('tp' if truth else 'fp') if prediction else ('fn' if truth else 'tn')]+=1
        results.append(dict(source_sha256=digest_cache[str(Path(row['path']).resolve())],time=row['time'],label=truth,predicted=prediction,margin=score))
    report=dict(task='frame pitch-camera classification ONLY',train_frames=sum(r['split']=='train' for r in rows),holdout_frames=len(results),counts=counts,results=results,player_identity='NOT_EVALUATED',pitch_recall='NOT_EVALUATED',play_end='NOT_EVALUATED')
    output=Path(args.output)
    if output.exists():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n')
    output.with_suffix('.validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))


if __name__=='__main__':main()
