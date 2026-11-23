from math import fsum, isclose

from .contract import ident, invariant, records


def read_windows(review, model):
    positions = {r['id']: i for i, r in enumerate(model['samples'])}
    for row in records(review.get('windows', []), '复核区间', 24):
        start = ident(row.get('first'), '起始取样')
        end = ident(row.get('last'), '结束取样')
        invariant(start in positions and end in positions and positions[start] < positions[end], '复核区间需指向递增的取样记录')
        yield row['id'], positions[start], positions[end]


def mass_terms(samples, start, end):
    """Shared earlier draws cancel; internal draws still contribute."""
    coeff = [samples[start]['removed']-samples[start]['before']]
    coeff.extend(r['removed'] for r in samples[start+1:end])
    coeff.append(samples[end]['before'])
    return [(i, weight) for i, weight in enumerate(coeff, start) if weight]


def window_delta(model, bounds, windows):
    samples = model['samples']
    result = []
    for key, start, end in windows:
        terms = mass_terms(samples, start, end)
        a, b = samples[start]['time'], samples[end]['time']
        holes = [samples[i]['id'] for i, _ in terms if bounds[i]['lo'] is None]
        lo = hi = None
        if not holes:
            lo = fsum(weight*bounds[i]['lo' if weight > 0 else 'hi'] for i, weight in terms)/model['area']
            hi = fsum(weight*bounds[i]['hi' if weight > 0 else 'lo'] for i, weight in terms)/model['area']
        result.append(dict(id=key, start=a, end=b, lo=lo, hi=hi, rate_lo=None if lo is None else lo/(b-a),
                           rate_hi=None if hi is None else hi/(b-a),
                           state='blind' if holes else 'negative' if hi < 0 else 'bounded' if lo != hi else 'known',
                           evidence={'weights_ml': {samples[i]['id']: weight for i, weight in terms}, 'missing': holes}))
    return result


def rate_agreement(flux, increments):
    result = []
    for older, newer in zip(flux, increments, strict=True):
        lo, hi = newer['lo'], newer['hi']
        prior_lo, prior_hi = older['lo'], older['hi']
        state = ('blind' if lo is None else 'recovered') if prior_lo is None or lo is None else (
            'same' if isclose(lo, prior_lo, rel_tol=1e-12, abs_tol=1e-12) and
            isclose(hi, prior_hi, rel_tol=1e-12, abs_tol=1e-12) else 'refined')
        result.append(dict(id=older['id'], lo=lo, hi=hi, prior_lo=prior_lo, prior_hi=prior_hi,
                           state=state, evidence=newer['evidence']))
    return result
