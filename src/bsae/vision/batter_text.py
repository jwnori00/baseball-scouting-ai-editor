"""Whole-frame caption evidence. This is not face/jersey recognition or tracking."""
from copy import deepcopy
import re
import unicodedata

VERSION='caption-evidence-v1'


def configure(profile,player):
    result=deepcopy(profile)
    if player.role!='batter' or result.get('input_type','broadcast')!='broadcast':return result
    if not result.get('regions',{}).get('batter_name'):
        result['auto_batter_text']=VERSION
        text=player.name+' '+''.join(player.aliases)
        result['language']='kor+eng' if player.league=='KBO' or re.search('[가-힣]',text) else 'jpn+eng' if player.league=='NPB' or re.search('[ぁ-ヿ]',text) else 'eng'
    return result


def mention(text,name):
    name=unicodedata.normalize('NFKC',name.strip())
    if not name:return None
    # Letter boundaries prevent e.g. a short surname matching a longer player.
    pattern=r'(?<![^\W\d_])'+r'\s*'.join(re.escape(c) for c in name if not c.isspace())+r'(?![^\W\d_])'
    return re.search(pattern,unicodedata.normalize('NFKC',text),re.I)


def near(a,b):
    x1,y1,x2,y2=a['region'];u1,v1,u2,v2=b['region']
    return max(y1-v2,v1-y2,0)<=.10 and max(x1-u2,u1-x2,0)<=.15


def interpret(blocks,player):
    result={};hits=[]
    for block in blocks:
        for name in [player.name,*player.aliases]:
            m=mention(block['text'],name)
            if m:hits.append((block,m.group()));break
    # Multiple target captions may coexist: conflicting local number readings
    # are retained rather than selecting whichever matches the requested input.
    for block,observed in hits:
        neighbors=[b['text'] for b in blocks if near(block,b)]
        context=' | '.join(neighbors)
        result['batter_name_hint']=observed
        result['batter_name_hint_source']='whole_frame_text; role not established'
        role=bool(re.search(r'타자|타석|BATTER|BATTING|打者',context,re.I))
        stats=sum(bool(re.search(word,context,re.I)) for word in [r'타율|AVG|打率',r'타점|RBI|打点',r'홈런|\bHR\b|本塁打',r'타수|\bAB\b'])
        if not role and stats<2:continue
        result['batter_name']=observed
        result['batter_role_text']=context[:1500]
        if player.team:
            for text in neighbors:
                m=mention(text,player.team)
                if m:result['batter_team']=m.group();break
        number=re.search(r'(?:등번호|背番号|\bNO\.?|#)\s*[:：]?\s*(\d{1,3})(?!\d)',context,re.I)
        if number:
            result['batter_jersey']=number.group(1)
            result['batter_number_source']='caption_label; NOT uniform_number'
    if not hits:
        # Only explicit role labels can introduce another player's name here.
        # A lineup, historical stat sheet, etc. is still not verified current play.
        for block in blocks:
            m=re.search(r'(?:타자|打者)\s*[:：]?\s*([가-힣]{2,4})(?![가-힣])',block['text'])
            if m:result.update(batter_name=m.group(1),batter_role_text=block['text']);break
    return result
