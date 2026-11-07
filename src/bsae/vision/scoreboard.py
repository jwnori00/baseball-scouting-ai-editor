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


def text_regions(rgb,language='eng+kor+jpn',minimum_confidence=45):
    """Propose text blocks only: never assert player role or scoreboard identity."""
    h,w=rgb.shape[:2]
    ok,image=cv2.imencode('.png',cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
    if not ok:raise RuntimeError('문자 영역 프레임 인코딩 실패')
    raw=run('tesseract',['stdin','stdout','-l',language,'--psm','11','-c','tessedit_create_tsv=1'],input=image.tobytes())
    blocks={}
    for row in csv.DictReader(io.StringIO(raw.decode('utf-8')),delimiter='\t',quoting=csv.QUOTE_NONE):
        if not row.get('text','').strip() or float(row.get('conf',-1))<minimum_confidence:continue
        key=(row['block_num'],row['par_num'],row['line_num']);x,y,bw,bh=[int(row[k]) for k in ('left','top','width','height')]
        if key not in blocks:blocks[key]=dict(text=[],bounds=[x,y,x+bw,y+bh],scores=[])
        block=blocks[key];block['text'].append(row['text']);block['scores'].append(float(row['conf']))
        a,b,c,d=block['bounds'];block['bounds']=[min(a,x),min(b,y),max(c,x+bw),max(d,y+bh)]
    return [dict(text=' '.join(v['text']),region=[v['bounds'][0]/w,v['bounds'][1]/h,v['bounds'][2]/w,v['bounds'][3]/h],ocr_confidence=sum(v['scores'])/len(v['scores']),semantic_role='UNCONFIRMED') for v in blocks.values()]
