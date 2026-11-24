"""开试前登记的母卷分区与样片清单，以及整卷批次判定。

登记内容在开试前固定：母卷分区、每区登记的样片、全卷共用的单位面积
透过限值、从各片试验起点计算的必测时点、判断截止时点和每区最少合格片数。
判定只消费归约出的累积质量区间（已含空白校正与抽液累计账），不在两次
取样之间插值，也不把截止以后的样点倒填进结论。
"""

from . import domain
from .artifacts import digest
from .contract import ContractError, ident, invariant, num, obj, records, unique_order
from .rules import decide

BLOCKERS = ('missing_piece', 'missing_required', 'untrusted_point', 'crossing_interval')
MAX_ZONES = 12


def _trial_source(piece, limit):
    """开试前登记的一次试验：同一片只允许这一份，不接受替换试验。"""
    trial = obj(piece.get('trial'), f"样片{piece['id']}的登记试验")
    invariant('id' not in trial and 'threshold' not in trial,
              f"样片{piece['id']}的试验不得自带标识或限值，限值以整卷登记为准")
    source = dict(trial)
    source['id'] = piece['id']
    source['threshold'] = limit
    return source


def parse_roll(source):
    source = obj(source, '母卷批次登记')
    roll_id = ident(source.get('id'), '母卷标识')
    limit = num(source.get('limit'), '单位面积透过限值', 0.000001)
    cutoff = num(source.get('cutoff'), '判断截止时点（分钟）', 0.000001)
    required = [num(value, '必测时点（分钟）', 0, cutoff)
                for value in list(source.get('required_points', []))]
    invariant(required, '必须至少登记一个必测时点')
    unique_order([dict(time=value) for value in required], 'time', '必测时点')
    min_pass = num(source.get('min_pass'), '每区最少合格片数', 1, 10_000)

    zones = records(source.get('zones'), '分区登记', MAX_ZONES, 1)
    pieces = {}
    parsed_zones = []
    for zone in zones:
        zone_id = ident(zone.get('id'), '分区标识')
        zone_pieces = records(zone.get('pieces'), f'分区{zone_id}的样片清单', 240, 1)
        registered = []
        for piece in zone_pieces:
            piece_id = ident(piece.get('id'), '样片标识')
            invariant(piece_id not in pieces, f'样片标识在全卷重复：{piece_id}')
            start = num(piece.get('test_start'), f'样片{piece_id}的试验起点（分钟）', 0)
            has_trial = isinstance(piece.get('trial'), dict)
            pieces[piece_id] = dict(id=piece_id, zone=zone_id, test_start=start,
                                    has_trial=has_trial)
            registered.append(piece_id)
            if has_trial:
                trial_source = _trial_source(piece, limit)
                model = domain.parse(trial_source)
                compiled = domain.evaluate(model)
                outputs = decide(model, compiled)
                pieces[piece_id]['packet'] = outputs
                pieces[piece_id]['model'] = model
        parsed_zones.append(dict(id=zone_id, pieces=registered))

    extra = source.get('extra_points')
    if extra is not None:
        invariant(isinstance(extra, list), '额外实测点声明应为清单')
        for row in extra:
            row = obj(row, '额外实测点声明')
            piece_id = ident(row.get('piece'), '额外点所属样片')
            invariant(piece_id in pieces, f'额外点引用了未登记样片：{piece_id}')
            invariant(isinstance(row.get('points'), list) and row['points'],
                      f'样片{piece_id}的额外点清单不能为空')
            for offset in row['points']:
                num(offset, f'样片{piece_id}的额外实测时点', 0, cutoff)

    return dict(id=roll_id, limit=limit, cutoff=cutoff, required_points=required,
                min_pass=min_pass, zones=parsed_zones, pieces=pieces,
                extra_declared=_declared_extras(source, pieces))


def _declared_extras(source, pieces):
    declared = {key: set() for key in pieces}
    for row in source.get('extra_points', []) or []:
        declared[row['piece']].update(row['points'])
    return declared


