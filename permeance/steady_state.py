"""稳态通量与滞后复核。

模型只接受同一恒定暴露条件下的稳态段：预测单位面积累计透过量为
``M = J * (t - L)``，其中 J 为正的稳态通量，L 为滞后（截距在横轴的位置）。
拟合点与留出点都沿用既有累计量的证据区间 [lo, hi]，区间不改成中点，
缺证点（lo/hi 为 None）不得悄悄删除，而是让对应起点失去资格。

在 (J, b) 平面（b = -J*L）中，每个区间点给出两条线性半平面，
全部约束（含资料管理员指定的 J、L 范围与 L 不晚于稳态起点）都是半平面，
故可行解释集合是凸多边形；用半平面逐次裁剪求精确可行域，
再由顶点读出 J 与 L 的联合范围。留出点用同一组 (J, L) 裁剪，逐点不重选参数。
"""

from .contract import ident, invariant, num, records

EPS = 1e-12


def read_steady(review, mass):
    """解析资料管理员在计算前指定的稳态复核方案，并把拟合/留出点绑定到累计证据。"""
    spec = review['steady_state']
    positions = {point['id']: i for i, point in enumerate(mass)}
    slope = spec['slope']
    lag = spec['lag']
    slope_lo, slope_hi = num(slope['lo'], '稳态通量下界', 1e-9), num(slope['hi'], '稳态通量上界', 1e-9)
    lag_lo, lag_hi = num(lag['lo'], '滞后下界', 0), num(lag['hi'], '滞后上界', 0)
    invariant(slope_lo < slope_hi, '稳态通量范围必须为正且上下界分离')
    invariant(lag_lo < lag_hi, '滞后范围上下界必须分离')
    min_points = int(num(spec.get('min_fit_points', 2), '最少拟合点数', 2, 240))
    min_span = num(spec.get('min_fit_span', 0), '拟合点最小时长（分钟）', 0)

    starts = []
    allowed = set()
    for row in records(spec.get('starts', []), '稳态起点', 240, 1):
        start_id = ident(row.get('sample'), '稳态起点取样')
        invariant(start_id in positions, '稳态起点引用未知取样')
        fit_ids = records(row.get('fit', []), '拟合点', 240, min_points)
        hold_ids = records(row.get('holdout', []), '独立复核点', 240, 1)
        fit = [ident(item.get('sample'), '拟合取样') for item in fit_ids]
        holdout = [ident(item.get('sample'), '复核取样') for item in hold_ids]
        invariant(start_id not in fit and start_id not in holdout, '起点本身不得充当拟合或复核点')
        invariant(len(set(fit)) == len(fit) and len(set(holdout)) == len(holdout), '拟合或复核点重复')
        invariant(not set(fit) & set(holdout), '同一取样不得既是拟合点又是复核点')
        for sample_id in [*fit, *holdout]:
            invariant(sample_id in positions, '稳态复核引用未知取样')
        chain = [start_id, *fit, *holdout]
        invariant(all(positions[a] < positions[b] for a, b in zip(chain, chain[1:])),
                  '稳态起点、拟合点、复核点必须按取样时刻严格递增')
        allowed.add(start_id)
        starts.append(dict(id=start_id, fit=fit, holdout=holdout))
    invariant(len(allowed) == len(starts), '稳态起点重复')
    return dict(slope_lo=slope_lo, slope_hi=slope_hi, lag_lo=lag_lo, lag_hi=lag_hi,
                min_points=min_points, min_span=min_span, starts=starts)


def clip(polygon, a, b, c):
    """保留满足 a*J + b*bvar <= c 的半平面；输入/输出均为 (J, b) 顶点序列。"""
    if not polygon:
        return polygon
    kept = []

    def inside(vertex):
        return a * vertex[0] + b * vertex[1] <= c + EPS

    previous = polygon[-1]
    previous_inside = inside(previous)
    for current in polygon:
        current_inside = inside(current)
        if current_inside:
            if not previous_inside:
                denom = a * (current[0] - previous[0]) + b * (current[1] - previous[1])
                if denom != 0:
                    ratio = (c - (a * previous[0] + b * previous[1])) / denom
                    ratio = min(1.0, max(0.0, ratio))
                    kept.append((previous[0] + ratio * (current[0] - previous[0]),
                                 previous[1] + ratio * (current[1] - previous[1])))
            kept.append(current)
        elif previous_inside:
            denom = a * (current[0] - previous[0]) + b * (current[1] - previous[1])
            if denom != 0:
                ratio = (c - (a * previous[0] + b * previous[1])) / denom
                ratio = min(1.0, max(0.0, ratio))
                kept.append((previous[0] + ratio * (current[0] - previous[0]),
                             previous[1] + ratio * (current[1] - previous[1])))
        previous, previous_inside = current, current_inside
    return dedupe(kept)


