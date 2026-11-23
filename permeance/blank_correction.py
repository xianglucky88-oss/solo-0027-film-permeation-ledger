from bisect import bisect_left


GAP_STATES = ('conflict', 'open')


def interpolate_blank(model, time):
    points=model['blanks']
    i=bisect_left(points,time,key=lambda r:r['time'])
    if i<len(points) and points[i]['time']==time:
        return points[i]['value'],[points[i]['id']]
    if 0<i<len(points):
        a,b=points[i-1:i+1]
        evidence=[a['id'],b['id']]
        if b['time']-a['time']<=model['max_gap']:
            return a['value']+(b['value']-a['value'])*(time-a['time'])/(b['time']-a['time']),evidence
        return None,evidence
    return None,[]


def merge_gap(states, fallback):
    """把若干浓度缺口归并成一个下游状态：档位冲突优先，其次单侧开放界。"""
    for wanted in GAP_STATES:
        if wanted in states:
            return wanted
    return fallback


def restore_tiers(tiers):
    """每档按稀释倍数在线性浓度口径下还原到未稀释试液的可核实区间，再求交。

    低于报告限的档提供上界，超量程的档提供下界，缺测档不提供约束。
    """
    lo, hi = 0.0, None
    detail = {}
    for tier in tiers:
        status, dilution = tier['status'], tier['dilution']
        if status == 'measured':
            tlo, thi = tier['lo']*dilution, tier['hi']*dilution
        elif status == 'censored':
            tlo, thi = 0.0, tier['limit']*dilution
        elif status == 'overrange':
            tlo, thi = tier['limit']*dilution, None
        else:
            tlo = thi = None
        detail[tier['id']] = dict(state=status, lo=tlo, hi=thi)
        if status == 'missing':
            continue
        lo = max(lo, tlo)
        if thi is not None:
            hi = thi if hi is None else min(hi, thi)
    return lo, hi, detail


def correct_tiers(r, blank, evidence):
    """可用档区间求交后只做一次原口径空白校正。

    档间不相容保留冲突而不任选结果；只剩单侧界时不补成零或仪器满量程。
    """
    lo, hi, detail = restore_tiers(r['tiers'])
    if all(tier['status'] == 'missing' for tier in r['tiers']):
        state, lo, hi = ('blind' if blank is None else 'missing'), None, None
    elif hi is not None and lo > hi:
        state, lo, hi = 'conflict', None, None
    elif hi is None:
        state, lo, hi = 'open', None, None
    elif blank is None:
        state, lo, hi = 'blind', None, None
    else:
        state = 'measured' if lo == hi else 'censored' if lo == 0 else 'bounded'
        lo, hi = max(0, lo-blank), max(0, hi-blank)
    return dict(id=r['id'], time=r['time'], state=state, lo=lo, hi=hi, evidence=evidence, tiers=detail)


def correct_sample(model, r):
    key,time=r['id'],r['time']
    blank, evidence=interpolate_blank(model,time)
    reading = dict(id=key,time=time,value=blank,evidence=evidence,state='blind' if blank is None else 'known')
    if r['tiers'] is not None:
        return reading, correct_tiers(r, blank, evidence)
    if blank is None or r['value'] is None:
        lo=hi=None
        state='blind' if blank is None else 'missing'
    else:
        hi=max(0,r['value']-blank)
        lo=hi if r['status']=='measured' else 0
        state=r['status']
    bounds = dict(id=key,time=time,state=state,lo=lo,hi=hi,evidence=evidence)
    return reading, bounds
