"""One-to-one interval evaluation. Unprovided measurements remain unknown."""
import csv
import statistics
from pathlib import Path

UNKNOWN = 'NOT_EVALUATED'


def write_csv(path, rows):
    rows = list(rows)
    fields = list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def evaluate(predicted, truth, *, iou_threshold=.5, manual_seconds=None, assisted_seconds=None):
    def valid(items):
        import math
        for e in items:
            if not all(math.isfinite(e[k]) for k in ('start','end')) or not 0 <= e['start'] < e['end']:
                raise ValueError('잘못된 평가 구간')
    valid(predicted); valid(truth)
    if not 0 < iou_threshold <= 1:
        raise ValueError('IoU 범위 오류')
    pairs = []
    for i,p in enumerate(predicted):
        for j,t in enumerate(truth):
            overlap = max(0, min(p['end'],t['end'])-max(p['start'],t['start']))
            union = max(p['end'],t['end'])-min(p['start'],t['start'])
            if overlap/union >= iou_threshold:
                pairs.append((overlap/union,i,j))
    # Deterministic greedy IoU matching; each event can count at most once.
    used_p, used_t, matches = set(),set(),[]
    for score,i,j in sorted(pairs, reverse=True):
        if i not in used_p and j not in used_t:
            used_p.add(i); used_t.add(j); matches.append((i,j))
    n = len(matches)
    identities = [(predicted[i].get('player_id'),truth[j].get('player_id')) for i,j in matches if truth[j].get('player_id') is not None]
    follows = [(predicted[i],truth[j]) for i,j in matches if truth[j].get('followup_end') is not None]
    truth_plates = {t.get('plate_id') for t in truth if t.get('plate_id') is not None}
    hit_plates = {truth[j].get('plate_id') for i,j in matches if predicted[i].get('plate_id') is not None}
    false_seconds = 0
    for i,j in matches:
        p,t=predicted[i],truth[j]
        false_seconds += max(0,t['start']-p['start']) + max(0,p['end']-t['end'])
    false_seconds += sum(p['end']-p['start'] for i,p in enumerate(predicted) if i not in used_p)
    duration = sum(p['end']-p['start'] for p in predicted)
    report = dict(truth_count=len(truth), candidate_count=len(predicted), matched=n,
        matching='greedy_one_to_one_IoU', iou_threshold=iou_threshold,
        pitch_recall=n/len(truth) if truth else UNKNOWN,
        precision=n/len(predicted) if predicted and truth else UNKNOWN,
        plate_recall=len(hit_plates & truth_plates)/len(truth_plates) if truth_plates and any(p.get('plate_id') for p in predicted) else UNKNOWN,
        identity_accuracy=sum(a==b for a,b in identities)/len(identities) if identities else UNKNOWN,
        start_error_median=statistics.median(abs(predicted[i]['start']-truth[j]['start']) for i,j in matches) if matches else UNKNOWN,
        end_error_median=statistics.median(abs(predicted[i]['end']-truth[j]['end']) for i,j in matches) if matches else UNKNOWN,
        missing_play_rate=1-n/len(truth) if truth else UNKNOWN,
        followup_preservation=sum(p['end'] >= t['followup_end'] for p,t in follows)/len(follows) if follows else UNKNOWN,
        irrelevant_duration_ratio=false_seconds/duration if duration and truth else UNKNOWN,
        review_time_savings=1-assisted_seconds/manual_seconds if manual_seconds and manual_seconds>0 and assisted_seconds is not None and assisted_seconds>=0 else UNKNOWN)
    return report