def dedupe(polygon):
    result = []
    for vertex in polygon:
        if not result or abs(vertex[0] - result[-1][0]) > EPS or abs(vertex[1] - result[-1][1]) > EPS:
            result.append(vertex)
    if len(result) > 1 and abs(result[0][0] - result[-1][0]) <= EPS and abs(result[0][1] - result[-1][1]) <= EPS:
        result.pop()
    return result


def initial_region(plan):
    """以 (J, b) 的大矩形起步，b 范围由给定 J、L 范围的乘积界覆盖。"""
    bound = max(abs(plan['slope_lo'] * plan['lag_hi']), abs(plan['slope_hi'] * plan['lag_hi']),
                abs(plan['slope_lo'] * plan['lag_lo']), abs(plan['slope_hi'] * plan['lag_lo']), 1.0) * 4
    j0, j1, b0, b1 = plan['slope_lo'], plan['slope_hi'], -bound, bound
    return [(j0, b0), (j1, b0), (j1, b1), (j0, b1)]


def point_constraints(point):
    """证据区间 lo <= J*(t-L) <= hi 转为 (J, b) 半平面，b = -J*L。"""
    t = point['time']
    return [(-t, -1.0, -point['lo']), (t, 1.0, point['hi'])]


def feasible_ranges(polygon):
    j_values = [vertex[0] for vertex in polygon]
    l_values = [-vertex[1] / vertex[0] for vertex in polygon]
    return (min(j_values), max(j_values)), (min(l_values), max(l_values))


def evaluate_start(plan, mass, start):
    """对一个允许起点保留全部指定拟合点，返回其可行解释与留出核对。"""
    index = {point['id']: point for point in mass}
    fit_points = [index[sample_id] for sample_id in start['fit']]
    hold_points = [index[sample_id] for sample_id in start['holdout']]
    blind = [point['id'] for point in [*fit_points, *hold_points] if point['lo'] is None]
    start_time = index[start['id']]['time']
    base = dict(id=start['id'], time=start_time,
                fit=[point['id'] for point in fit_points], holdout=[point['id'] for point in hold_points],
                fit_evidence={point['id']: dict(lo=point['lo'], hi=point['hi'], state=point['state'],
                                                 evidence=point['evidence']) for point in fit_points},
                holdout_evidence={point['id']: dict(lo=point['lo'], hi=point['hi'], state=point['state'],
                                                    evidence=point['evidence']) for point in hold_points})
    if blind:
        return dict(base, state='evidence_incomplete', reason='缺证点不得删除：' + '、'.join(blind),
                    slope_lo=None, slope_hi=None, lag_lo=None, lag_hi=None,
                    fit_polygon=[], surviving_polygon=[], holdout_checks=[])
    invariant(len(fit_points) >= plan['min_points'], '拟合点数少于资料管理员指定的最少点数')
    span = fit_points[-1]['time'] - fit_points[0]['time']
    invariant(span >= plan['min_span'], '拟合时长短于指定的最小时长')

    polygon = initial_region(plan)
    # 管理员指定的通量与滞后范围：L = -b/J，J 恒正，故 J*L = -b。
    polygon = clip(polygon, 1.0, 0.0, plan['slope_hi'])
    polygon = clip(polygon, -1.0, 0.0, -plan['slope_lo'])
    # lag_lo <= -b/J => J*lag_lo + b <= 0
    polygon = clip(polygon, plan['lag_lo'], 1.0, 0.0)
    # -b/J <= lag_hi => 0 <= J*lag_hi + b
    polygon = clip(polygon, -plan['lag_hi'], -1.0, 0.0)
    # 滞后不得晚于该稳态起点：L <= t_start => J*t_start + b >= 0。
    polygon = clip(polygon, -start_time, -1.0, 0.0)
    for point in fit_points:
        for a, b, c in point_constraints(point):
            polygon = clip(polygon, a, b, c)
        if not polygon:
            break
    fit_polygon = list(polygon)
    checks = []
    surviving = list(polygon)
    for point in hold_points:
        before = len(surviving)
        for a, b, c in point_constraints(point):
            surviving = clip(surviving, a, b, c)
        checks.append(dict(id=point['id'], time=point['time'], lo=point['lo'], hi=point['hi'],
                           state=point['state'], evidence=point['evidence'],
                           feasible=bool(surviving),
                           note='同一组参数仍落在该点证据区间' if surviving
                           else f'无共同参数可落入该点区间（裁剪前顶点 {before}）'))
    if not fit_polygon:
        return dict(base, state='no_solution', reason='不存在同时落入全部拟合点证据区间的 (J, L)',
                    slope_lo=None, slope_hi=None, lag_lo=None, lag_hi=None,
                    fit_polygon=[], surviving_polygon=[], holdout_checks=checks)
    (j_lo, j_hi), (l_lo, l_hi) = feasible_ranges(fit_polygon)
    if not surviving:
        return dict(base, state='no_solution', reason='拟合可行但没有同一组参数通过全部独立复核点',
                    slope_lo=j_lo, slope_hi=j_hi, lag_lo=l_lo, lag_hi=l_hi,
                    fit_polygon=fit_polygon, surviving_polygon=[], holdout_checks=checks)
    (sj_lo, sj_hi), (sl_lo, sl_hi) = feasible_ranges(surviving)
    return dict(base, state='feasible', reason='同一组斜率与滞后通过全部拟合点及留出点',
                slope_lo=sj_lo, slope_hi=sj_hi, lag_lo=sl_lo, lag_hi=sl_hi,
                fit_slope_lo=j_lo, fit_slope_hi=j_hi, fit_lag_lo=l_lo, fit_lag_hi=l_hi,
                fit_polygon=fit_polygon, surviving_polygon=surviving, holdout_checks=checks)


