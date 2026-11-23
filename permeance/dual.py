"""双池对账：供液池与受液池各自留账，登记跨池转移单与成对检查点。

规则要点
- 转移单指向同一时刻、方向明确的两侧操作前取样记录；两侧记录都须是各池
  实际存在的取样，不用最近读数或插值凑成同时有证；每条记录只能被一张单使用。
- 转移从供液池扣除体积和所含示踪剂质量，在受液池登记同一笔量；不再按对外
  取液及零质量补液重复登记。
- 转移质量采用供液池操作前、已完成空白校正的浓度界限；同一笔转移在两侧账上
  是同一质量，而不是两个可独立挑值的范围。质量不明时可挡住单侧透过发布，
  但两侧合并的守恒核对不依赖这笔内部转移，不会仅因此失证。
- 外来补液不带示踪剂；对外取液沿用各池原有低限/缺测证据口径。
"""

from .blank_correction import correct_sample
from .contract import enum, ident, invariant, num, obj, records
from .domain import parse_pool


def analyze_dual(dual, model):
    dual = obj(dual, '双池对账数据')
    donor_source = obj(dual.get('donor'), '供液池数据')
    if 'max_blank_gap' not in donor_source:
        donor_source = {**donor_source, 'max_blank_gap': model['max_gap']}
    donor = parse_pool(donor_source, '供液池')
    receiver = model

    d_index = {r['id']: i for i, r in enumerate(donor['samples'])}
    r_index = {r['id']: i for i, r in enumerate(receiver['samples'])}

    transfers = read_transfers(dual, donor, receiver, d_index, r_index)
    checkpoints = read_checkpoints(dual, donor, receiver, d_index, r_index)
    verify_volumes(donor, receiver, transfers, d_index, r_index)

    d_bounds = [correct_sample(donor, r)[1] for r in donor['samples']]
    r_bounds = [correct_sample(receiver, r)[1] for r in receiver['samples']]

    transfer_rows = resolve_transfers(transfers, donor, d_bounds)
    by_donor = {t['donor_sample']: t for t in transfer_rows}
    by_receiver = {t['receiver_sample']: t for t in transfer_rows}

    area = model['area']
    receiver_ledger = build_ledger(receiver, r_bounds, by_receiver, 'receiver', area)
    donor_ledger = build_ledger(donor, d_bounds, by_donor, 'donor', area)
    checkpoint_rows = build_checkpoints(checkpoints, donor, receiver, d_bounds, r_bounds,
                                        donor_ledger, receiver_ledger, area)
    interval_rows = build_intervals(checkpoint_rows, donor_ledger, receiver_ledger)
    return dict(dual_transfer=transfer_rows,
                dual_receiver=receiver_ledger,
                dual_donor=donor_ledger,
                dual_checkpoint=checkpoint_rows,
                dual_interval=interval_rows)


def read_transfers(dual, donor, receiver, d_index, r_index):
    result = []
    seen_donor, seen_receiver = set(), set()
    for row in records(dual.get('transfers', []), '跨池转移单', 240):
        enum(row.get('direction'), ('donor_to_receiver',), '转移方向')
        donor_sample = ident(row.get('donor_sample'), '供液侧取样号')
        receiver_sample = ident(row.get('receiver_sample'), '受液侧取样号')
        invariant(donor_sample in d_index, '跨池转移引用未知的供液侧取样')
        invariant(receiver_sample in r_index, '跨池转移引用未知的受液侧取样')
        d_row = donor['samples'][d_index[donor_sample]]
        r_row = receiver['samples'][r_index[receiver_sample]]
        invariant(donor_sample not in seen_donor and receiver_sample not in seen_receiver,
                  '同一取样记录只能登记在一张跨池转移单上')
        invariant(d_row['time'] == r_row['time'], '跨池转移两侧记录必须指向同一时刻')
        volume = num(row.get('volume_ml'), '跨池转移体积', 0.000001, 1e4)
        seen_donor.add(donor_sample)
        seen_receiver.add(receiver_sample)
        result.append(dict(id=row['id'], direction='donor_to_receiver', time=d_row['time'],
                           volume_ml=volume, donor_sample=donor_sample,
                           receiver_sample=receiver_sample))
    return result


def read_checkpoints(dual, donor, receiver, d_index, r_index):
    result = []
    used_donor, used_receiver, times = set(), set(), set()
    for row in records(dual.get('checkpoints', []), '成对检查点', 24):
        donor_sample = ident(row.get('donor_sample'), '检查点供液侧取样号')
        receiver_sample = ident(row.get('receiver_sample'), '检查点受液侧取样号')
        invariant(donor_sample in d_index, '成对检查点引用未知的供液侧取样')
        invariant(receiver_sample in r_index, '成对检查点引用未知的受液侧取样')
        d_row = donor['samples'][d_index[donor_sample]]
        r_row = receiver['samples'][r_index[receiver_sample]]
        invariant(donor_sample not in used_donor and receiver_sample not in used_receiver,
                  '同一取样记录只能登记在一个成对检查点上')
        invariant(d_row['time'] not in times, '成对检查点时刻不能重复')
        invariant(d_row['time'] == r_row['time'], '成对检查点两侧必须是同一时刻各自的实际取样')
        used_donor.add(donor_sample)
        used_receiver.add(receiver_sample)
        times.add(d_row['time'])
        result.append(dict(id=row['id'], time=d_row['time'],
                           donor_sample=donor_sample, receiver_sample=receiver_sample))
    result.sort(key=lambda r: r['time'])
    return result


