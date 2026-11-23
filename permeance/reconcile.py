def summarize(model, facts, outputs):
    result = []
    bounds = facts['bounds']
    for i, flux in enumerate(outputs['flux']):
        first,last = model['samples'][i:i+2]
        a,b = bounds[i:i+2]
        known = a['lo'] is not None and b['lo'] is not None
        if known:
            carry = first['before'] - first['removed']
            scale = model['area'] * (last['time'] - first['time'])
            lo = (last['before'] * b['lo'] - carry * a['hi']) / scale
            hi = (last['before'] * b['hi'] - carry * a['lo']) / scale
        else:
            lo = hi = None
        state = 'blind' if not known else 'negative' if hi < 0 else 'bounded' if lo != hi else 'known'
        result.append(dict(id=flux['id'],start=flux['start'],end=flux['end'],lo=lo,hi=hi,state=state,
                           evidence={'samples':[a['id'],b['id']], 'blanks':list(dict.fromkeys(a['evidence']+b['evidence']))}))
    return result
