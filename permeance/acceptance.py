"""盲样验收：揭盲后按同源组核对重复性与参照区间。

工作台只接收按盲码登记的锁定检测结果，揭盲表在验收时才提供。同源组的
重复读数只是同一次独立试验的内部重复性，不能拆成多个独立组；检测条件
更换后也不能与旧条件结果拼组。每项核对都区分“任意取值都合格／任意取值
都不合格／只有部分取值合格”，联合结论按同一组真值能否同时满足两项判断，
不允许分别挑选有利取值。
"""

from .contract import ContractError, enum, ident, invariant, num, obj


def _rows(value, label, maximum, minimum=1):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ContractError(f'{label}应含 {minimum} 至 {maximum} 条记录')
    return value

# 单项核对与联合判定的三态
PASS = 'pass'          # 任意取值都合格
FAIL = 'fail'          # 任意取值都不合格
PARTIAL = 'partial'    # 只有部分取值合格
INSUFFICIENT = 'insufficient'  # 可参与证明的读数不足，无法证明

# 浓度档与整批结论
ACCEPTED = 'accepted'
REJECTED = 'rejected'
PENDING = 'pending'


def _num(row, key, label, low=0.0):
    return num(row.get(key), label, low, 1e9)


def parse_readings(locked):
    """解析锁定检测结果，每个盲码至多一条冻结结果。"""
    locked = obj(locked, '锁定检测结果')
    readings = {}
    for row in _rows(locked.get('results'), '锁定检测结果', 600):
        item = obj(row, '锁定检测结果')
        code = ident(item.get('code'), '盲码')
        if code in readings:
            raise ContractError(f'同一盲码 {code} 存在多个冻结结果')
        condition = ident(item.get('condition'), '检测条件标识')
        status = enum(item.get('status'), ('measured', 'censored', 'missing'), '检测结果状态')
        if status == 'missing':
            # 缺测不参与证明，只登记其存在与检测条件
            value = report_limit = None
        else:
            value = _num(item, 'value', '读数或报告限', 0.0 if status == 'measured' else 1e-9)
            report_limit = value if status == 'censored' else None
        readings[code] = dict(code=code, condition=condition, status=status,
                              value=value, report_limit=report_limit)
    return readings


def parse_unblinding(reveal, readings):
    """解析揭盲表：指明同源组、浓度档和已定参照区间。"""
    reveal = obj(reveal, '揭盲表')
    version = ident(reveal.get('version'), '揭盲版本')
    levels = {}
    for row in _rows(reveal.get('levels'), '必查浓度档', 100):
        level = obj(row, '必查浓度档')
        level_id = ident(level.get('id'), '浓度档标识')
        if level_id in levels:
            raise ContractError(f'浓度档标识重复：{level_id}')
        lo = _num(level, 'reference_lo', '参照区间下界')
        hi = _num(level, 'reference_hi', '参照区间上界')
        invariant(lo < hi, '参照区间上界必须大于下界')
        required = level.get('required_groups')
        if type(required) is not int or not 1 <= required <= 100:
            raise ContractError('独立且确证合格组数量应为 1 至 100 的整数')
        tolerance = level.get('tolerance', 0)
        num(tolerance, '参照允差', 0, 1e9)
        levels[level_id] = dict(id=level_id, lo=lo, hi=hi, required=required, tolerance=tolerance)

    groups = {}
    mapped = set()
    for row in _rows(reveal.get('assignments'), '揭盲登记', 600):
        entry = obj(row, '揭盲登记')
        code = ident(entry.get('code'), '盲码')
        group_id = ident(entry.get('group'), '同源组标识')
        level_id = ident(entry.get('level'), '浓度档标识')
        invariant(code in readings, f'盲码 {code} 没有锁定检测结果，不能揭盲')
        invariant(code not in mapped, f'盲码 {code} 在揭盲表中重复登记')
        invariant(level_id in levels, f'盲码 {code} 指向未知浓度档 {level_id}')
        mapped.add(code)
        groups.setdefault(group_id, []).append((code, level_id))

    unused = sorted(set(readings) - mapped)
    if unused:
        raise ContractError(f'锁定结果存在未揭盲的盲码：{"、".join(unused)}')

    # 同一同源组必须落在同一浓度档，并在同一检测条件下完成
    assembled = {}
    for group_id, members in groups.items():
        member_levels = {level_id for _, level_id in members}
        invariant(len(member_levels) == 1, f'同源组 {group_id} 跨越多个浓度档')
        conditions = {readings[code]['condition'] for code, _ in members}
        invariant(len(conditions) == 1, f'同源组 {group_id} 混入不同检测条件的结果，不能拼组')
        assembled[group_id] = dict(id=group_id, level=next(iter(member_levels)),
                                   condition=next(iter(conditions)),
                                   codes=[code for code, _ in members])
    return version, levels, assembled


def reading_interval(reading):
    """把一条读数化为真值闭区间；缺测返回 None。

    低限（censored）记录按零至报告限的区间处理，既不当作零也不删除。
    """
    if reading['status'] == 'missing':
        return None
    if reading['status'] == 'censored':
        return 0.0, reading['report_limit']
    return reading['value'], reading['value']


def repeatability_verdict(intervals, limit):
    """组内最大两两绝对差的三态判定。"""
    if len(intervals) < 2:
        return INSUFFICIENT, None, None
    # 最小可能极差：所有区间存在公共取值时可为 0，否则为最小错开量
    min_spread = max(0.0, max(lo for lo, _ in intervals) - min(hi for _, hi in intervals))
    max_spread = max(hi for _, hi in intervals) - min(lo for lo, _ in intervals)
    if max_spread <= limit:
        verdict = PASS
    elif min_spread > limit:
        verdict = FAIL
    else:
        verdict = PARTIAL
    return verdict, min_spread, max_spread