def _piece_blockers(piece, registration):
    """返回 (状态, 阻断明细, 判定时点, 下界, 上界)。"""
    limit, cutoff = registration['limit'], registration['cutoff']
    required = registration['required_points']
    if not piece['has_trial']:
        return 'undetermined', [dict(reason='missing_piece', detail='登记样片未提交开试前登记的那次试验',
                                     sample=None, offset=None, evidence=[])], None, None, None

    points = piece['packet']['mass']
    by_time = {point['time']: point for point in points}
    blockers = []
    decisive = None

    # 截止时点及以前的任何实际样点：下界到限即确认未通过；区间跨限则未定。
    for point in points:
        if point['time'] > cutoff:
            continue
        if point['lo'] is None:
            blockers.append(dict(reason='untrusted_point',
                                 detail='该取样已记录但没有可信质量区间（缺测或早先抽液带走未知质量）',
                                 sample=point['id'], offset=point['time'], evidence=list(point['evidence'])))
            continue
        if point['lo'] >= limit:
            return 'fail', [], point['time'], point['lo'], point['hi']
        if point['hi'] >= limit:
            blockers.append(dict(reason='crossing_interval',
                                 detail='质量区间跨过限值，上界到限而下界未到限，无法审结',
                                 sample=point['id'], offset=point['time'],
                                 evidence=list(point['evidence'])))
            decisive = point

    # 必测点必须在截止以内逐点有证；不允许在两次取样之间插值。
    for offset in required:
        point = by_time.get(offset)
        if point is None:
            blockers.append(dict(reason='missing_required',
                                 detail='必测时点没有对应取样，禁止插值或用相邻点顶替',
                                 sample=None, offset=offset, evidence=[]))
        elif point['lo'] is None:
            blockers.append(dict(reason='missing_required',
                                 detail='必测时点对应的取样没有可信质量区间',
                                 sample=point['id'], offset=offset, evidence=list(point['evidence'])))

    # 已登记的额外实测点落在截止前同样要检查；无点或无区间都不能报通过。
    for offset in registration['extra_declared'][piece['id']]:
        point = by_time.get(offset)
        if point is None:
            blockers.append(dict(reason='untrusted_point',
                                 detail='登记的额外实测点没有对应取样记录',
                                 sample=None, offset=offset, evidence=[]))
        elif point['lo'] is None:
            already = any(b['reason'] == 'untrusted_point' and b['sample'] == point['id'] for b in blockers)
            if not already:
                blockers.append(dict(reason='untrusted_point',
                                     detail='额外实测点已记录但没有可信质量区间，不能报通过',
                                     sample=point['id'], offset=offset, evidence=list(point['evidence'])))

    if blockers:
        order = {reason: i for i, reason in enumerate(BLOCKERS)}
        blockers.sort(key=lambda b: (order[b['reason']], b['offset'] if b['offset'] is not None else -1))
        point = decisive or next((by_time.get(offset) for offset in reversed(required)
                                  if by_time.get(offset) is not None), None)
        return 'undetermined', blockers, (None if point is None else point['time']), \
            (None if point is None else point['lo']), (None if point is None else point['hi'])

    last = max((point for point in points if point['time'] <= cutoff), key=lambda p: p['time'])
    return 'pass', [], last['time'], last['lo'], last['hi']


def adjudicate(source):
    registration = parse_roll(source)
    piece_rows = []
    verdicts = {}
    for zone in registration['zones']:
        for piece_id in zone['pieces']:
            piece = registration['pieces'][piece_id]
            state, blockers, time, lo, hi = _piece_blockers(piece, registration)
            verdicts[piece_id] = state
            piece_rows.append(dict(id=piece_id, zone=zone['id'], state=state,
                                   test_start=piece['test_start'], time=time, lo=lo, hi=hi,
                                   blockers=blockers,
                                   evidence=None if not piece['has_trial'] else
                                   {'mass_points': len(piece['packet']['mass']),
                                    'unresolved': [p['id'] for p in piece['packet']['mass']
                                                   if p['lo'] is None and p['time'] <= registration['cutoff']]}))

    zone_rows = []
    for zone in registration['zones']:
        states = [verdicts[piece_id] for piece_id in zone['pieces']]
        passed = states.count('pass')
        failed = states.count('fail')
        undetermined = states.count('undetermined')
        minimum = passed
        maximum = passed + undetermined
        if maximum < registration['min_pass']:
            state = 'reject'
        elif minimum >= registration['min_pass']:
            state = 'release'
        else:
            state = 'pending'
        zone_rows.append(dict(id=zone['id'], state=state, registered=len(states),
                              pass_count=passed, fail_count=failed,
                              undetermined_count=undetermined, min_possible=minimum,
                              max_possible=maximum, required_pass=registration['min_pass']))

    if any(row['state'] == 'reject' for row in zone_rows):
        roll_state = 'reject'
    elif all(row['state'] == 'release' for row in zone_rows):
        roll_state = 'release'
    else:
        roll_state = 'pending'

    outputs = dict(roll=dict(id=registration['id'], state=roll_state, limit=registration['limit'],
                             cutoff=registration['cutoff'], required_points=registration['required_points'],
                             min_pass=registration['min_pass'],
                             total_pass=sum(row['pass_count'] for row in zone_rows),
                             total_registered=sum(row['registered'] for row in zone_rows),
                             blockers=[b for row in piece_rows for b in row['blockers']]),
                   zones=zone_rows, pieces=piece_rows)
    packet = dict(project='permeance', kind='roll_batch', schema=1, subject=registration['id'],
                  source=source, source_digest=digest(source), outputs=outputs)
    packet['digest'] = digest(packet)
    return packet
