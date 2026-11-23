from math import fsum

from .contract import enum, invariant, interval, num, obj, records, unique_order

KINDS = ('heat', 'hold', 'cool')


def read_program(block):
    """温度程序只消费自己的温度样点，不拿取样浓度补温度证据。"""
    block = obj(block, '温度程序')
    max_gap = num(block.get('max_gap'), '温度最大插值间隔（分钟）', 0.001)
    segments = []
    for row in records(block.get('segments'), '温度程序段', 24, 1):
        start, end = interval(row.get('start'), row.get('end'), '程序段时刻（分钟）')
        lo0 = num(row.get('lo_start'), '段起目标下限', -100, 1000)
        lo1 = num(row.get('lo_end'), '段止目标下限', -100, 1000)
        hi0 = num(row.get('hi_start'), '段起目标上限', -100, 1000)
        hi1 = num(row.get('hi_end'), '段止目标上限', -100, 1000)
        invariant(lo0 < hi0 and lo1 < hi1, '目标温度带的下限必须低于上限')
        segments.append(dict(id=row['id'], kind=enum(row.get('kind'), KINDS, '程序段类型'),
                             start=start, end=end, lo=(lo0, lo1), hi=(hi0, hi1),
                             cold=num(row.get('cold_budget'), '冷侧度分钟预算', 0),
                             hot=num(row.get('hot_budget'), '热侧度分钟预算', 0)))
    unique_order(segments, 'start', '程序段起点')
    for earlier, later in zip(segments, segments[1:]):
        invariant(earlier['end'] <= later['start'], '温度程序段不能重叠')
    readings = [dict(id=r['id'], time=num(r.get('time'), '温度样点时刻（分钟）', 0),
                     value=num(r.get('value'), '温度读数', -100, 1000))
                for r in records(block.get('readings'), '温度样点', 240)]
    unique_order(readings, 'time', '温度样点时标')
    return max_gap, segments, readings


def split_area(da, db, width):
    """线性偏差正部的面积及越界子区间：越过边界按实际交点切开。"""
    if da <= 0 and db <= 0:
        return 0.0, None
    if da >= 0 and db >= 0:
        return (da + db) / 2 * width, (0.0, width)
    cross = width * da / (da - db)
    if da > 0:
        return da / 2 * cross, (0.0, cross)
    return db / 2 * (width - cross), (cross, width)


def merge_spans(spans):
    merged = []
    for a, b in spans:
        if merged and merged[-1][1] == a:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return merged


def evaluate_segment(segment, readings, max_gap):
    s, e = segment['start'], segment['end']
    lo0, lo1 = segment['lo']
    hi0, hi1 = segment['hi']

    def low(t):
        return lo0 + (lo1 - lo0) * (t - s) / (e - s)

    def high(t):
        return hi0 + (hi1 - hi0) * (t - s) / (e - s)

    covered, cold_parts, hot_parts, cold_spans, hot_spans = [], [], [], [], []
    for first, second in zip(readings, readings[1:]):
        t0, t1 = first['time'], second['time']
        if t1 - t0 > max_gap:
            continue
        a, b = max(t0, s), min(t1, e)
        if not a < b:
            continue
        covered.append((a, b))
        slope = (second['value'] - first['value']) / (t1 - t0)
        va = first['value'] + slope * (a - t0)
        vb = first['value'] + slope * (b - t0)
        area, span = split_area(low(a) - va, low(b) - vb, b - a)
        cold_parts.append(area)
        if span is not None:
            cold_spans.append((a + span[0], a + span[1]))
        area, span = split_area(va - high(a), vb - high(b), b - a)
        hot_parts.append(area)
        if span is not None:
            hot_spans.append((a + span[0], a + span[1]))
    gaps, cursor = [], s
    for a, b in covered:
        if a > cursor:
            gaps.append((cursor, a))
        cursor = b
    if cursor < e:
        gaps.append((cursor, e))
    cold_area, hot_area = fsum(cold_parts), fsum(hot_parts)
    state = 'exceeded' if cold_area > segment['cold'] or hot_area > segment['hot'] else 'lacking' if gaps else 'within'
    violations = [dict(side='cold', start=a, end=b) for a, b in merge_spans(cold_spans)]
    violations += [dict(side='hot', start=a, end=b) for a, b in merge_spans(hot_spans)]
    violations.sort(key=lambda row: (row['start'], row['side']))
    return dict(id=segment['id'], kind=segment['kind'], start=s, end=e,
                cold_area=cold_area, hot_area=hot_area, state=state,
                evidence=dict(cold_budget=segment['cold'], hot_budget=segment['hot'],
                              violations=violations,
                              gaps=[dict(start=a, end=b) for a, b in gaps],
                              points=[dict(id=r['id'], time=r['time'], value=r['value'])
                                      for r in readings if s <= r['time'] <= e]))


def verify_program(block):
    """逐段判定并给出整个程序的结论；结论不回写原透过计算。"""
    max_gap, segments, readings = read_program(block)
    rows = [evaluate_segment(segment, readings, max_gap) for segment in segments]
    states = {row['id']: row['state'] for row in rows}
    verdict = 'exceeded' if 'exceeded' in states.values() else 'lacking' if 'lacking' in states.values() else 'within'
    rows.append(dict(id='整个程序', kind=None, start=None, end=None, cold_area=None, hot_area=None,
                     state=verdict, evidence=dict(segments=states)))
    return rows