def verify_volumes(donor, receiver, transfers, d_index, r_index):
    """转移体积在两侧都按操作前可扣量核对，受液侧登记后不越界。"""
    for t in transfers:
        d_row = donor['samples'][d_index[t['donor_sample']]]
        r_row = receiver['samples'][r_index[t['receiver_sample']]]
        invariant(t['volume_ml'] <= d_row['before'] - d_row['removed'],
                  '转移体积超过供液池操作前可扣量')
        received = r_row['before'] - r_row['removed'] + t['volume_ml']
        invariant(0.000001 <= received <= 1e4, '受液池登记转移后体积越界')


def state_from(lo, hi):
    if lo is None:
        return 'blind'
    return 'known' if lo == hi else 'bounded'


def resolve_transfers(transfers, donor, d_bounds):
    """同一笔转移在两侧账上是同一质量，界限只取自供液侧操作前浓度。"""
    rows = []
    for t in transfers:
        i = next(i for i, r in enumerate(donor['samples']) if r['id'] == t['donor_sample'])
        bound = d_bounds[i]
        if bound['lo'] is None:
            lo = hi = None
            state = 'blind'
        else:
            lo = t['volume_ml'] * bound['lo']
            hi = t['volume_ml'] * bound['hi']
            state = state_from(lo, hi)
        rows.append(dict(id=t['id'], direction=t['direction'], time=t['time'],
                         volume_ml=t['volume_ml'], donor_sample=t['donor_sample'],
                         receiver_sample=t['receiver_sample'], lo=lo, hi=hi, state=state,
                         evidence={'concentration': t['donor_sample'],
                                   'blanks': list(bound['evidence'])}))
    return rows


def build_ledger(pool, bounds, linked, side, area):
    """逐取样点给出操作前透过累计（单位面积）。

    受液侧：操作前池内质量 + 历次对外取走质量 − 历次跨池直接转入质量。
    供液侧：以首个取样点为基线，由供液减少推算已透过膜的质量。
    对外取液缺测或转移质量不明都会让此后的单侧账失证。
    """
    rows = []
    blocked = []
    transfer_lo = transfer_hi = 0.0
    carry_lo = carry_hi = 0.0
    base = pool['samples'][0]
    base_bound = bounds[0]
    baseline_lo = None if base_bound['lo'] is None else base['before'] * base_bound['lo']
    baseline_hi = None if base_bound['hi'] is None else base['before'] * base_bound['hi']
    for i, (sample, bound) in enumerate(zip(pool['samples'], bounds, strict=True)):
        link = linked.get(sample['id'])
        blind = bound['lo'] is None or bool(blocked) or (side == 'donor' and baseline_lo is None)
        if side == 'receiver':
            if blind:
                lo = hi = None
            else:
                # 减去转移区间：下界用转移上界、上界用转移下界
                lo = sample['before'] * bound['lo'] + carry_lo - transfer_hi
                hi = sample['before'] * bound['hi'] + carry_hi - transfer_lo
        else:
            if i == 0:
                lo, hi = (None, None) if blind else (0.0, 0.0)
            elif blind:
                lo = hi = None
            else:
                lo = baseline_lo - sample['before'] * bound['hi'] - carry_hi + transfer_lo
                hi = baseline_hi - sample['before'] * bound['lo'] - carry_lo + transfer_hi
        evidence = list(dict.fromkeys([*bound['evidence'],
                                       *[s['id'] for s in pool['samples'][:i] if s['removed'] > 0],
                                       *([link['id']] if link else []),
                                       *blocked]))
        rows.append(dict(id=sample['id'], time=sample['time'],
                         lo=None if lo is None else lo / area,
                         hi=None if hi is None else hi / area,
                         state='blind' if blind else state_from(lo, hi),
                         transfer=link['id'] if link else None, evidence=evidence))
        # 本时点的对外取液与跨池转移在操作后才进入后续账
        if sample['removed'] > 0:
            if bound['lo'] is None:
                blocked.append(sample['id'])
            else:
                carry_lo += sample['removed'] * bound['lo']
                carry_hi += sample['removed'] * bound['hi']
        if link is not None:
            if link['lo'] is None:
                blocked.append(link['id'])
            else:
                transfer_lo += link['lo']
                transfer_hi += link['hi']
    return rows


