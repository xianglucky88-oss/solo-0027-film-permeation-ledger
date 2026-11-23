from .contract import enum, invariant, num, records, unique_order
from .blank_correction import correct_sample


def parse(source):
    initial = num(source.get('initial_ml'),'初始体积（毫升）',0.1,1e4)
    blank = [dict(id=r['id'],time=num(r.get('time'),'空白时刻（分钟）',0),value=num(r.get('value'),'空白浓度',0,1e5))
             for r in records(source.get('blanks'),'空白读数',240)]
    unique_order(blank,'time','空白时标')
    samples=[]
    remaining=initial
    for row in records(source.get('samples'),'取样记录',240,2):
        status = enum(row.get('status'),('measured','censored','missing'),'浓度结果状态')
        removed = num(row.get('removed'),'抽取体积',0,remaining)
        added = num(row.get('added'),'补液体积',0,1e4)
        invariant(0.000001 <= remaining-removed+added <= 1e4 and removed<remaining,'取样必须保留受液，补液后体积不可越界')
        value = num(row.get('value'),'读数或报告限',0 if status=='measured' else .000001,1e5) if status!='missing' else None
        samples.append(dict(id=row['id'],time=num(row.get('time'),'取样时刻（分钟）',0),status=status,
                            removed=removed,added=added,before=remaining,after=remaining-removed+added,value=value))
        remaining = samples[-1]['after']
    unique_order(samples,'time','取样时标')
    return dict(samples=samples,blanks=blank,area=num(source.get('area'),'膜面积（平方厘米）',0.01,1e4),
                max_gap=num(source.get('max_blank_gap'),'空白可插值时长',0.001),
                threshold=num(source.get('threshold'),'单位面积透过阈值',0.000001))


def evaluate(model):
    volume,blanks,bounds=[],[],[]
    for r in model['samples']:
        key,time=r['id'],r['time']
        volume.append(dict(id=key,time=time,before=r['before'],after=r['after'],removed=r['removed'],added=r['added'],
                           state='restored' if r['removed']==r['added'] else 'shifted'))
        blank, corrected = correct_sample(model, r)
        blanks.append(blank)
        bounds.append(corrected)
    return dict(liquid=volume,blank=blanks,bounds=bounds)
