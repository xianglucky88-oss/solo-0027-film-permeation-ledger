def flux_between(points):
    flux=[]
    for first,last in zip(points,points[1:]):
        dt=last['time']-first['time']
        known=first['lo'] is not None and last['lo'] is not None
        lo=(last['lo']-first['hi'])/dt if known else None
        hi=(last['hi']-first['lo'])/dt if known else None
        flux.append(dict(id=f"{first['id']}/{last['id']}",start=first['time'],end=last['time'],lo=lo,hi=hi,
                         state='blind' if not known else 'negative' if hi<0 else 'bounded' if lo!=hi else 'known',
                         evidence=[first['id'],last['id']]))
    return flux


def threshold_crossings(points, threshold):
    crossings=[]
    for point in points:
        hi,lo=point['hi'],point['lo']
        state='blind' if lo is None else 'verified' if lo>=threshold else 'possible' if hi>=threshold else 'below'
        crossings.append(dict(id=point['id'],time=point['time'],lo=lo,hi=hi,state=state))
    return crossings