def pool_current(pool, bounds, index, sample_id):
    """某时点操作前的池内示踪质量加累计对外取走质量（跨池转移不计入）。

    沿用各池原有证据口径：缺测若没有取液只影响本次快照，有取液才传给以后；
    跨池转移不进入全系统守恒量，因此转移质量不明不会让这里失证。
    """
    end = index[sample_id]
    run_lo = run_hi = 0.0
    blocked = False
    evidence = []
    for i in range(end + 1):
        sample, bound = pool['samples'][i], bounds[i]
        evidence.extend(bound['evidence'])
        if bound['lo'] is None:
            if sample['removed'] > 0:
                blocked = True
            continue
        run_lo += sample['removed'] * bound['lo']
        run_hi += sample['removed'] * bound['hi']
    last_bound = bounds[end]
    if blocked or last_bound['lo'] is None:
        return None, None, list(dict.fromkeys(evidence))
    before = pool['samples'][end]['before']
    return before * last_bound['lo'] + run_lo, before * last_bound['hi'] + run_hi, \
        list(dict.fromkeys(evidence))


def build_checkpoints(checkpoints, donor, receiver, d_bounds, r_bounds,
                      donor_ledger, receiver_ledger, area):
    d_index = {r['id']: i for i, r in enumerate(donor['samples'])}
    r_index = {r['id']: i for i, r in enumerate(receiver['samples'])}
    d_ledger = {r['id']: r for r in donor_ledger}
    r_ledger = {r['id']: r for r in receiver_ledger}
    rows = []
    for cp in checkpoints:
        d_lo, d_hi, d_ev = pool_current(donor, d_bounds, d_index, cp['donor_sample'])
        r_lo, r_hi, r_ev = pool_current(receiver, r_bounds, r_index, cp['receiver_sample'])
        # 全系统总质量差只合并两池各自证据；内部转移在两侧相抵，不进入守恒核对
        if d_lo is None or r_lo is None:
            lo = hi = None
        else:
            lo, hi = (d_lo + r_lo) / area, (d_hi + r_hi) / area
        donor_side = d_ledger[cp['donor_sample']]
        receiver_side = r_ledger[cp['receiver_sample']]
        rows.append(dict(id=cp['id'], time=cp['time'],
                         donor_sample=cp['donor_sample'], receiver_sample=cp['receiver_sample'],
                         lo=lo, hi=hi, state=state_from(lo, hi),
                         evidence={'donor': donor_side['state'], 'receiver': receiver_side['state'],
                                   'blanks': list(dict.fromkeys(d_ev + r_ev)),
                                   'donor_mass': None if d_lo is None else [d_lo, d_hi],
                                   'receiver_mass': None if r_lo is None else [r_lo, r_hi]}))
    base = rows[0] if rows else None
    for row in rows:
        if base is None or row is base:
            row['delta_lo'] = 0.0 if row['lo'] is not None else None
            row['delta_hi'] = 0.0 if row['hi'] is not None else None
        elif base['lo'] is None or row['lo'] is None:
            row['delta_lo'] = row['delta_hi'] = None
        else:
            row['delta_lo'] = row['lo'] - base['hi']
            row['delta_hi'] = row['hi'] - base['lo']
        row['delta_state'] = state_from(row['delta_lo'], row['delta_hi'])
    return rows


def build_intervals(checkpoint_rows, donor_ledger, receiver_ledger):
    """相邻成对检查点之间的两种透过推算与系统总量变化。

    起点当时发生的对外取补和跨池转移计入区间，终点当时的操作不计入；
    两个操作前快照之差天然满足该口径。
    """
    d_ledger = {r['id']: r for r in donor_ledger}
    r_ledger = {r['id']: r for r in receiver_ledger}
    rows = []
    for first, last in zip(checkpoint_rows, checkpoint_rows[1:]):
        r_a, r_b = r_ledger[first['receiver_sample']], r_ledger[last['receiver_sample']]
        d_a, d_b = d_ledger[first['donor_sample']], d_ledger[last['donor_sample']]
        rows.append(dict(id=f"{first['id']}/{last['id']}", start=first['time'], end=last['time'],
                         receiver_lo=None if r_a['lo'] is None or r_b['lo'] is None
                         else r_b['lo'] - r_a['hi'],
                         receiver_hi=None if r_a['hi'] is None or r_b['hi'] is None
                         else r_b['hi'] - r_a['lo'],
                         receiver_state='blind' if r_a['state'] == 'blind' or r_b['state'] == 'blind'
                         else state_from(r_b['lo'] - r_a['hi'], r_b['hi'] - r_a['lo']),
                         donor_lo=None if d_a['lo'] is None or d_b['lo'] is None
                         else d_b['lo'] - d_a['hi'],
                         donor_hi=None if d_a['hi'] is None or d_b['hi'] is None
                         else d_b['hi'] - d_a['lo'],
                         donor_state='blind' if d_a['state'] == 'blind' or d_b['state'] == 'blind'
                         else state_from(d_b['lo'] - d_a['hi'], d_b['hi'] - d_a['lo']),
                         system_lo=last['delta_lo'], system_hi=last['delta_hi'],
                         system_state=last['delta_state'],
                         evidence={'from': first['id'], 'to': last['id']}))
    return rows
