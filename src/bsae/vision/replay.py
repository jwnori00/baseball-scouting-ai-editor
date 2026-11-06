"""Exact decoded-frame overlap evidence; no claim of perceptual replay recall."""
from collections import deque


def exact_overlap(tail, head, *, minimum_samples=8):
    """Longest suffix/prefix match. Require changing images, reject static slates.

    Each item is a sampled SHA-256 frame fingerprint. Compression changes can
    prevent a match; absence of a match is not proof of absence of overlap.
    """
    tail,head=list(tail),list(head)
    for n in range(min(len(tail),len(head)),minimum_samples-1,-1):
        if tail[-n:]==head[:n] and len(set(head[:n]))>=4:
            return n
    return 0


class BoundaryTracker:
    def __init__(self, window=240):
        self.window=window
        self.previous_tail=[]
        self.tail=deque(maxlen=window)
        self.head=[]

    def add(self, row):
        h=row['frame_hash']
        self.tail.append(h)
        if len(self.head)<self.window:self.head.append(h)

    def finish_source(self):
        n=exact_overlap(self.previous_tail,self.head)
        self.previous_tail=list(self.tail)
        self.tail.clear();self.head=[]
        return n
