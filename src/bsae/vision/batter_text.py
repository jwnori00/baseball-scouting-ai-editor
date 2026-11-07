"""Whole-frame caption evidence. This is not face/jersey recognition or tracking."""
from copy import deepcopy
import re
import unicodedata
import json

VERSION='caption-evidence-v4-scorebug-role-2'


def configure(profile,player):
    result=deepcopy(profile)
    if player.role!='batter' or result.get('input_type','broadcast')!='broadcast':return result
    text=player.name+' '+''.join(player.aliases)
    if result.get('language','eng')=='eng' and (player.league=='KBO' or re.search('[가-힣]',text)):result['language']='kor+eng'
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


def interpret(blocks,player,pitch_view=False):
    result={};hits=[]
    for block in blocks:
        if re.search(r'\bREPLAY\b|리플레이',block['text'],re.I):result['replay']='REPLAY'
        m=re.search(r'자료\s*화면|지난\s*경기|ARCHIVE FOOTAGE|PAST GAME',block['text'],re.I)
        if m:result['archive']=m.group()
    for block in blocks:
        for name in [player.name,*player.aliases]:
            m=mention(block['text'],name)
            if m:hits.append((block,m.group()));break
    # Multiple target captions may coexist: conflicting local number readings
    # are retained rather than selecting whichever matches the requested input.
    graphic=[]
    for b in blocks:
        name=role_line(b['text'])
        if not name:name=scorebug_name(b,blocks)
        if not name:continue
        a1,b1,a2,b2=b['region'];duplicate=False
        for old,old_name in graphic:
            c1,d1,c2,d2=old['region'];intersection=max(0,min(a2,c2)-max(a1,c1))*max(0,min(b2,d2)-max(b1,d1))
            compact=re.sub(r'\s+','',name);previous=re.sub(r'\s+','',old_name)
            compatible=compact==previous or (min(len(compact),len(previous))>=2 and (compact.endswith(previous) or previous.endswith(compact)))
            if compatible and intersection>.3*min((a2-a1)*(b2-b1),(c2-c1)*(d2-d1)):
                duplicate=True
                # Prefer an explicit position/role label over a partial reading.
                if (bool(role_line(b['text'])),len(compact))>(bool(role_line(old['text'])),len(previous)):
                    graphic[graphic.index((old,old_name))]=(b,name)
        if not duplicate:graphic.append((b,name))
    for block,observed in hits:
        neighbors=[b['text'] for b in blocks if near(block,b)]
        context=' | '.join(neighbors)
        result['batter_name_hint']=observed
        result['batter_name_hint_region']=json.dumps(block['region'])
        result['batter_name_hint_source']='whole_frame_text; role not established'
        role=bool(re.search(r'타자|타석|BATTER|BATTING|打者',context,re.I))
        stats=sum(bool(re.search(word,context,re.I)) for word in [r'타율|AVG|打率',r'타점|RBI|打点',r'홈런|\bHR\b|本塁打',r'타수|\bAB\b'])
        current_graphic=pitch_view and len(graphic)==1 and graphic[0][0] is block
        if not role and stats<2 and not current_graphic:continue
        if current_graphic:
            result['batter_current_role']=block['text'];result['batter_role_region']=json.dumps(block['region'])
            result['batter_role_source']='explicit_role_line' if role_line(block['text']) else 'scorebug_count_pitcher_neighbor'
            panel=block.get('panel_region')
            counts={m.group(1)+'-'+m.group(2) for peer in blocks if panel and peer.get('panel_region')==panel for m in re.finditer(r'(?<!\d)([0-3])\s*[-:]\s*([0-2])(?!\d)',peer['text'])}
            if len(counts)==1:result['count']=counts.pop()
        result['batter_name']=observed
        result['batter_role_text']=context[:1500]
        if player.team:
            for text in [block['text']]:
                m=mention(text,player.team)
                if m:result['batter_team']=m.group();break
        number=re.search(r'(?:등번호|背番号|\bNO\.?|#)\s*[:：]?\s*(\d{1,3})(?!\d)',context,re.I)
        if number:
            result['batter_jersey']=number.group(1)
            result['batter_number_source']='caption_label; NOT uniform_number'
    if not hits and pitch_view and len(graphic)==1:
        block,name=graphic[0];result.update(batter_name=name,batter_role_text=block['text'],batter_current_role=block['text'])
    if not hits and not result.get('batter_name'):
        # Only explicit role labels can introduce another player's name here.
        # A lineup, historical stat sheet, etc. is still not verified current play.
        for block in blocks:
            m=re.search(r'(?:타자|打者)\s*[:：]?\s*([가-힣]{2,4})(?![가-힣])',block['text'])
            if m:result.update(batter_name=m.group(1),batter_role_text=block['text']);break
    return result


def role_line(text):
    """Explicit scorebug notation only; a lone number before a name is ambiguous."""
    text=text.strip(' |[]_')
    position=r'(?:CF|LF|RF|SS|DH|[123]B|C)'
    korean=r'([가-힣](?:\s*[가-힣]){1,3})(?=\s*(?:[\d.]|$))'
    match=re.search(r'^\s*[1-9]\s*[.:]?\s*'+position+r'\s*'+korean,text,re.I)
    if not match:match=re.search(r'^\s*B[.:]\s*'+korean,text,re.I)
    return match.group(1) if match else None


def scorebug_name(block,blocks):
    """Infer a lower batter row only inside an observed live count/pitcher panel.

    Geometry is relative to an image-derived panel, never a broadcaster ROI.
    The pitcher marker must be read, not inferred from a requested name/team.
    """
    panel=block.get('panel_region')
    if not panel:return None
    peers=[b for b in blocks if b.get('panel_region')==panel]
    if not any(re.search(r'(?<!\d)[0-3]\s*[-:]\s*[0-2](?!\d)',b['text']) for b in peers):return None
    y=block['region'][1]
    pitcher=[b for b in peers if re.match(r'^[|\[\]jIl\s]*P(?:\b|[.:])',b['text'],re.I) and b['region'][3]<y+.008]
    if not pitcher:return None
    # A single compact name followed by batting statistics or batting order.
    text=block['text'].strip(' |[]_')
    match=re.search(r'([가-힣](?:\s*[가-힣]){1,3})(?=\s*(?:[\d.]|$))',text)
    if not match:return None
    name=match.group(1)
    if re.sub(r'\s+','',name) in ('타수','안타','타율','홈런','삼진','투구수'):return None
    prefix=text[:match.start()]
    stats=re.search(r'타\s*수|안\s*타|\.\d{3}',text[match.end():])
    order=re.search(r'(?:^|[|\[\]\s])[1-9][.:]?\s*$',prefix)
    if not stats and not order:return None
    return name
