from collections import defaultdict

from .blank_correction import merge_gap
from .contract import ident, invariant, records


def draw_exposure(model, bounds):
    result = []
    for i, (sample, row) in enumerate(zip(model['samples'], bounds, strict=True)):
        removed = sample['removed']
        if removed == 0:
            continue
        evidence = [s['id'] for s in model['samples'][i+1:]]
        lo = None if row['lo'] is None else row['lo']*removed
        hi = None if row['hi'] is None else row['hi']*removed
        result.append(dict(id=sample['id'], lo=lo, hi=hi, removed=removed,
                           count=len(evidence), state=merge_gap((row['state'],), 'blind') if lo is None else 'bounded' if lo != hi else 'known',
                           evidence={'downstream': evidence, 'blanks': row['evidence']}))
    return result


def blank_footprint(blanks, bounds):
    groups = defaultdict(list)
    for blank, bound in zip(blanks, bounds, strict=True):
        for key in blank['evidence']:
            groups[key].append((blank, bound))
    return [dict(id=key, count=len(rows), known=sum(blank['state'] == 'known' for blank, _ in rows),
                 state='shared' if len(rows) > 1 else 'single',
                 evidence={blank['id']: {'blank': blank['state'], 'bound': bound['state']} for blank, bound in rows})
            for key, rows in sorted(groups.items())]


def threshold_review(crossings, mass):
    earliest = next((i for i, r in enumerate(crossings) if r['state'] != 'below'), None)
    proved = next((i for i, r in enumerate(crossings) if r['state'] == 'verified'), None)
    evidence = {'first_not_excluded': None if earliest is None else crossings[earliest]['id'],
                'first_verified': None if proved is None else crossings[proved]['id'],
                'unknown': [r['id'] for r in mass[:proved] if r['lo'] is None]}
    return [dict(id='first-observation', start=None if earliest is None else crossings[earliest]['time'],
                 end=None if proved is None else crossings[proved]['time'],
                 state='verified' if proved is not None else 'partial' if earliest is not None else 'below', evidence=evidence)]


def volume_checkpoints(review, liquid):
    positions = {r['id']: r for r in liquid}
    result = []
    for row in records(review.get('checkpoints', []), '池量核对点', 24):
        sample = ident(row.get('sample'), '池量核对的取样号')
        invariant(sample in positions, '池量核对引用未知取样')
        result.append((row, positions[sample]))
    return result
