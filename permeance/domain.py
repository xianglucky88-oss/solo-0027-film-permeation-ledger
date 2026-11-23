from .contract import enum, invariant, num, records, unique_order
from .blank_correction import correct_sample


def parse_tiers(rows):
    """一个取样点的多档测量：每档有独立编号、稀释倍数、状态及读数区间或限值。"""
    tiers=[]
    for row in records(rows,'测量档位',24,1):
        status=enum(row.get('status'),('measured','censored','overrange','missing'),'档位状态')
        dilution=num(row.get('dilution'),'稀释倍数',1,1e6)
        lo=hi=limit=None
        if status=='measured':
            if row.get('value') is not None:
                invariant(row.get('lo') is None and row.get('hi') is None,'档位读数与数值区间不应并存')
                lo=hi=num(row.get('value'),'档位读数',0,1e5)
            else:
                lo=num(row.get('lo'),'档位区间下界',0,1e5)
                hi=num(row.get('hi'),'档位区间上界',0,1e5)
                invariant(lo<=hi,'档位区间下界不可超过上界')
        elif status in ('censored','overrange'):
            limit=num(row.get('limit'),'档位限值',.000001,1e5)
        tiers.append(dict(id=row['id'],status=status,dilution=dilution,lo=lo,hi=hi,limit=limit))
    return tiers


def parse(source):
    initial = num(source.get('initial_ml'),'初始体积（毫升）',0.1,1e4)
    blank = [dict(id=r['id'],time=num(r.get('time'),'空白时刻（分钟）',0),value=num(r.get('value'),'空白浓度',0,1e5))
             for r in records(source.get('blanks'),'空白读数',240)]
    unique_order(blank,'time','空白时标')
    samples=[]
    remaining=initial
    for row in records(source.get('samples'),'取样记录',240,2):
        removed = num(row.get('removed'),'抽取体积',0,remaining)
        added = num(row.get('added'),'补液体积',0,1e4)
        invariant(0.000001 <= remaining-removed+added <= 1e4 and removed<remaining,'取样必须保留受液，补液后体积不可越界')
        if 'tiers' in row:
            invariant(row.get('status') is None and row.get('value') is None,'多档取样不应再列单值状态或读数')
            tiers,status,value = parse_tiers(row['tiers']),None,None
        else:
            tiers = None
            status = enum(row.get('status'),('measured','censored','missing'),'浓度结果状态')
            value = num(row.get('value'),'读数或报告限',0 if status=='measured' else .000001,1e5) if status!='missing' else None
        samples.append(dict(id=row['id'],time=num(row.get('time'),'取样时刻（分钟）',0),status=status,
                            removed=removed,added=added,before=remaining,after=remaining-removed+added,value=value,tiers=tiers))
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
