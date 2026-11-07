"""Configurable normalized OCR regions. Missing fields stay unknown."""
import csv
import io
import re
import unicodedata
import cv2
from bsae.ingest.media import run


def normalize(text):
    text=unicodedata.normalize('NFC',''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c)))
    return ''.join(c for c in text if c.isalnum())


def identify(player, readings):
    role_name = readings.get(player.role + '_name', '')
    match = bool(normalize(role_name)) and normalize(role_name) in {normalize(n) for n in [player.name, *player.aliases] if n.strip()}
    evidence = []
    if match:
        evidence.append(('name', role_name))
    if normalize(player.team) and normalize(readings.get(player.role + '_team', '')) == normalize(player.team):
        evidence.append(('team', player.team))
    if player.jersey and readings.get(player.role + '_jersey', '').strip() == player.jersey:
        evidence.append(('jersey', player.jersey))
    # One OCR name alone is insufficient. Do not propagate identity indefinitely.
    return match and len(evidence) >= 2, evidence


class ScoreboardOCR:
    def __init__(self, profile):
        self.profile = profile
        for key, roi in profile.get('regions', {}).items():
            if len(roi) != 4 or not 0 <= roi[0] < roi[2] <= 1 or not 0 <= roi[1] < roi[3] <= 1:
                raise ValueError('잘못된 OCR ROI: ' + key)

    def read(self, rgb):
        result = {}
        h, w = rgb.shape[:2]
        for name, (x1, y1, x2, y2) in self.profile.get('regions', {}).items():
            crop = rgb[int(y1*h):int(y2*h), int(x1*w):int(x2*w)]
            if not crop.size:
                continue
            crop = cv2.resize(crop, None, fx=3, fy=3)
            ok, image = cv2.imencode('.png', cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
            if not ok:
                raise RuntimeError('OCR 이미지 인코딩 실패')
            raw = run('tesseract', ['stdin', 'stdout', '-l', self.profile.get('language', 'eng'), '--psm', '7', '-c', 'tessedit_create_tsv=1'], input=image.tobytes())
            words = [row['text'] for row in csv.DictReader(io.StringIO(raw.decode('utf-8')), delimiter='\t',quoting=csv.QUOTE_NONE)
                     if row.get('text', '').strip() and float(row.get('conf', -1)) >= self.profile.get('minimum_word_confidence', 60)]
            result[name] = ' '.join(words)
        return result


def text_regions(rgb,language='eng+kor+jpn',minimum_confidence=45,psm=11):
    """Propose text blocks only: never assert player role or scoreboard identity."""
    h,w=rgb.shape[:2]
    ok,image=cv2.imencode('.png',cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
    if not ok:raise RuntimeError('문자 영역 프레임 인코딩 실패')
    raw=run('tesseract',['stdin','stdout','-l',language,'--psm',str(psm),'-c','tessedit_create_tsv=1'],input=image.tobytes())
    blocks={}
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8')),delimiter='\t',quoting=csv.QUOTE_NONE):
        if not row.get('text','').strip() or float(row.get('conf',-1))<minimum_confidence:continue
        key=(row['block_num'],row['par_num'],row['line_num']);x,y,bw,bh=[int(row[k]) for k in ('left','top','width','height')]
        if key not in blocks:blocks[key]=dict(text=[],bounds=[x,y,x+bw,y+bh],scores=[])
        block=blocks[key];block['text'].append(row['text']);block['scores'].append(float(row['conf']))
        a,b,c,d=block['bounds'];block['bounds']=[min(a,x),min(b,y),max(c,x+bw),max(d,y+bh)]
    return [dict(text=' '.join(v['text']),region=[v['bounds'][0]/w,v['bounds'][1]/h,v['bounds'][2]/w,v['bounds'][3]/h],ocr_confidence=sum(v['scores'])/len(v['scores']),semantic_role='UNCONFIRMED') for v in blocks.values()]


def broadcast_text_regions(rgb,language='eng+kor'):
    """Full-frame OCR plus bounded, image-derived contrast panels; no fixed ROIs."""
    result=text_regions(rgb,language=language);gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);h,w=gray.shape
    candidates=[]
    for mask in ((gray>185).astype('uint8')*255,(gray<100).astype('uint8')*255):
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(7,3)))
        count,_,stats,_=cv2.connectedComponentsWithStats(mask)
        for x,y,bw,bh,area in stats[1:]:
            if not (max(8,h*.012)<=bh<=h*.25 and w*.04<=bw<=w*.7 and 1.2<=bw/bh<=18 and bw*bh<=w*h*.08 and area/(bw*bh)>.45):continue
            x0=int(x);y0=int(y);x1=int(x+bw);y1=int(y+bh)
            contrast=float(gray[y0:y1,x0:x1].std())
            if contrast<18:continue
            score=contrast/(1+20*bw*bh/(w*h));candidates.append((score,x0,y0,x1,y1))
    selected=[]
    for _,x0,y0,x1,y1 in sorted(candidates,reverse=True):
        if any(abs(x0-a)+abs(y0-b)+abs(x1-c)+abs(y1-d)<20 for a,b,c,d in selected):continue
        selected.append((x0,y0,x1,y1))
        if len(selected)>=6:break
    for x0,y0,x1,y1 in selected:
        crop=cv2.resize(rgb[y0:y1,x0:x1],None,fx=4,fy=4,interpolation=cv2.INTER_LINEAR)
        variants=[(crop,language,'linear')]
        # Hangul-only recognition avoids Latin decoding of small syllables.
        # Keep observations separate: never substitute the requested name.
        if 'kor' in language and y1-y0>h*.05:
            variants.append((cv2.resize(rgb[y0:y1,x0:x1],None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC),'kor','cubic_kor'))
            variants.append((crop,'eng','role_latin'))
        for variant,lang,method in variants:
            for block in text_regions(variant,language=lang,psm=6,minimum_confidence=10 if method=='role_latin' else 45):
                a,b,c,d=block['region'];block=dict(block,panel_region=[x0/w,y0/h,x1/w,y1/h],ocr_variant=method,region=[(x0+a*(x1-x0))/w,(y0+b*(y1-y0))/h,(x0+c*(x1-x0))/w,(y0+d*(y1-y0))/h],detector='contrast_panel')
                result.append(block)
    return result
