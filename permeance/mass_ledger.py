def accumulate_mass(model, concentration_bounds):
    points=[]
    owed_lo=owed_hi=0
    lost=[]
    carried=[]
    for sample,bounds in zip(model['samples'], concentration_bounds):
        lo,hi=bounds['lo'],bounds['hi']
        if lo is None or lost:
            low=high=None
            state='missing' if lo is None else 'unresolved'
        else:
            low=(sample['before']*lo+owed_lo)/model['area']
            high=(sample['before']*hi+owed_hi)/model['area']
            state='bounded' if low!=high else 'known'
        evidence=list(dict.fromkeys([*bounds['evidence'],*carried,*lost]))
        points.append(dict(id=sample['id'],time=sample['time'],lo=low,hi=high,state=state,evidence=evidence))
        if sample['removed']>0:
            if lo is None:
                lost.append(sample['id'])
            else:
                owed_lo+=sample['removed']*lo
                owed_hi+=sample['removed']*hi
                carried.append(sample['id'])
    return points
