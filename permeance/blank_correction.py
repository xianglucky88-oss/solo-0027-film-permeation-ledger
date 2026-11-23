from bisect import bisect_left


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


def correct_sample(model, r):
    key,time=r['id'],r['time']
    blank, evidence=interpolate_blank(model,time)
    reading = dict(id=key,time=time,value=blank,evidence=evidence,state='blind' if blank is None else 'known')
    if blank is None or r['value'] is None:
        lo=hi=None
        state='blind' if blank is None else 'missing'
    else:
        hi=max(0,r['value']-blank)
        lo=hi if r['status']=='measured' else 0
        state=r['status']
    bounds = dict(id=key,time=time,state=state,lo=lo,hi=hi,evidence=evidence)
    return reading, bounds