def summarize_steady(results, mass, threshold):
    """汇总全部起点；可行起点滞后互不相容时不合并为确定参数，分别报告。"""
    feasible = [row for row in results if row['state'] == 'feasible']
    compatible = True
    shared = None
    if feasible:
        lag_window = [max(row['lag_lo'] for row in feasible), min(row['lag_hi'] for row in feasible)]
        slope_window = [max(row['slope_lo'] for row in feasible), min(row['slope_hi'] for row in feasible)]
        compatible = lag_window[0] <= lag_window[1] + EPS and slope_window[0] <= slope_window[1] + EPS
        if compatible:
            shared = dict(lag_lo=lag_window[0], lag_hi=lag_window[1],
                          slope_lo=slope_window[0], slope_hi=slope_window[1])
    # 原累计量与过限判断保持既有口径，这里只引用，不改写。
    crossings = [dict(id=point['id'], time=point['time'], lo=point['lo'], hi=point['hi'])
                 for point in mass if point['lo'] is not None and point['hi'] is not None
                 and point['hi'] >= threshold]
    if not feasible:
        overall = 'confirmed_no_solution'
    elif compatible:
        overall = 'coexistent'
    else:
        overall = 'incompatible_lags'
    return dict(overall=overall, feasible_starts=[row['id'] for row in feasible],
                compatible=compatible, shared_parameters=shared,
                incompatible_pairs=[],
                threshold_observations=crossings,
                note='原累计量证据区间与过限判断不变；稳态复核只引用既有 mass/crossing 结果')


def analyze_steady_state(review, mass, threshold):
    plan = read_steady(review, mass)
    results = [evaluate_start(plan, mass, start) for start in plan['starts']]
    summary = summarize_steady(results, mass, threshold)
    if summary['overall'] == 'incompatible_lags':
        pairs = []
        feasible = [row for row in results if row['state'] == 'feasible']
        for i, left in enumerate(feasible):
            for right in feasible[i + 1:]:
                lag_overlap = min(left['lag_hi'], right['lag_hi']) + EPS >= \
                    max(left['lag_lo'], right['lag_lo'])
                slope_overlap = min(left['slope_hi'], right['slope_hi']) + EPS >= \
                    max(left['slope_lo'], right['slope_lo'])
                if not lag_overlap or not slope_overlap:
                    pairs.append([left['id'], right['id']])
        summary['incompatible_pairs'] = pairs
    return dict(plan={key: value for key, value in plan.items() if key != 'starts'},
                starts=results, summary=summary)
