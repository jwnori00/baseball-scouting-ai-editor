"""Conservative OCR context. State changes corroborate, never invent pitches."""
from dataclasses import dataclass
import re
from .scoreboard import normalize,identify


@dataclass(frozen=True)
class Count:
    balls:int
    strikes:int


def parse_count(text):
    match=re.fullmatch(r'\s*([0-3])\s*[-:]\s*([0-2])\s*',text)
    return Count(*map(int,match.groups())) if match else None


class IdentityContext:
    def __init__(self,player,max_age=20,field_window=5):
        self.player=player;self.max_age=max_age;self.field_window=field_window
        self.fields={};self.last_confirmed=None

    def update(self,time,readings):
        prefix=self.player.role+'_'
        name=readings.get(prefix+'name','').strip()
        old=self.fields.get(prefix+'name')
        # A changed name invalidates supporting fields; never combine one
        # player's name with another player's shirt number across substitution.
        if name and old and normalize(name)!=normalize(old[1]):self.fields={}
        for k,v in readings.items():
            if k.startswith(prefix) and v.strip():self.fields[k]=(time,v.strip())
        self.fields={k:v for k,v in self.fields.items() if time-v[0]<=self.field_window}
        values={k:v[1] for k,v in self.fields.items()}
        certain,evidence=identify(self.player,values)
        if name and not identify(self.player,{prefix+'name':name})[1]:self.last_confirmed=None
        if certain:self.last_confirmed=(time,evidence)
        if self.last_confirmed and time-self.last_confirmed[0]<=self.max_age:
            return True,self.last_confirmed[1]
        return False,evidence


def replay_text(readings):
    return normalize(readings.get('replay','')) in ('replay','repeticion','repeticao')