def reference_verdict(intervals, ref_lo, ref_hi, tolerance):
    """对组内每条读数检查至参照区间距离的三态判定。"""
    if not intervals:
        return INSUFFICIENT
    states = set()
    for lo, hi in intervals:
        # 读数区间上距参照区间最近／最远的真值距离
        nearest = max(ref_lo - hi, 0.0, lo - ref_hi)
        farthest = max(ref_hi - lo, hi - ref_lo)
        if farthest <= tolerance:
            states.add(PASS)
        elif nearest > tolerance:
            states.add(FAIL)
        else:
            states.add(PARTIAL)
    if states == {PASS}:
        return PASS
    if states == {FAIL}:
        return FAIL
    return PARTIAL


def joint_verdict(intervals, limit, ref_lo, ref_hi, tolerance):
    """按同一组真值同时满足重复性与参照核对的联合三态。

    在每条读数的区间内取同一组真值，不允许重复性与参照核对分别挑选
    有利取值。可行域取“参照允差带”与各读数区间的交集。
    """
    if len(intervals) < 2:
        return INSUFFICIENT
    band_lo, band_hi = ref_lo - tolerance, ref_hi + tolerance
    feasible = []
    for lo, hi in intervals:
        overlap_lo, overlap_hi = max(lo, band_lo), min(hi, band_hi)
        if overlap_lo > overlap_hi:
            return FAIL  # 该读数没有任何真值能满足参照核对
        feasible.append((overlap_lo, overlap_hi))
    # 在可行域内能达到的最小／最大极差
    min_spread = max(0.0, max(lo for lo, _ in feasible) - min(hi for _, hi in feasible))
    max_spread = max(hi for _, hi in feasible) - min(lo for lo, _ in feasible)
    if max_spread <= limit:
        return PASS
    if min_spread > limit:
        return FAIL
    return PARTIAL


def analyze_acceptance(payload):
    """盲样验收主入口，返回可封存的验收成果结构。"""
    payload = obj(payload, '盲样验收包')
    run_id = ident(payload.get('id'), '验收批次标识')
    readings = parse_readings(obj(payload.get('locked'), '锁定检测结果'))
    version, levels, groups = parse_unblinding(obj(payload.get('unblinding'), '揭盲表'), readings)
    repeat_limit = num(payload.get('repeatability_limit'), '重复性最大允许极差', 1e-9, 1e9)

    group_rows = []
    for group_id in sorted(groups):
        group = groups[group_id]
        level = levels[group['level']]
        member_rows, intervals, missing_codes = [], [], []
        for code in group['codes']:
            reading = readings[code]
            interval = reading_interval(reading)
            member_rows.append(dict(code=code, status=reading['status'],
                                    value=reading['value'],
                                    report_limit=reading['report_limit'],
                                    participates=interval is not None))
            if interval is None:
                missing_codes.append(code)
            else:
                intervals.append(interval)

        rep, rep_min, rep_max = repeatability_verdict(intervals, repeat_limit)
        ref = reference_verdict(intervals, level['lo'], level['hi'], level['tolerance'])
        joint = joint_verdict(intervals, repeat_limit, level['lo'], level['hi'], level['tolerance'])

        if joint == PASS:
            confirmed = True
        elif joint == FAIL:
            confirmed = False
        else:
            # PARTIAL（仅部分取值可行）或 INSUFFICIENT（可参与证明的读数不足）
            confirmed = None  # 都不能确证，落待补
        group_rows.append(dict(
            id=group_id, level=group['level'], condition=group['condition'],
            state={True: ACCEPTED, False: REJECTED, None: PENDING}[confirmed],
            repeatability=rep, reference=ref, joint=joint,
            repeat_min=rep_min, repeat_max=rep_max,
            readings=member_rows, missing=missing_codes,
            evidence=dict(unblinding_version=version, repeatability_limit=repeat_limit,
                          reference=[level['lo'], level['hi']], tolerance=level['tolerance'],
                          locked_codes=list(group['codes']))))

    level_rows = []
    for level_id in sorted(levels):
        level = levels[level_id]
        members = [row for row in group_rows if row['level'] == level_id]
        confirmed_pass = [row['id'] for row in members if row['state'] == ACCEPTED]
        confirmed_fail = [row['id'] for row in members if row['state'] == REJECTED]
        if confirmed_fail:
            state = REJECTED  # 任一组已确证不合格即不合格
        elif len(confirmed_pass) >= level['required']:
            state = ACCEPTED
        else:
            state = PENDING  # 合格组数量不足或仍不确定，待补
        level_rows.append(dict(id=level_id, state=state, required=level['required'],
                               confirmed_pass=confirmed_pass, confirmed_fail=confirmed_fail,
                               pending_groups=[row['id'] for row in members if row['state'] == PENDING],
                               reference_range=[level['lo'], level['hi']], tolerance=level['tolerance']))

    if any(row['state'] == REJECTED for row in level_rows):
        overall = REJECTED
    elif all(row['state'] == ACCEPTED for row in level_rows):
        overall = ACCEPTED
    else:
        overall = PENDING

    return dict(id=run_id, state=overall, unblinding_version=version,
                repeatability_limit=repeat_limit,
                acceptance_levels=level_rows, acceptance_groups=group_rows,
                evidence=dict(locked_codes=sorted(readings),
                              unblinding_version=version))
